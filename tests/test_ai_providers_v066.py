"""v0.66: своя подпись клиента для Cloudflare (Groq/Cerebras), Ollama Cloud —
отдельный облачный провайдер, Z.ai GLM, честные причины отказа, ключ из
программы главнее переменной окружения."""
import json
import threading
import time

import pytest

from ecodoc.ai import config, detect, health, providers, registry
from ecodoc.ai.config import AIConfig
from ecodoc.ai.registry import FREE, is_ollama_cloud


class _Resp:
    def __init__(self, body):
        self._b = json.dumps(body).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_post_signs_requests_with_own_user_agent(monkeypatch):
    """Groq и Cerebras (Cloudflare) отбивают подпись «Python-urllib» кодом 1010."""
    seen = {}

    def fake_urlopen(req, timeout=None, context=None):
        seen["ua"] = req.get_header("User-agent")
        return _Resp({"ok": 1})

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    providers._post("https://api.groq.com/openai/v1/chat/completions", {}, {})
    assert seen["ua"].startswith("EcoDoc/") and "urllib" not in seen["ua"].lower()


def test_timeout_cap_limits_wait_only_inside_block(monkeypatch):
    seen = []
    monkeypatch.setattr(providers.urllib.request, "urlopen",
                        lambda req, timeout=None, context=None:
                        seen.append(timeout) or _Resp({}))
    with providers.timeout_cap(45):
        providers._post("http://x/api", {}, {})        # по умолчанию ждём 300 с
    providers._post("http://x/api", {}, {})
    assert seen == [45, 300]


@pytest.mark.parametrize("err, expect", [
    ("HTTP 403: error code: 1010", "1010"),
    ('HTTP 401: {"detail":"Your API key expired on 2026-09-08."}', "срок ключа истёк"),
    ('HTTP 402: {"message":"Payment required to access this resource."}', "оплата"),
    ('HTTP 403: { "success": false, "error": "Access denied by security policy." }',
     "регион"),
    ('HTTP 403: {"error":{"message":"Forbidden"}}', "регион"),
    ("HTTP 429: Request too large for model `qwen/qwen3.6-27b`", "лимит"),
    ('HTTP 401: {"error":{"message":"Invalid API Key"}}', "ключ не действует"),
    ("ollama_cloud: Ollama на этом компьютере не вошла в аккаунт ollama.com — "
     "выполните «ollama signin» (HTTP 401: unauthorized)", "ollama signin"),
])
def test_reason_names_the_real_cause(err, expect):
    assert expect in health._reason(err)[1]


def test_is_ollama_cloud():
    assert is_ollama_cloud("gpt-oss:120b-cloud") and is_ollama_cloud("nemotron-3-super:cloud")
    assert not is_ollama_cloud("qwen2.5:7b") and not is_ollama_cloud("")


def test_local_ollama_never_picks_cloud_model(monkeypatch):
    """После подключения облака облачный ярлык стоит в списке Ollama первым —
    проверка «Ollama (локально, приватно)» не должна уходить в облако."""
    monkeypatch.setattr(detect, "_ollama_tags", lambda: [
        "gpt-oss:20b-cloud", "nemotron-3-super:cloud", "qwen2.5:7b", "bge-m3:latest"])
    assert detect._ollama_models() == ["qwen2.5:7b", "bge-m3:latest"]
    assert detect._ollama_cloud_models() == ["gpt-oss:20b-cloud", "nemotron-3-super:cloud"]
    used = {}

    class Fake:
        def __init__(self, cfg):
            used["model"] = cfg.model

        def chat(self, s, u):
            return "работает"

    monkeypatch.setattr(providers, "get_provider", Fake)
    h = health.check_one(registry.by_id("ollama"))
    assert h.ok and used["model"] == "qwen2.5:7b"


def test_ollama_cloud_needs_no_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setattr(health, "_ollama_up", lambda: True)
    monkeypatch.setattr(providers, "get_provider",
                        lambda cfg: type("P", (), {"chat": lambda self, s, u: "работает"})())
    spec = registry.by_id("ollama_cloud/gpt-oss:120b-cloud")
    assert spec is not None and spec.tier == FREE
    h = health.check_one(spec)
    assert h.ok and h.reason == "работает"


def test_ollama_cloud_reports_ollama_down(monkeypatch):
    monkeypatch.setattr(health, "_ollama_up", lambda: False)
    h = health.check_one(registry.by_id("ollama_cloud/gpt-oss:120b-cloud"))
    assert not h.ok and h.reason == "сервер недоступен"


def test_ollama_cloud_pulls_missing_model_once(monkeypatch):
    calls = []

    def fake_post(url, payload, headers, timeout=300, **kw):
        calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("/api/chat") and calls.count("chat") == 1:
            raise providers.AIError(f'{url}: HTTP 404: {{"error":"model not found"}}')
        if url.endswith("/api/pull"):
            return {"status": "success"}
        return {"message": {"content": "работает"}}

    monkeypatch.setattr(providers, "_post", fake_post)
    p = providers.get_provider(AIConfig(provider="ollama_cloud", model="gemma4:31b-cloud"))
    assert p.chat("s", "u") == "работает"
    assert calls == ["chat", "pull", "chat"]


def test_ollama_cloud_explains_missing_signin(monkeypatch):
    def fake_post(url, payload, headers, timeout=300, **kw):
        raise providers.AIError(f"{url}: HTTP 401: unauthorized")

    monkeypatch.setattr(providers, "_post", fake_post)
    p = providers.get_provider(AIConfig(provider="ollama_cloud", model="gemma4:31b-cloud"))
    with pytest.raises(providers.AIError, match="ollama signin"):
        p.chat("s", "u")


def test_check_all_runs_ollama_cloud_one_at_a_time(monkeypatch, tmp_path):
    """Бесплатный ollama.com — 1 запрос одновременно: облако проверяется по
    очереди, остальное параллельно; порядок результатов сохраняется."""
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    lock, now = threading.Lock(), {"cloud": 0, "max": 0}

    def fake_check(spec):
        if spec.provider == "ollama_cloud":
            with lock:
                now["cloud"] += 1
                now["max"] = max(now["max"], now["cloud"])
            time.sleep(0.05)
            with lock:
                now["cloud"] -= 1
        return health.Health(provider=spec.provider, model=spec.model,
                             tier=spec.tier, ok=True)

    monkeypatch.setattr(health, "check_one", fake_check)
    res = health.check_all(registry.ALL)
    assert now["max"] == 1
    assert [h.provider for h in res] == [s.provider for s in registry.ALL]


def test_new_providers_are_wired_everywhere():
    ids = {s.id for s in registry.ALL}
    assert "zai/glm-4.7-flash" in ids and "groq/openai/gpt-oss-120b" in ids
    assert "groq/llama-3.3-70b-versatile" not in ids        # у Groq её больше нет
    for s in registry.ALL:
        assert s.provider in providers.PROVIDERS, s.provider
        assert s.provider in detect.PROVIDER_LABEL, s.provider
    assert providers.PROVIDERS["zai"].base_url == "https://api.z.ai/api/paas/v4"
    assert all(is_ollama_cloud(s.model) for s in registry.ALL
               if s.provider == "ollama_cloud")


def test_ollama_cloud_is_free_tier_before_local():
    ids = [s.id for s in registry.ranked()]
    assert ids.index("ollama_cloud/gpt-oss:120b-cloud") < ids.index("ollama")


def test_gui_marks_ollama_cloud_keyless(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    (tmp_path / "config.json").write_text(json.dumps(
        {"ai": {"provider": "cohere", "model": "command-a-03-2025"}}), encoding="utf-8")
    monkeypatch.setattr(detect, "_ollama_tags", lambda: [])
    from ecodoc.gui import server
    out = server.api_ai_config({}, {})
    cloud = next(x for x in out["providers"] if x["id"] == "ollama_cloud")
    assert cloud["keyless"] and cloud["has_key"] and not cloud["local"]
    zai = next(x for x in out["providers"] if x["id"] == "zai")
    assert not zai["keyless"] and not zai["has_key"]


def test_key_entered_in_program_beats_env_and_foreign_key_env(monkeypatch, tmp_path):
    """Новый ключ, введённый в программе, не должен перекрываться старым из
    переменной окружения; key_env чужого провайдера (хвост от прошлого выбора)
    не используется."""
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("MISTRAL_API_KEY", "old-expired")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("GROQ_API_KEY", "groq-from-env")
    config.save_key("mistral", "new-from-program")
    assert config.api_key(AIConfig(provider="mistral", key_env="MISTRAL_API_KEY")) \
        == "new-from-program"
    config.save_key("cohere", "cohere-key")
    assert config.api_key(AIConfig(provider="cohere", key_env="OPENROUTER_API_KEY")) \
        == "cohere-key"
    # сохранённого ключа нет — чужой key_env всё равно не берём, берём свою env
    assert config.api_key(AIConfig(provider="groq", key_env="OPENROUTER_API_KEY")) \
        == "groq-from-env"


def _fake_chat_post(seen):
    def fake_post(url, payload, headers, timeout=300, **kw):
        seen.update(url=url, payload=payload, auth=headers.get("Authorization"))
        return {"choices": [{"message": {"content": "работает"}}]}
    return fake_post


def test_zai_disables_thinking(monkeypatch, tmp_path):
    """У GLM «размышления» включены по умолчанию: 11 с вместо 2,7 с при том же
    качестве извлечения (замер 10.09.2026) — выключаем."""
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    config.save_key("zai", "z-key")
    seen = {}
    monkeypatch.setattr(providers, "_post", _fake_chat_post(seen))
    p = providers.get_provider(AIConfig(provider="zai", model="glm-4.7-flash"))
    assert p.chat("s", "u") == "работает"
    assert seen["url"] == "https://api.z.ai/api/paas/v4/chat/completions"
    assert seen["payload"]["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize("key, saved_acc, expect_acc", [
    ("acc123:tok", "", "acc123"),        # ключ вида «ID_аккаунта:токен»
    ("tok", "acc456", "acc456"),         # токен + отдельно сохранённый ID
])
def test_cloudflare_builds_account_url(monkeypatch, tmp_path, key, saved_acc, expect_acc):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    config.save_key("cloudflare", key)
    if saved_acc:
        config.save_key("cloudflare_account", saved_acc)
    seen = {}
    monkeypatch.setattr(providers, "_post", _fake_chat_post(seen))
    p = providers.get_provider(AIConfig(provider="cloudflare", model="@cf/openai/gpt-oss-120b"))
    assert p.chat("s", "u") == "работает"
    assert seen["url"] == ("https://api.cloudflare.com/client/v4/accounts/"
                           f"{expect_acc}/ai/v1/chat/completions")
    assert seen["auth"] == "Bearer tok"


def test_cloudflare_without_account_explains(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    config.save_key("cloudflare", "tok")
    p = providers.get_provider(AIConfig(provider="cloudflare", model="@cf/openai/gpt-oss-120b"))
    with pytest.raises(providers.AIError, match="ID аккаунта"):
        p.chat("s", "u")


def test_zero_rate_limit_means_plan_not_activated(monkeypatch):
    """Mistral без активированного бесплатного тарифа отвечает обычным 429;
    отличает его только заголовок «лимит 0 запросов в минуту»."""
    import io
    import urllib.error

    def fake_urlopen(req, timeout=None, context=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests",
                                     {"x-ratelimit-limit-req-minute": "0"},
                                     io.BytesIO(b'{"message":"Rate limit exceeded"}'))

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(providers.AIError) as err:
        providers._post("https://api.mistral.ai/v1/chat/completions", {}, {})
    assert "не активирован" in health._reason(str(err.value))[1]


def test_reason_model_not_in_tier_is_not_bad_key():
    err = ('HTTP 403: {"object":"error","message":"This model is not available in '
           'your subscription tier","type":"tier_not_allowed"}')
    assert health._reason(err)[1] == "модель недоступна на вашем тарифе"


def test_reason_cloudflare_token_without_workers_ai_rights():
    err = ('HTTP 401: {"success":false,"errors":[{"code":10000,'
           '"message":"Authentication error"}]}')
    assert "Workers AI" in health._reason(err)[1]
