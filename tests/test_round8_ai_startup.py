"""09.09.2026: автовыбор при запуске с подтверждением, живые модели OpenRouter
в ранжировании, ручной выбор не откатывается панелью, автовыбор по кнопке,
проверка источников структурой с автокоррекцией."""
from ecodoc.ai import detect, health, registry
from ecodoc.ai.config import AIConfig, load_config, save_config
from ecodoc.gui import server


def _h(provider, model, ok=True, sec=1.0):
    return health.Health(provider=provider, model=model, tier="free", ok=ok, sec=sec)


def test_live_openrouter_free_ranks_before_local(monkeypatch):
    # живая бесплатная модель OpenRouter (не из вшитого реестра) — выше Ollama
    save_config(AIConfig(provider="", detected={"openrouter_models": ["nvidia/nemotron-3.5-lightning:free"]}))
    res = [_h("ollama", "qwen2.5:7b", sec=5), _h("openrouter", "nvidia/nemotron-3.5-lightning:free", sec=40)]
    top = health.ranked_working(res)[0]
    assert top.provider == "openrouter"


def test_panel_does_not_overwrite_manual_choice(monkeypatch):
    monkeypatch.setattr(detect, "_ollama_models", lambda: [])
    best = AIConfig(provider="mistral", model="mistral-small-latest")
    monkeypatch.setattr("ecodoc.ai.health.fresh", lambda: ["x"])
    monkeypatch.setattr("ecodoc.ai.health.pick_best", lambda checked: (best, checked))
    server.api_ai_save({}, {"provider": "cohere", "model": "command-a-03-2025"})
    conf = server.api_ai_config({}, {})
    assert (conf["provider"], conf["model"]) == ("cohere", "command-a-03-2025")
    assert conf["picked_by"] == "user" and conf["auto_pick"] is True
    # и приём (ensure_configured) в этой сессии тоже уважает ручной выбор
    out = detect.ensure_configured()
    assert (out.provider, out.model) == ("cohere", "command-a-03-2025")


def test_startup_note_confirms_applied_model(monkeypatch):
    results = [_h("cohere", "command-a-03-2025"), _h("ollama", "qwen2.5:7b", sec=9)]
    monkeypatch.setattr(health, "check_all", lambda specs=None, workers=8: results)
    save_config(AIConfig(provider="ollama", model="qwen2.5:7b", detected={"picked_by": "user"}))
    server._startup_ai_check()
    note = server.STARTUP_NOTES["ai"]
    assert note["applied"] and note["works"] and "подтверждено" in note["text"]
    assert (note["provider"], note["model"]) == ("cohere", "command-a-03-2025")
    assert load_config().provider == "cohere"
    meta = server.api_meta({}, {})
    assert meta["ai"]["provider"] == "cohere" and meta["ai"]["picked_by"] == "health"


def test_autopick_button(monkeypatch):
    results = [_h("cohere", "command-a-03-2025")]
    monkeypatch.setattr(health, "fresh", lambda: results)
    save_config(AIConfig(provider="ollama", model="qwen2.5:7b", detected={"picked_by": "user"}))
    note = server.api_ai_autopick({}, {})
    assert note["applied"] and load_config().provider == "cohere"
    assert load_config().detected.get("picked_by") == "health"


def test_sources_struct_and_autocorrect(monkeypatch):
    from ecodoc.watch import watcher
    srcs = [{"id": "rates", "name": "Ставки платы за НВОС", "url": "http://x", "forms": ["declaration-nvos"]},
            {"id": "rosstat", "name": "Росстат — альбом форм", "url": "http://y", "forms": []},
            {"id": "fkko", "name": "ФККО", "url": "http://z", "forms": []}]
    monkeypatch.setattr(watcher, "load_sources", lambda: srcs)

    def fake_check(src, save=True):
        st = {"rates": "changed", "rosstat": "error", "fkko": "same"}[src["id"]]
        return {"name": src["name"], "status": st,
                "detail": "HTTP Error 502: Bad Gateway" if st == "error" else ""}
    monkeypatch.setattr(watcher, "check_source", fake_check)
    res = watcher.run_check_struct()
    assert [c["id"] for c in res["changed"]] == ["rates"]
    assert "временно недоступен" in res["errors"][0]["detail"]
    assert "изменилось: 1" in res["summary"] and "ИЗМЕНИЛОСЬ" in res["text"]
    monkeypatch.setattr("ecodoc.core.rates_update.check_online",
                        lambda timeout=10: {"newer": False, "text": "новее нет", "latest_act": "2409-р"})
    auto = server._auto_correct(res)
    assert auto and "справочник актуален" in auto[0]
    assert watcher._friendly("CERTIFICATE_VERIFY_FAILED").startswith("сертификат")
