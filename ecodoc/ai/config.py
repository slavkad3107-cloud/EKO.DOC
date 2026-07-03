"""Конфигурация ИИ-слоя: ~/.ecodoc/config.json, секция "ai".

Ключи API никогда не пишутся в файл — только имена переменных окружения.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("ECODOC_HOME", Path.home() / ".ecodoc"))
CONFIG_PATH = CONFIG_DIR / "config.json"

# переменные окружения с ключами по умолчанию для каждого провайдера
DEFAULT_KEY_ENV = {
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
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")).get("ai", {})
        known = {f for f in AIConfig.__dataclass_fields__}
        return AIConfig(**{k: v for k, v in data.items() if k in known})
    return AIConfig()


def save_config(cfg: AIConfig) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["ai"] = asdict(cfg)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return CONFIG_PATH


def api_key(cfg: AIConfig) -> str:
    env = cfg.key_env or DEFAULT_KEY_ENV.get(cfg.provider, "")
    return os.environ.get(env, "") if env else ""
