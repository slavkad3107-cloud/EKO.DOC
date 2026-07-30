"""Реестр моделей, проверка работоспособности и выбор лучшей по ТЗ.

Ранжирование из ТЗ: сначала большие бесплатные, потом локальные,
и только потом платный DeepSeek.
"""
import json
import time

from ecodoc.ai import health, registry
from ecodoc.ai.config import load_config
from ecodoc.ai.health import Health
from ecodoc.ai.registry import FREE, LOCAL, PAID


def test_registry_covers_keys_from_tz():
    provs = {s.provider for s in registry.ALL}
    # все провайдеры, ключи которых пользователь дал в ТЗ
    for p in ("deepseek", "openai", "gemini", "anthropic", "moonshot", "mistral",
              "openrouter", "groq", "cerebras", "cohere", "ollama"):
        assert p in provs, p


def test_ranked_order_free_then_local_then_paid():
    tiers = [s.tier for s in registry.ranked()]
    assert tiers.index(FREE) < tiers.index(LOCAL) < tiers.index(PAID)
    # внутри бесплатных первым идёт замеренный лучший (Mistral Small)
    assert registry.ranked()[0].id == "mistral/mistral-small-latest"
    # DeepSeek — первый среди платных, и он позже локальных
    paid = [s for s in registry.ranked() if s.tier == PAID]
    assert paid[0].provider == "deepseek"


def test_reason_recognises_region_block_not_bad_key():
    """403 с телом Cloudflare 1010 и «location is not supported» — это регион,
    а не «ключ не действует» (иначе пользователь зря меняет ключ)."""
    code, why = health._reason("https://api.groq.com/...: HTTP 403: error code: 1010")
    assert code == 403 and "регион" in why
    code, why = health._reason('HTTP 400: {"message": "User location is not '
                               'supported for the API use."}')
    assert "регион" in why and "VPN" in why
    assert health._reason("HTTP 429: quota")[1].startswith("лимит")
    assert health._reason('HTTP 400: {"error":"credit balance is too low"}')[1] \
        == "недостаточно средств"
    assert health._reason("HTTP 401: unauthorized")[1] == "ключ не действует"


def _res(items):
    return [Health(provider=p, model=m, tier=t, ok=ok, sec=s)
            for p, m, t, ok, s in items]


def test_pick_best_prefers_free_over_local_and_paid(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    results = _res([
        ("deepseek", "deepseek-chat", PAID, True, 1.0),      # платный и быстрый
        ("ollama", "qwen2.5:7b", LOCAL, True, 20.0),
        ("mistral", "mistral-small-latest", FREE, True, 9.0),
        ("groq", "llama-3.3-70b-versatile", FREE, False, 0.5),
    ])
    cfg, _ = health.pick_best(results)
    assert (cfg.provider, cfg.model) == ("mistral", "mistral-small-latest")
    chain = [f["provider"] for f in cfg.fallbacks]
    assert chain.index("ollama") < chain.index("deepseek")   # платный — последним
    assert "groq" not in chain                               # нерабочие не берём


def test_pick_best_falls_to_local_when_no_free(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    results = _res([
        ("deepseek", "deepseek-chat", PAID, True, 1.0),
        ("ollama", "qwen2.5:7b", LOCAL, True, 30.0),
        ("mistral", "mistral-small-latest", FREE, False, 0.4),
    ])
    cfg, _ = health.pick_best(results)
    assert cfg.provider == "ollama"          # локальная раньше платной
    assert cfg.fallbacks[0]["provider"] == "deepseek"


def test_pick_best_keeps_config_when_nothing_works(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps(
        {"ai": {"provider": "cohere", "model": "command-a-03-2025"}}),
        encoding="utf-8")
    cfg, _ = health.pick_best(_res([("groq", "x", FREE, False, 0.1)]))
    assert cfg.provider == "cohere"          # прошлый выбор не затираем


def test_cache_roundtrip_and_ttl(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    health.save_cache(_res([("mistral", "mistral-small-latest", FREE, True, 9.0)]))
    checked, items = health.load_cache()
    assert items and items[0].ok and items[0].id == "mistral/mistral-small-latest"
    assert health.fresh(ttl=3600)            # свежий кэш отдаётся
    assert not health.fresh(ttl=0)           # просроченный — нет
    assert not (tmp_path / "ai_health.tmp").exists()   # запись атомарна


def test_check_one_reports_missing_key_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))

    def boom(cfg):
        raise AssertionError("сетевого запроса быть не должно — ключа нет")

    monkeypatch.setattr("ecodoc.ai.providers.get_provider", boom)
    h = health.check_one(registry.by_id("cohere/command-a-03-2025"))
    assert not h.ok and h.reason == "нет ключа"


def test_check_one_marks_local_ollama_down(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setattr(health, "_ollama_models", lambda: [])
    h = health.check_one(registry.by_id("ollama"))
    assert not h.ok and h.reason == "сервер недоступен"


def test_summary_mentions_chosen_model():
    text = health.summary(_res([
        ("mistral", "mistral-small-latest", FREE, True, 9.0),
        ("deepseek", "deepseek-chat", PAID, True, 1.0)]))
    assert "Выбрана: mistral/mistral-small-latest" in text
    assert "deepseek" in text
