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

# человекочитаемые метки провайдеров (для выпадающего списка в GUI)
PROVIDER_LABEL = {
    "cohere": "Cohere (облако, БЕСПЛАТНЫЙ ключ — по умолчанию)",
    "cerebras": "Cerebras (облако, бесплатный тариф, очень быстро)",
    "deepseek": "DeepSeek (облако, быстро)",
    "openrouter": "OpenRouter (облако, много моделей)",
    "groq": "Groq (облако, очень быстро)",
    "mistral": "Mistral (облако)",
    "gemini": "Google Gemini (облако)",
    "openai": "OpenAI / GPT (облако)",
    "anthropic": "Anthropic / Claude (облако)",
    "together": "Together (облако)",
    "xai": "xAI / Grok (облако)",
    "vsegpt": "VseGPT (облако, РФ-агрегатор)",
    "proxyapi": "ProxyAPI (облако, РФ-прокси)",
    "gigachat": "GigaChat (Сбер, облако)",
    "yandexgpt": "YandexGPT (облако)",
    "ollama": "Ollama (локально, приватно)",
    "lmstudio": "LM Studio (локально)",
}

# пресеты моделей на провайдера (пользователь выбирает из списка или вводит
# своё). Для ollama/lmstudio список подтягивается из установленных моделей.
KNOWN_MODELS = {
    "cohere": ["command-a-03-2025", "command-r7b-12-2024", "command-r-08-2024",
               "command-a-plus-05-2026", "command-r-plus-08-2024"],
    "cerebras": ["llama-3.3-70b", "qwen-3-32b", "gpt-oss-120b", "llama3.1-8b"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "openrouter": ["openai/gpt-oss-20b:free", "deepseek/deepseek-chat",
                   "meta-llama/llama-3.3-70b-instruct",
                   "google/gemini-2.0-flash-001", "openai/gpt-4o-mini",
                   "qwen/qwen-2.5-72b-instruct"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant",
             "openai/gpt-oss-120b", "qwen/qwen3-32b"],
    "mistral": ["mistral-large-latest", "mistral-small-latest", "open-mistral-nemo"],
    "gemini": ["gemini-flash-latest", "gemini-2.0-flash", "gemini-2.5-flash"],
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o3-mini"],
    "anthropic": ["claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-opus-4-8"],
    "together": ["meta-llama/Llama-3.3-70B-Instruct-Turbo",
                 "Qwen/Qwen2.5-72B-Instruct-Turbo"],
    "xai": ["grok-2-latest"],
    "vsegpt": ["openai/gpt-4o-mini", "deepseek/deepseek-chat"],
    "proxyapi": ["gpt-4o-mini", "gpt-4o"],
    "gigachat": ["GigaChat", "GigaChat-Pro", "GigaChat-Max"],
    "yandexgpt": ["yandexgpt-lite/latest", "yandexgpt/latest"],
}

# провайдеры с БЕСПЛАТНЫМ тарифом — порядок предпочтения при автонастройке.
# Проверено на задаче извлечения из русских документов (18.07.2026):
# cohere command-a ~3 с/документ, mistral small ~1 с, openrouter :free ~6 с,
# gemini flash ~13 с. Cohere первым: бесплатный ключ без карты и без
# ограничения по дням (лимит — 20 запросов/мин, обрабатывается ретраем).
FREE_PREFERENCE = ("cohere", "cerebras", "groq", "mistral", "openrouter", "gemini")

# дефолтные модели для облачных провайдеров (быстрые и пригодные для
# извлечения структурных данных из русскоязычных документов)
CLOUD_DEFAULT_MODEL = {
    "cohere": "command-a-03-2025",
    "cerebras": "llama-3.3-70b",
    "deepseek": "deepseek-chat",
    "openrouter": "openai/gpt-oss-20b:free",   # бесплатная модель агрегатора
    "groq": "llama-3.3-70b-versatile",
    "mistral": "mistral-small-latest",         # бесплатный тариф Mistral
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-flash-latest",
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
    """Составить и сохранить конфиг. prefer — принудительный провайдер.

    По умолчанию берём БЕСПЛАТНОЕ облако (Cohere и далее по FREE_PREFERENCE):
    оно на порядок быстрее локальной модели на слабой машине и не требует
    видеокарты. Локальная Ollama остаётся в конце цепочки — работает без
    интернета и без лимитов.
    """
    found = detect_all()
    cfg = AIConfig(detected=found)
    free_keys = [p for p in FREE_PREFERENCE if p in found["keys"]]

    if prefer:
        cfg.provider = prefer
    elif free_keys:
        cfg.provider = free_keys[0]           # бесплатное облако (Cohere и т.д.)
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

    # запасные варианты. Порядок: у Cohere — своя быстрая модель (лимит
    # 20 запросов/мин у бесплатного ключа), затем остальные бесплатные облака
    # по ключам, затем прочие ключи, затем ЛОКАЛЬНЫЕ модели (последний рубеж:
    # медленно, зато без интернета и лимитов).
    if cfg.provider == "cohere":
        cfg.fallbacks.append({"provider": "cohere",
                              "model": "command-r7b-12-2024"})
    for prov in free_keys + [p for p in found["keys"] if p not in FREE_PREFERENCE]:
        if prov != cfg.provider:
            cfg.fallbacks.append({"provider": prov,
                                  "model": CLOUD_DEFAULT_MODEL.get(prov, "")})
    if cfg.provider != "ollama":
        for m in found["ollama"]:
            if not any(k in m.lower() for k in _EMBED_MARKERS):
                cfg.fallbacks.append({"provider": "ollama", "model": m})
    else:
        seen = {cfg.model}
        for m in found["ollama"]:
            if m not in seen and not any(k in m.lower() for k in _EMBED_MARKERS):
                cfg.fallbacks.append({"provider": "ollama", "model": m})
                seen.add(m)
    if cfg.provider != "lmstudio" and found["lmstudio"]:
        cfg.fallbacks.append({"provider": "lmstudio",
                              "model": pick_chat_model(found["lmstudio"])})
    if not cfg.embed_model:
        cfg.embed_model = pick_embed_model(found["ollama"])
    save_config(cfg)
    return cfg


def ensure_configured() -> AIConfig:
    """Конфиг для работы; если ИИ ещё не настроен — настроить автоматически.

    «Из коробки» пользователь ничего не выбирает: есть ключ бесплатного
    облака (COHERE_API_KEY) — работаем через него, нет — через локальную
    Ollama. Результат сохраняется, чтобы не детектить каждый раз.
    """
    from ecodoc.ai.config import load_config
    cfg = load_config()
    if not cfg.provider:
        return setup()
    return _migrate_to_free(cfg)


def _migrate_to_free(cfg: AIConfig) -> AIConfig:
    """Одноразовый переход на бесплатное облако.

    Старые конфиги выбирали локальную Ollama (минуты на документ). Если
    появился ключ бесплатного облака — переключаемся на него, а локальные
    модели остаются в запасе. Делается ОДИН раз: отметка в detected, чтобы
    осознанный возврат к Ollama потом не перебивался.
    """
    from ecodoc.ai.config import has_key, save_config
    det = cfg.detected if isinstance(cfg.detected, dict) else {}
    if det.get("free_migrated") or cfg.provider not in ("ollama", "lmstudio", ""):
        return cfg
    free = next((p for p in FREE_PREFERENCE if has_key(p)), "")
    if not free:
        return cfg
    old = {"provider": cfg.provider, "model": cfg.model}
    cfg.provider, cfg.model = free, CLOUD_DEFAULT_MODEL.get(free, "")
    fb = []
    if free == "cohere":
        fb.append({"provider": "cohere", "model": "command-r7b-12-2024"})
    fb += [{"provider": p, "model": CLOUD_DEFAULT_MODEL.get(p, "")}
           for p in FREE_PREFERENCE if p != free and has_key(p)]
    if old["provider"]:
        fb.append(old)                       # локальная модель — последний рубеж
    fb += [f for f in cfg.fallbacks
           if f.get("provider") not in {x["provider"] for x in fb}]
    cfg.fallbacks = fb
    det["free_migrated"] = True
    cfg.detected = det
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
