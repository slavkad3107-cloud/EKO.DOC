"""Бесплатный Cohere по умолчанию: провайдер, автонастройка, лимит 20/мин."""
import json

import pytest

from ecodoc.ai import detect, providers
from ecodoc.ai.config import AIConfig
from ecodoc.ai.providers import AIError, CohereProvider


def test_cohere_parses_v2_response(monkeypatch):
    seen = {}

    def fake_post(url, payload, headers, **kw):
        seen.update(url=url, payload=payload, headers=headers)
        return {"message": {"content": [{"type": "text", "text": '{"ok":1}'}]}}

    monkeypatch.setattr(providers, "_post", fake_post)
    monkeypatch.setenv("COHERE_API_KEY", "test-key")
    out = CohereProvider(AIConfig(provider="cohere",
                                  model="command-a-03-2025")).chat("сис", "юзер")
    assert out == '{"ok":1}'
    assert seen["url"] == "https://api.cohere.com/v2/chat"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["payload"]["messages"][0]["role"] == "system"


def test_cohere_without_key_says_where_to_get_it(monkeypatch, tmp_path):
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    with pytest.raises(AIError, match="dashboard.cohere.com"):
        CohereProvider(AIConfig(provider="cohere")).chat("s", "u")


def test_setup_prefers_free_cloud_over_local(monkeypatch, tmp_path):
    """Есть бесплатный ключ — он и дефолт; локальная Ollama уходит в запас.

    Порядок бесплатных задан FREE_PREFERENCE (по замеру: Mistral впереди)."""
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setattr(detect, "detect_all", lambda: {
        "ollama": ["qwen2.5:7b", "bge-m3:latest"], "lmstudio": [],
        "keys": ["cohere", "mistral"]})
    cfg = detect.setup()
    assert cfg.provider == detect.FREE_PREFERENCE[0] == "mistral"
    assert cfg.model == detect.CLOUD_DEFAULT_MODEL["mistral"]
    chain = [f["provider"] for f in cfg.fallbacks]
    assert "cohere" in chain and "ollama" in chain
    assert chain.index("cohere") < chain.index("ollama")   # облако раньше
    assert cfg.embed_model == "bge-m3:latest"


def test_setup_cohere_chain_adds_fast_model(monkeypatch, tmp_path):
    """Если выбран Cohere — первым запасным идёт его же быстрая модель."""
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setattr(detect, "detect_all", lambda: {
        "ollama": [], "lmstudio": [], "keys": ["cohere"]})
    cfg = detect.setup()
    assert cfg.provider == "cohere"
    assert cfg.fallbacks[0] == {"provider": "cohere",
                                "model": "command-r7b-12-2024"}


def test_setup_falls_back_to_ollama_without_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setattr(detect, "detect_all", lambda: {
        "ollama": ["qwen2.5:7b"], "lmstudio": [], "keys": []})
    assert detect.setup().provider == "ollama"


def test_rate_limit_429_retries_same_provider(monkeypatch):
    """429 (лимит запросов/мин) — пауза и повтор ТОГО ЖЕ провайдера,
    а не уход на запасной."""
    calls = []

    class Flaky:
        def __init__(self, cfg):
            self.cfg = cfg

        def chat(self, system, user):
            calls.append(self.cfg.provider)
            if len(calls) == 1:
                raise AIError("api.cohere.com: HTTP 429: rate limit")
            return "ответ"

    monkeypatch.setattr(providers, "get_provider", lambda cfg: Flaky(cfg))
    monkeypatch.setattr(providers, "_RATE_WAIT", 0)
    cfg = AIConfig(provider="cohere", model="command-a-03-2025",
                   fallbacks=[{"provider": "mistral", "model": "m"}])
    text, used = providers.chat_with_fallback(cfg, "s", "u")
    assert text == "ответ"
    assert used.startswith("cohere/")
    assert calls == ["cohere", "cohere"]              # запасной не понадобился


def test_ensure_configured_uses_saved_config(monkeypatch, tmp_path):
    """Конфиг есть и переход на бесплатное облако уже был — ничего не трогаем."""
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps(
        {"ai": {"provider": "ollama", "model": "qwen2.5:7b",
                "detected": {"free_migrated": True}}}), encoding="utf-8")
    monkeypatch.setattr(detect, "setup", lambda *a, **k:
                        pytest.fail("не должно вызываться — конфиг уже есть"))
    assert detect.ensure_configured().provider == "ollama"


def test_migrate_local_to_free_once(monkeypatch, tmp_path):
    """Старый конфиг с Ollama + появился бесплатный ключ → переходим на облако,
    локальная модель уходит в запас. Повторно выбор пользователя не перебиваем."""
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setenv("COHERE_API_KEY", "k")
    (tmp_path / "config.json").write_text(json.dumps(
        {"ai": {"provider": "ollama", "model": "qwen2.5:7b"}}), encoding="utf-8")
    cfg = detect.ensure_configured()
    assert (cfg.provider, cfg.model) == ("cohere", "command-a-03-2025")
    assert {"provider": "ollama", "model": "qwen2.5:7b"} in cfg.fallbacks
    # пользователь осознанно вернулся на Ollama — второй раз не перебиваем
    cfg.provider, cfg.model = "ollama", "qwen2.5:7b"
    from ecodoc.ai.config import save_config
    save_config(cfg)
    assert detect.ensure_configured().provider == "ollama"


def test_key_can_be_saved_to_shared_base(monkeypatch, tmp_path):
    """Ключ в общей базе (OneDrive) виден программе на любом компьютере."""
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "base"))
    from ecodoc.ai import config as C
    (tmp_path / "base").mkdir()
    path = C.save_key("cohere", "shared-key", shared=True)
    assert path == tmp_path / "base" / "ai_keys.json"
    assert C.has_key("cohere")
    assert C.api_key(AIConfig(provider="cohere")) == "shared-key"
    # локальный ключ этой машины важнее общего
    C.save_key("cohere", "local-key")
    assert C.api_key(AIConfig(provider="cohere")) == "local-key"
