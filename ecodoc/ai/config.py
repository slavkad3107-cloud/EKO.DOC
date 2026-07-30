"""Конфигурация ИИ-слоя: ~/.ecodoc/config.json, секция "ai".

Ключи API никогда не пишутся в файл — только имена переменных окружения.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def config_dir() -> Path:
    """Папка настроек этой машины (env ECODOC_HOME читается при каждом
    обращении — иначе смена переменной после импорта не действует)."""
    return Path(os.environ.get("ECODOC_HOME", "") or Path.home() / ".ecodoc")


def config_path() -> Path:
    return config_dir() / "config.json"


def keys_path() -> Path:
    return config_dir() / "keys.json"



# переменные окружения с ключами по умолчанию для каждого провайдера
DEFAULT_KEY_ENV = {
    "cohere": "COHERE_API_KEY",       # бесплатный trial-ключ (20 запросов/мин)
    "cerebras": "CEREBRAS_API_KEY",   # бесплатный тариф, очень быстрый
    "moonshot": "MOONSHOT_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
    "together": "TOGETHER_API_KEY",
    "vsegpt": "VSEGPT_API_KEY",       # российский агрегатор
    "proxyapi": "PROXYAPI_API_KEY",   # российский прокси к OpenAI/Anthropic
    "gigachat": "GIGACHAT_AUTH_KEY",  # Authorization key (base64) Сбер
    "yandexgpt": "YANDEX_API_KEY",    # + YANDEX_FOLDER_ID
}


@dataclass
class AIConfig:
    provider: str = ""          # "ollama" | "anthropic" | "openai" | ...
    model: str = ""             # имя модели у провайдера
    embed_model: str = ""       # локальная эмбеддинг-модель (bge-m3 и т.п.)
    base_url: str = ""          # переопределение адреса (LM Studio, прокси)
    key_env: str = ""           # имя env-переменной с ключом
    # список запасных вариантов [{provider, model}, ...] — если основной недоступен
    fallbacks: list = field(default_factory=list)
    # найденные при setup локальные модели (информационно)
    detected: dict = field(default_factory=dict)


def load_config() -> AIConfig:
    cp = config_path()
    if cp.exists():
        data = json.loads(cp.read_text(encoding="utf-8-sig")).get("ai", {})
        known = {f for f in AIConfig.__dataclass_fields__}
        return AIConfig(**{k: v for k, v in data.items() if k in known})
    return AIConfig()


def save_config(cfg: AIConfig) -> Path:
    config_dir().mkdir(parents=True, exist_ok=True)
    cp, data = config_path(), {}
    if cp.exists():
        data = json.loads(cp.read_text(encoding="utf-8"))
    data["ai"] = asdict(cfg)
    cp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    return cp


def _read_keys(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def shared_keys_path() -> Path | None:
    """Файл ключей в ОБЩЕЙ базе (OneDrive) — ключ вводится один раз и
    работает на всех компьютерах пользователя. None, если база недоступна."""
    try:
        from ecodoc.core import workspace
        return workspace.root() / "ai_keys.json"
    except Exception:
        return None


def _saved_keys() -> dict:
    """Ключи: локальные (этой машины) поверх общих (из базы)."""
    keys = {}
    sp = shared_keys_path()
    if sp is not None:
        keys.update(_read_keys(sp))
    keys.update(_read_keys(keys_path()))
    return keys


def save_key(provider: str, key: str, shared: bool = False) -> Path:
    """Сохранить API-ключ провайдера. Пустой ключ — удалить сохранённый.

    shared=False — только на этой машине (~/.ecodoc/keys.json);
    shared=True  — в общую базу (OneDrive): ключ подхватится на всех
    компьютерах пользователя. Ключи не попадают в git — база отдельно.
    """
    path = (shared_keys_path() if shared else None) or keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = _read_keys(path)
    if key:
        keys[provider] = key
    else:
        keys.pop(provider, None)
    path.write_text(json.dumps(keys, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def has_key(provider: str) -> bool:
    env = DEFAULT_KEY_ENV.get(provider, "")
    if env and os.environ.get(env):
        return True
    return bool(_saved_keys().get(provider))


def api_key(cfg: AIConfig) -> str:
    # приоритет: явная env-переменная в конфиге → сохранённый ключ провайдера
    # → стандартная env-переменная провайдера
    if cfg.key_env and os.environ.get(cfg.key_env):
        return os.environ[cfg.key_env]
    saved = _saved_keys().get(cfg.provider, "")
    if saved:
        return saved
    env = DEFAULT_KEY_ENV.get(cfg.provider, "")
    return os.environ.get(env, "") if env else ""
