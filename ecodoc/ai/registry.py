"""Реестр моделей ИИ: что вообще можно использовать и в каком порядке.

Единый источник правды о провайдерах и моделях. Порядок выбора задан
пользователем в ТЗ: **сначала большие бесплатные, потом локальные, и только
потом платный DeepSeek**.

Поля `sec` и `score` — результат замера на РЕАЛЬНОЙ задаче ЭКО.DOC (извлечение
данных из справки-акта: 2 акта + вещества + реквизиты + объект НВОС, 19
проверяемых полей). Замер 18–30.07.2026, ключи пользователя. Числа нужны для
сортировки внутри одного тарифа: при равном качестве быстрее — лучше.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FREE, LOCAL, PAID = "free", "local", "paid"

_TIER_ORDER = {FREE: 0, LOCAL: 1, PAID: 2}


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    tier: str                  # free | local | paid
    label: str = ""            # человекочитаемо для GUI
    limit: str = ""            # известные лимиты бесплатного тарифа
    sec: float = 0.0           # замер: секунд на документ (0 — не замерялось)
    score: str = ""            # замер: качество извлечения, «19/19»
    note: str = ""

    @property
    def id(self) -> str:
        return f"{self.provider}/{self.model}" if self.model else self.provider


# ── бесплатные облачные (первый эшелон) ──────────────────────────────────────
_FREE = [
    ModelSpec("mistral", "mistral-small-latest", FREE,
              "Mistral Small — бесплатный тариф",
              limit="1 запрос/с, ~1 млрд токенов/мес",
              sec=9.1, score="19/19", note="лучшее сочетание качества и скорости"),
    ModelSpec("gemini", "gemini-flash-latest", FREE,
              "Google Gemini Flash — бесплатный лимит",
              limit="~15 запросов/мин, 1500/сутки",
              sec=17.8, score="19/19",
              note="из РФ отвечает «User location is not supported» — только через VPN"),
    ModelSpec("cohere", "command-a-03-2025", FREE,
              "Cohere Command A — бесплатный ключ",
              limit="20 запросов/мин, 1000/мес",
              sec=26.9, score="19/19", note="лимит обрабатывается паузой и повтором"),
    ModelSpec("groq", "llama-3.3-70b-versatile", FREE,
              "Groq Llama 3.3 70B — бесплатный лимит",
              limit="~30 запросов/мин",
              note="HTTP 403 (Cloudflare 1010) — блокировка региона"),
    ModelSpec("cerebras", "llama-3.3-70b", FREE,
              "Cerebras Llama 3.3 70B — бесплатный лимит",
              limit="~30 запросов/мин, 1 млн токенов/сутки",
              note="HTTP 403 (Cloudflare 1010) — блокировка региона"),
    ModelSpec("openrouter", "openai/gpt-oss-20b:free", FREE,
              "OpenRouter GPT-OSS 20B — бесплатная модель",
              limit="20 запросов/мин, 50–1000/сутки",
              sec=91.2, score="19/19", note="работает, но очень медленно"),
    ModelSpec("mistral", "mistral-large-latest", FREE,
              "Mistral Large", sec=25.1, score="19/19",
              note="на бесплатном тарифе доступна не всегда"),
]

# ── локальные (второй эшелон: без интернета и лимитов, но медленно) ──────────
_LOCAL = [
    ModelSpec("ollama", "", LOCAL, "Ollama — локально на этом компьютере",
              limit="без лимитов", note="модель подбирается из установленных"),
    ModelSpec("lmstudio", "", LOCAL, "LM Studio — локально"),
]

# ── платные (последний эшелон) ───────────────────────────────────────────────
_PAID = [
    ModelSpec("deepseek", "deepseek-chat", PAID,
              "DeepSeek Chat — платный (дёшево)",
              sec=9.7, score="19/19", note="по ТЗ — только после бесплатных и локальных"),
    ModelSpec("openai", "gpt-4o-mini", PAID, "OpenAI GPT-4o mini — платный",
              note="ключ из ТЗ: квота исчерпана (HTTP 429)"),
    ModelSpec("anthropic", "claude-3-5-haiku-latest", PAID,
              "Anthropic Claude Haiku — платный",
              note="ключ из ТЗ: недостаточно средств (HTTP 400)"),
    ModelSpec("moonshot", "kimi-k2-0905-preview", PAID, "Moonshot Kimi — платный",
              note="ключ в ТЗ пустой"),
    ModelSpec("gigachat", "GigaChat", PAID, "GigaChat (Сбер) — платный"),
    ModelSpec("yandexgpt", "yandexgpt-lite/latest", PAID, "YandexGPT — платный"),
]

ALL: list[ModelSpec] = _FREE + _LOCAL + _PAID


def by_id(spec_id: str) -> ModelSpec | None:
    return next((s for s in ALL if s.id == spec_id), None)


def for_provider(provider: str) -> list[ModelSpec]:
    return [s for s in ALL if s.provider == provider]


def sort_key(spec: ModelSpec) -> tuple:
    """Порядок предпочтения: тариф → качество → скорость.

    Незамеренные модели идут после замеренных того же тарифа (о них меньше
    известно), но раньше следующего тарифа."""
    quality = -int(spec.score.split("/")[0]) if spec.score else 0
    speed = spec.sec if spec.sec else 10_000
    return (_TIER_ORDER.get(spec.tier, 9), quality, speed)


def ranked(specs: list[ModelSpec] | None = None) -> list[ModelSpec]:
    """Все модели в порядке предпочтения (бесплатные → локальные → платные)."""
    return sorted(specs if specs is not None else ALL, key=sort_key)


def tier_label(tier: str) -> str:
    return {FREE: "бесплатно", LOCAL: "локально", PAID: "платно"}.get(tier, tier)
