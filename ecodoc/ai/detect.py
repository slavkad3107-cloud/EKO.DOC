"""Автообнаружение локальных ИИ при установке/настройке.

`ecodoc ai setup` вызывает detect_all(): находит Ollama и LM Studio,
собирает список моделей, выбирает лучшую для извлечения данных и
эмбеддинг-модель, пишет конфиг.
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.request

from ecodoc.ai.config import AIConfig, DEFAULT_KEY_ENV, save_config

# порядок предпочтения локальных моделей для извлечения структурированных
# данных из русскоязычных документов (по убыванию качества на этой задаче)
_CHAT_PREFERENCE = ("qwen3", "qwen2.5", "llama3.3", "gemma3", "llama3.2",
                    "mistral", "deepseek-r1", "phi4", "llama3", "gemma2")
_EMBED_MARKERS = ("bge", "embed", "nomic", "mxbai", "e5")

# дефолтные модели для облачных провайдеров (быстрые и пригодные для
# извлечения структурных данных из русскоязычных документов)
CLOUD_DEFAULT_MODEL = {
    "deepseek": "deepseek-chat",
    "openrouter": "deepseek/deepseek-chat",
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-large-latest",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-2.5-flash",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "xai": "grok-2-latest",
    "vsegpt": "openai/gpt-4o-mini",
    "proxyapi": "gpt-4o-mini",
    "yandexgpt": "yandexgpt-lite/latest",
    "gigachat": "GigaChat",
}


def _ollama_models() -> list[str]:
    for base in (os.environ.get("OLLAMA_HOST_URL", ""),
                 "http://localhost:11434"):
        if not base:
            continue
        try:
            with urllib.request.urlopen(f"{base.rstrip('/')}/api/tags",
                                        timeout=4) as r:
                data = json.loads(r.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            continue
    return []


def _lmstudio_models() -> list[str]:
    try:
        with urllib.request.urlopen("http://localhost:1234/v1/models",
                                    timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m["id"] for m in data.get("data", [])]
    except Exception:
        return []


def pick_chat_model(models: list[str]) -> str:
    """Выбрать наиболее подходящую chat-модель: по предпочтению, затем размер."""
    chat = [m for m in models
            if not any(k in m.lower() for k in _EMBED_MARKERS)]
    for pref in _CHAT_PREFERENCE:
        cand = sorted(m for m in chat if m.lower().startswith(pref))
        if cand:
            return cand[-1]  # у одинаковых семейств берём последний тег
    return chat[0] if chat else ""


def pick_embed_model(models: list[str]) -> str:
    for m in models:
        if any(k in m.lower() for k in _EMBED_MARKERS):
            return m
    return ""


def detect_all() -> dict:
    """Обнаружить всё локальное + ключи внешних API в окружении."""
    found: dict = {"ollama": [], "lmstudio": [], "keys": []}
    if shutil.which("ollama") or _ollama_models():
        found["ollama"] = _ollama_models()
    found["lmstudio"] = _lmstudio_models()
    for prov, env in DEFAULT_KEY_ENV.items():
        if os.environ.get(env):
            found["keys"].append(prov)
    return found


def setup(prefer: str = "") -> AIConfig:
    """Составить и сохранить конфиг. prefer — принудительный провайдер."""
    found = detect_all()
    cfg = AIConfig(detected=found)

    if prefer:
        cfg.provider = prefer
    elif found["ollama"]:
        cfg.provider = "ollama"
    elif found["lmstudio"]:
        cfg.provider = "lmstudio"
    elif found["keys"]:
        cfg.provider = found["keys"][0]

    if cfg.provider == "ollama":
        cfg.model = pick_chat_model(found["ollama"])
        cfg.embed_model = pick_embed_model(found["ollama"])
    elif cfg.provider == "lmstudio":
        cfg.model = pick_chat_model(found["lmstudio"])
    elif cfg.provider:
        cfg.model = CLOUD_DEFAULT_MODEL.get(cfg.provider, "")

    # запасные варианты: сначала ВСЕ остальные локальные модели, затем
    # другой локальный сервер, затем внешние API по найденным ключам
    if cfg.provider == "ollama":
        seen = {cfg.model}
        for m in found["ollama"]:
            if m not in seen and not any(k in m.lower() for k in _EMBED_MARKERS):
                cfg.fallbacks.append({"provider": "ollama", "model": m})
                seen.add(m)
    if cfg.provider != "lmstudio" and found["lmstudio"]:
        cfg.fallbacks.append({"provider": "lmstudio",
                              "model": pick_chat_model(found["lmstudio"])})
    for prov in found["keys"]:
        if prov != cfg.provider:
            cfg.fallbacks.append({"provider": prov, "model": ""})
    save_config(cfg)
    return cfg


def describe(cfg: AIConfig) -> str:
    lines = [f"Провайдер: {cfg.provider or '(не выбран)'}",
             f"Модель:    {cfg.model or '(по умолчанию провайдера)'}"]
    if cfg.embed_model:
        lines.append(f"Эмбеддинги: {cfg.embed_model}")
    det = cfg.detected or {}
    if det.get("ollama"):
        lines.append("Ollama: " + ", ".join(det["ollama"]))
    if det.get("lmstudio"):
        lines.append("LM Studio: " + ", ".join(det["lmstudio"]))
    if det.get("keys"):
        lines.append("Ключи внешних API в окружении: " + ", ".join(det["keys"]))
    if cfg.fallbacks:
        lines.append("Fallback: " + ", ".join(f"{f['provider']}" for f in cfg.fallbacks))
    return "\n".join(lines)
