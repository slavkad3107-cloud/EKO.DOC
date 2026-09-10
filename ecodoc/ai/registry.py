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


def is_ollama_cloud(model: str) -> bool:
    """Облачная модель ollama.com (ярлык `…-cloud` или `…:cloud`): считается на
    сервере, данные уходят в облако — выдавать её за локальную нельзя."""
    m = (model or "").lower()
    return m.endswith("-cloud") or m.endswith(":cloud")


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
_OLLAMA_CLOUD_LIMIT = "1 запрос одновременно, объём сбрасывается раз в неделю"
_OLLAMA_CLOUD_NOTE = ("облако ollama.com: данные уходят на сервер (обещают не "
                      "логировать и не обучаться); нужна Ollama, вошедшая в "
                      "аккаунт ollama.com")

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
    # Ollama Cloud: облачные модели ollama.com через установленную Ollama
    # (вход в аккаунт — `ollama signin`). Бесплатный тариф пользователя на
    # 10.09.2026: gemma4:31b, gpt-oss:120b/20b, nemotron-3-nano/super/ultra.
    # Мини-замер 10.09 (3 поля из справки): все 3/3; gpt-oss:120b 1,0 с,
    # gemma4 0,7 с, nano 1,9 с, super 11 с, gpt-oss:20b 4,7 с, ultra 62 с.
    # В автопроверку не включены ultra (медленная, дорогая для недельного
    # объёма) и gpt-oss:20b (слабее 120b при той же скорости) — они есть в
    # списке ручного выбора.
    ModelSpec("ollama_cloud", "gpt-oss:120b-cloud", FREE,
              "Ollama Cloud GPT-OSS 120B — бесплатный недельный объём",
              limit=_OLLAMA_CLOUD_LIMIT, note=_OLLAMA_CLOUD_NOTE),
    ModelSpec("ollama_cloud", "gemma4:31b-cloud", FREE,
              "Ollama Cloud Gemma 4 31B — бесплатно, самая быстрая",
              limit=_OLLAMA_CLOUD_LIMIT, note=_OLLAMA_CLOUD_NOTE),
    # Groq: живые модели на 10.09.2026 — gpt-oss-120b/20b, qwen3.6/3.8-27b
    # (последние на бесплатном тарифе упираются в лимит токенов); Llama 3.3
    # у Groq больше нет. Лимиты — из заголовков ответа Groq.
    ModelSpec("groq", "openai/gpt-oss-120b", FREE,
              "Groq GPT-OSS 120B — бесплатный лимит, очень быстро",
              limit="1000 запросов/сутки, 8000 токенов/мин",
              note="8000 токенов/мин — примерно один кусок документа (14 тыс. "
                   "символов) в минуту; работает только через VPN (из РФ — 403)"),
    ModelSpec("ollama_cloud", "nemotron-3-super:cloud", FREE,
              "Ollama Cloud Nemotron 3 Super — бесплатный недельный объём",
              limit=_OLLAMA_CLOUD_LIMIT, note=_OLLAMA_CLOUD_NOTE),
    ModelSpec("ollama_cloud", "nemotron-3-nano:30b-cloud", FREE,
              "Ollama Cloud Nemotron 3 Nano 30B — бесплатный недельный объём",
              limit=_OLLAMA_CLOUD_LIMIT, note=_OLLAMA_CLOUD_NOTE),
    ModelSpec("zai", "glm-4.7-flash", FREE,
              "Z.ai GLM-4.7-Flash — бесплатная модель",
              limit="1 запрос одновременно",
              note="из РФ без VPN; «размышления» выключены — 2,7 с вместо 11 с "
                   "при том же качестве (замер 10.09.2026); бесплатный тариф "
                   "часто отвечает «перегружен» (429); условия коммерческого "
                   "использования явно не прописаны"),
    # Cloudflare Workers AI: 10 000 «нейронов» в сутки бесплатно — примерно
    # 60 запросов к gpt-oss-120b среднего размера; сверх лимита — отказ, не
    # списание. 10.09.2026: токен пользователя с правами Workers AI работает
    # (ответ 3,9 с), в аккаунте 31 текстовая модель.
    ModelSpec("cloudflare", "@cf/openai/gpt-oss-120b", FREE,
              "Cloudflare Workers AI GPT-OSS 120B — бесплатный суточный объём",
              limit="10 000 нейронов/сутки ≈ 60 запросов",
              note="нужны токен с правами Workers AI и ID аккаунта"),
    ModelSpec("cerebras", "gpt-oss-120b", FREE,
              "Cerebras GPT-OSS 120B",
              note="10.09.2026: HTTP 402 «Payment required» — бесплатный "
                   "доступ закрыт, нужна оплата в кабинете Cerebras"),
    # список пользователя (08.09.2026): бесплатные Nemotron и Gemma 4 (vision)
    ModelSpec("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free", FREE,
              "OpenRouter Nemotron 3 Ultra 550B — бесплатная",
              limit="20 запросов/мин, 50–1000/сутки"),
    ModelSpec("openrouter", "nvidia/nemotron-3-super-120b-a12b:free", FREE,
              "OpenRouter Nemotron 3 Super 120B — бесплатная",
              limit="20 запросов/мин, 50–1000/сутки"),
    ModelSpec("openrouter", "nvidia/nemotron-3.5-lightning:free", FREE,
              "OpenRouter Nemotron 3.5 Lightning — бесплатная, быстрая",
              limit="20 запросов/мин, 50–1000/сутки"),
    ModelSpec("openrouter", "google/gemma-4-31b-it:free", FREE,
              "OpenRouter Gemma 4 31B — бесплатная, умеет картинки (паспорта-сканы)",
              limit="20 запросов/мин, 50–1000/сутки"),
    ModelSpec("mistral", "mistral-large-latest", FREE,
              "Mistral Large", sec=25.1, score="19/19",
              note="10.09.2026: на бесплатном тарифе недоступна "
                   "(403 tier_not_allowed)"),
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


def all_specs() -> list[ModelSpec]:
    """Вшитый реестр + бесплатные модели OpenRouter из живого списка (без
    дублей по id)."""
    seen = {s.id for s in ALL}
    out = list(ALL)
    try:
        from ecodoc.ai.detect import dynamic_openrouter_specs
        for s in dynamic_openrouter_specs():
            if s.id not in seen:
                out.append(s)
                seen.add(s.id)
    except Exception:
        pass
    return out

