"""Слой ИИ-анализа документов.

Единая точка доступа к локальным (Ollama, LM Studio) и внешним
(Anthropic, OpenAI, OpenRouter, DeepSeek, Gemini, GigaChat, YandexGPT)
моделям. Провайдер и модель выбираются в конфиге ~/.ecodoc/config.json;
команда `ecodoc ai setup` находит всё установленное локально сама.
"""
from ecodoc.ai.config import AIConfig, load_config, save_config  # noqa: F401
from ecodoc.ai.providers import get_provider, PROVIDERS  # noqa: F401
