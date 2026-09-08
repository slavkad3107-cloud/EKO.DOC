"""Список моделей OpenRouter обновляется автоматически (08.09.2026):
бесплатные впереди в порядке пользователя, исчезнувшие убираются, живой
список виден в «Выборе ИИ» и в проверке «здоровья»; обслуживание при старте."""
import io
import json

from ecodoc.ai import detect, registry
from ecodoc.ai.config import AIConfig, load_config, save_config


def _fake_models():
    return {"data": [
        {"id": "nvidia/nemotron-3-super-120b-a12b:free", "pricing": {"prompt": "0", "completion": "0"},
         "context_length": 131072, "architecture": {"input_modalities": ["text"]}},
        {"id": "google/gemma-4-31b-it:free", "pricing": {"prompt": "0", "completion": "0"},
         "context_length": 32768, "architecture": {"input_modalities": ["text", "image"]}},
        {"id": "qwen/qwen3-235b:free", "pricing": {"prompt": "0", "completion": "0"},
         "context_length": 65536, "architecture": {"input_modalities": ["text"]}},
        {"id": "deepseek/deepseek-chat", "pricing": {"prompt": "0.0000003", "completion": "0.0000012"},
         "context_length": 65536, "architecture": {"input_modalities": ["text"]}},
        {"id": "openai/gpt-4o-mini", "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
         "context_length": 128000, "architecture": {"input_modalities": ["text", "image"]}},
    ]}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_refresh_keeps_user_order_and_drops_missing(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=10: _Resp(json.dumps(_fake_models()).encode()))
    save_config(AIConfig(provider="openrouter", model="nvidia/nemotron-3-ultra-550b-a55b:free"))
    res = detect.refresh_openrouter_models(timeout=5)
    models = res["models"]
    # ultra исчезла → убрана, super (порядок пользователя) впереди, потом gemma, новая qwen,
    # платные пользователя — в конце
    assert models[0] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert models[1] == "google/gemma-4-31b-it:free"
    assert "qwen/qwen3-235b:free" in models
    assert models[-2:] == ["deepseek/deepseek-chat", "openai/gpt-4o-mini"]
    assert "nvidia/nemotron-3-ultra-550b-a55b:free" in res["gone"]
    assert res["vision"] == ["google/gemma-4-31b-it:free", "openai/gpt-4o-mini"]
    # модель по умолчанию исчезла → переключено на первую бесплатную, список сохранён
    cfg = load_config()
    assert cfg.model == models[0] and res["switched_from"].endswith("ultra-550b-a55b:free")
    assert detect.known_models("openrouter") == models
    assert any(s.model == "qwen/qwen3-235b:free" for s in registry.all_specs())


def test_refresh_without_network_keeps_builtin_list(monkeypatch):
    def boom(req, timeout=10):
        raise OSError("нет сети")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    res = detect.refresh_openrouter_models(timeout=1)
    assert "error" in res and res["models"] == detect.known_models("openrouter")
    assert detect.known_models("openrouter")[0].startswith("nvidia/nemotron-3-ultra")


def test_maintenance_once_records_notes(monkeypatch):
    from ecodoc.gui import server
    monkeypatch.setattr(detect, "refresh_openrouter_models",
                        lambda timeout=10: {"text": "OpenRouter: моделей 3", "models": ["x:free"]})
    monkeypatch.setattr(server, "_startup_rates_check",
                        lambda: server.STARTUP_NOTES.__setitem__("rates", {"text": "ставки: новее нет"}))
    out = server._maintenance_once(first=True)
    assert out["models"] == "OpenRouter: моделей 3" and out["rates"] == "ставки: новее нет"
    assert server.STARTUP_NOTES["maintenance"]["at"]
    assert "models_refresh" in server.POST_ROUTES
