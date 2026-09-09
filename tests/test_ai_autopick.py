"""При каждом запуске проверяются модели и применяется оптимальная (08.09.2026);
ручной выбор закрепляется только снятой галочкой auto_pick."""
from ecodoc.ai import detect, health
from ecodoc.ai.config import AIConfig, load_config, save_config
from ecodoc.gui import server


def test_ensure_configured_repicks_unless_pinned(monkeypatch):
    best = AIConfig(provider="mistral", model="mistral-small-latest")
    monkeypatch.setattr("ecodoc.ai.health.fresh", lambda: ["x"])
    monkeypatch.setattr("ecodoc.ai.health.pick_best", lambda checked: (best, checked))
    # ручной выбор в сессии держится до следующего запуска (09.09.2026):
    # автовыбор — только при старте и по кнопке, ensure_configured не перевыбирает
    save_config(AIConfig(provider="cohere", model="command-a", detected={"picked_by": "user"}))
    out = detect.ensure_configured()
    assert (out.provider, out.model) == ("cohere", "command-a")
    # без ручного выбора (picked_by health/пусто) — берётся оптимальная из свежей проверки
    save_config(AIConfig(provider="ollama", model="q", detected={"picked_by": "health"}))
    out1 = detect.ensure_configured()
    assert (out1.provider, out1.model) == ("mistral", "mistral-small-latest")
    # закреплено (auto_pick False) → остаётся ручной
    save_config(AIConfig(provider="cohere", model="command-a",
                         detected={"picked_by": "user", "auto_pick": False}))
    out2 = detect.ensure_configured()
    assert (out2.provider, out2.model) == ("cohere", "command-a")


def _h(provider, model, ok=True, sec=1.0):
    return health.Health(provider=provider, model=model, tier="free", ok=ok, sec=sec)


def test_startup_check_runs_every_time_and_applies(monkeypatch):
    calls = []
    results = [_h("cohere", "command-a-03-2025"), _h("openrouter", "x:free", sec=80)]
    monkeypatch.setattr(health, "fresh", lambda: ["свежий кэш"])      # раньше — срезало
    monkeypatch.setattr(health, "check_all", lambda specs=None, workers=8: calls.append(1) or results)
    save_config(AIConfig(provider="openrouter", model="x:free", detected={"picked_by": "user"}))
    server._startup_ai_check()
    assert calls and "выбрана оптимальная" in server.STARTUP_NOTES["ai"]["text"]
    cfg = load_config()
    assert cfg.provider == "cohere"
    # закреплённый выбор не трогаем, но проверка всё равно выполняется
    save_config(AIConfig(provider="openrouter", model="x:free",
                         detected={"picked_by": "user", "auto_pick": False}))
    server._startup_ai_check()
    assert len(calls) == 2 and "закреплена вручную" in server.STARTUP_NOTES["ai"]["text"]
    assert load_config().provider == "openrouter"


def test_ai_save_and_config_carry_auto_pick(monkeypatch):
    monkeypatch.setattr(detect, "ensure_configured", lambda: load_config())
    monkeypatch.setattr(detect, "_ollama_models", lambda: [])
    server.api_ai_save({}, {"provider": "cohere", "model": "command-a-03-2025", "auto_pick": False})
    assert server.api_ai_config({}, {})["auto_pick"] is False
    server.api_ai_save({}, {"provider": "cohere", "model": "command-a-03-2025"})
    assert server.api_ai_config({}, {})["auto_pick"] is True
