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
from ecodoc.ai.registry import is_ollama_cloud

# порядок предпочтения локальных моделей для извлечения структурированных
# данных из русскоязычных документов (по убыванию качества на этой задаче)
_CHAT_PREFERENCE = ("qwen3", "qwen2.5", "llama3.3", "gemma3", "llama3.2",
                    "mistral", "deepseek-r1", "phi4", "llama3", "gemma2")
_EMBED_MARKERS = ("bge", "embed", "nomic", "mxbai", "e5")

# человекочитаемые метки провайдеров (для выпадающего списка в GUI)
PROVIDER_LABEL = {
    "mistral": "Mistral (облако, БЕСПЛАТНЫЙ тариф — лучший по замеру)",
    "cohere": "Cohere (облако, бесплатный ключ)",
    "cerebras": "Cerebras (облако; бесплатный доступ закрыт — нужна оплата)",
    "moonshot": "Moonshot / Kimi (облако)",
    "deepseek": "DeepSeek (облако, быстро)",
    "openrouter": "OpenRouter (облако, много моделей)",
    "groq": "Groq (облако, бесплатно, очень быстро; только через VPN)",
    "zai": "Z.ai GLM (облако, бесплатно; нужен ключ z.ai)",
    "cloudflare": "Cloudflare Workers AI (облако, бесплатно ~60 запросов/сутки; токен + ID аккаунта)",
    "gemini": "Google Gemini (облако, бесплатный лимит)",
    "openai": "OpenAI / GPT (облако)",
    "anthropic": "Anthropic / Claude (облако)",
    "together": "Together (облако)",
    "xai": "xAI / Grok (облако)",
    "vsegpt": "VseGPT (облако, РФ-агрегатор)",
    "proxyapi": "ProxyAPI (облако, РФ-прокси)",
    "gigachat": "GigaChat (Сбер, облако)",
    "yandexgpt": "YandexGPT (облако)",
    "ollama_cloud": "Ollama Cloud (облако ollama.com, бесплатный объём; ключ не нужен)",
    "ollama": "Ollama (локально, приватно)",
    "lmstudio": "LM Studio (локально)",
}

# пресеты моделей на провайдера (пользователь выбирает из списка или вводит
# своё). Для ollama/lmstudio список подтягивается из установленных моделей.
KNOWN_MODELS = {
    "cohere": ["command-a-03-2025", "command-r7b-12-2024", "command-r-08-2024",
               "command-a-plus-05-2026", "command-r-plus-08-2024"],
    "moonshot": ["kimi-k2-0905-preview", "moonshot-v1-32k"],
    "cerebras": ["gpt-oss-120b", "qwen-3.8-27b", "gemma-4-31b"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    # список пользователя (08.09.2026): бесплатные Nemotron впереди, Gemma 4
    # умеет картинки — для паспортов-сканов
    "openrouter": ["nvidia/nemotron-3-ultra-550b-a55b:free",
                   "nvidia/nemotron-3-super-120b-a12b:free",
                   "nvidia/nemotron-3.5-lightning:free",
                   "google/gemma-4-31b-it:free",          # умеет картинки — для паспортов
                   "deepseek/deepseek-chat",
                   "meta-llama/llama-3.3-70b-instruct",
                   "openai/gpt-4o-mini"],
    "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b",
             "qwen/qwen3.8-27b", "qwen/qwen3.6-27b"],
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
    "zai": ["glm-4.7-flash", "glm-4.5-flash", "glm-4.6v-flash"],
    "cloudflare": ["@cf/openai/gpt-oss-120b", "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                   "@cf/moonshotai/kimi-k2.7-code", "@cf/openai/gpt-oss-20b"],
    # бесплатные облачные модели тарифа пользователя (ollama.com, 10.09.2026)
    "ollama_cloud": ["gpt-oss:120b-cloud", "gemma4:31b-cloud",
                     "nemotron-3-super:cloud", "nemotron-3-nano:30b-cloud",
                     "gpt-oss:20b-cloud", "nemotron-3-ultra:cloud"],
}

# провайдеры с БЕСПЛАТНЫМ тарифом — порядок предпочтения при автонастройке.
# Проверено на задаче извлечения из русских документов (18.07.2026):
# cohere command-a ~3 с/документ, mistral small ~1 с, openrouter :free ~6 с,
# gemini flash ~13 с. Cohere первым: бесплатный ключ без карты и без
# ограничения по дням (лимит — 20 запросов/мин, обрабатывается ретраем).
FREE_PREFERENCE = ("mistral", "gemini", "cohere", "groq", "zai", "openrouter",
                   "cloudflare", "cerebras")

# дефолтные модели для облачных провайдеров (быстрые и пригодные для
# извлечения структурных данных из русскоязычных документов)
CLOUD_DEFAULT_MODEL = {
    "cohere": "command-a-03-2025",
    "moonshot": "kimi-k2-0905-preview",
    "cerebras": "gpt-oss-120b",
    "deepseek": "deepseek-chat",
    "openrouter": "nvidia/nemotron-3-ultra-550b-a55b:free",   # бесплатная модель агрегатора
    "groq": "openai/gpt-oss-120b",
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
    "zai": "glm-4.7-flash",
    "cloudflare": "@cf/openai/gpt-oss-120b",
    "ollama_cloud": "gpt-oss:120b-cloud",
}


def _ollama_bases() -> list[str]:
    return [b.rstrip("/") for b in (os.environ.get("OLLAMA_HOST_URL", ""),
                                     "http://localhost:11434") if b]


def _ollama_tags() -> list[str]:
    """Все модели, которые знает Ollama: локальные и облачные ярлыки."""
    for base in _ollama_bases():
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=4) as r:
                data = json.loads(r.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            continue
    return []


def _ollama_models() -> list[str]:
    """ЛОКАЛЬНЫЕ модели Ollama.

    Облачные ярлыки (`…-cloud`, `…:cloud`) Ollama показывает в том же списке,
    но считаются они на ollama.com. 10.09.2026 после подключения облака первой
    в списке стояла облачная модель, и проверка «Ollama (локально, приватно)»
    ушла бы в облако — поэтому здесь только локальные."""
    return [m for m in _ollama_tags() if not is_ollama_cloud(m)]


def _ollama_cloud_models() -> list[str]:
    """Облачные модели ollama.com, уже подключённые в Ollama этого компьютера."""
    return [m for m in _ollama_tags() if is_ollama_cloud(m)]


def _ollama_running() -> bool:
    """Отвечает ли Ollama (даже если в ней нет ни одной модели)."""
    for base in _ollama_bases():
        try:
            with urllib.request.urlopen(f"{base}/api/version", timeout=4):
                return True
        except Exception:
            continue
    return False


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

    «Из коробки» пользователь ничего не выбирает: если есть свежая проверка
    моделей (`ai/health.py`) — берём лучшую рабочую по ранжированию ТЗ
    (бесплатные → локальные → платный DeepSeek); иначе быстрый локальный
    детект. Результат сохраняется, чтобы не детектить каждый раз.
    """
    from ecodoc.ai.config import load_config
    from ecodoc.ai.health import fresh, pick_best
    cfg = load_config()
    det = cfg.detected if isinstance(cfg.detected, dict) else {}
    # выбор, сделанный руками в «Сервис → Выбор ИИ», автопроверка «здоровья»
    # моделей не перебивает: раньше в углу стояла одна модель, а анализ шёл
    # другой — pick_best молча переписывал конфиг при каждом приёме
    # закреплённый вручную выбор (галочка «выбирать автоматически» снята)
    # автопроверка не перебивает; по умолчанию (08.09.2026, требование
    # пользователя) при каждом запуске выбирается оптимальная модель
    # ручной выбор («Применить и сохранить») держится до следующего запуска:
    # автовыбор — только при старте (_startup_ai_check) и по кнопке
    # «Автовыбор по результатам»; иначе панель «откатывала» выбор пользователя
    if cfg.provider and det.get("picked_by") == "user":
        return cfg
    checked = fresh()
    if checked:
        best, _ = pick_best(checked)
        if best.provider:
            from ecodoc.ai.config import save_config
            if (best.provider, best.model) != (cfg.provider, cfg.model):
                save_config(best)
            return best
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


# ── список моделей OpenRouter: проверять и обновлять автоматически ──────
# Требование пользователя (08.09.2026): список бесплатных моделей меняется,
# программа при запуске (и раз в сутки) сама спрашивает OpenRouter, какие
# модели доступны, держит бесплатные впереди, сохраняя порядок пользователя.
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_FAMILY_PREF = ("nvidia/nemotron", "google/gemma", "meta-llama", "qwen", "deepseek",
                "mistralai", "openai", "microsoft", "nousresearch")
_MAX_LIST = 14


def fetch_openrouter_models(timeout: int = 10) -> list[dict]:
    """Сырой список моделей OpenRouter (id, name, pricing, modalities)."""
    import json
    import urllib.request
    req = urllib.request.Request(OPENROUTER_MODELS_URL,
                                 headers={"User-Agent": "EcoDoc/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [m for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]


def _is_free(m: dict) -> bool:
    mid = str(m.get("id") or "")
    if mid.endswith(":free"):
        return True
    pr = m.get("pricing") or {}
    try:
        return float(pr.get("prompt") or 1) == 0 and float(pr.get("completion") or 1) == 0
    except (TypeError, ValueError):
        return False


def _has_vision(m: dict) -> bool:
    arch = m.get("architecture") or {}
    mods = arch.get("input_modalities") or []
    return "image" in [str(x).lower() for x in mods]


def _family_rank(mid: str) -> int:
    for i, fam in enumerate(_FAMILY_PREF):
        if mid.startswith(fam):
            return i
    return len(_FAMILY_PREF)


def refresh_openrouter_models(timeout: int = 10, save: bool = True) -> dict:
    """Обновить список: пользовательский порядок (KNOWN_MODELS) — впереди,
    если модель ещё есть; затем прочие бесплатные по семействам и размеру
    контекста; платные из пользовательского списка — в конце. Результат
    сохраняется в конфиг (detected['openrouter_models']) и сразу виден в
    «Сервис → Выбор ИИ» через known_models('openrouter')."""
    from datetime import datetime
    try:
        models = fetch_openrouter_models(timeout=timeout)
    except Exception as e:
        return {"error": f"OpenRouter не ответил: {str(e)[:120]}", "models": known_models("openrouter")}
    by_id = {m["id"]: m for m in models}
    user = list(KNOWN_MODELS.get("openrouter") or [])
    kept = [mid for mid in user if mid in by_id]
    gone = [mid for mid in user if mid not in by_id]
    free = [m for m in models if _is_free(m) and m["id"] not in kept]
    free.sort(key=lambda m: (_family_rank(m["id"]), -int(m.get("context_length") or 0)))
    free_ids = [m["id"] for m in free]
    ordered = ([mid for mid in kept if _is_free(by_id[mid])] + free_ids
               + [mid for mid in kept if not _is_free(by_id[mid])])
    # не раздувать выпадающий список: бесплатных до _MAX_LIST, платные пользователя — всегда
    paid_user = [mid for mid in kept if not _is_free(by_id[mid])]
    free_part = [mid for mid in ordered if mid not in paid_user][:_MAX_LIST]
    final = free_part + paid_user
    vision = [mid for mid in final if _has_vision(by_id.get(mid, {}))]
    res = {"models": final, "free": [mid for mid in final if _is_free(by_id.get(mid, {}))],
           "vision": vision, "gone": gone,
           "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "text": (f"OpenRouter: моделей {len(final)} (бесплатных "
                    f"{sum(1 for mid in final if _is_free(by_id.get(mid, {})))}"
                    + (f", исчезли: {', '.join(gone)}" if gone else "") + ")")}
    if save:
        try:
            from ecodoc.ai.config import load_config, save_config
            cfg = load_config()
            det = cfg.detected if isinstance(cfg.detected, dict) else {}
            det["openrouter_models"] = final
            det["openrouter_vision"] = vision
            det["openrouter_models_checked"] = res["checked_at"]
            cfg.detected = det
            # модель по умолчанию исчезла — берём первую бесплатную
            if cfg.provider == "openrouter" and cfg.model and cfg.model not in by_id and final:
                res["switched_from"] = cfg.model
                cfg.model = final[0]
            save_config(cfg)
        except Exception as e:
            res["save_error"] = str(e)[:120]
    return res


def known_models(provider: str) -> list[str]:
    """Список моделей провайдера: для OpenRouter — живой (из конфига после
    refresh_openrouter_models), иначе вшитый."""
    if provider == "openrouter":
        try:
            from ecodoc.ai.config import load_config
            det = load_config().detected
            live = det.get("openrouter_models") if isinstance(det, dict) else None
            if live:
                return list(live)
        except Exception:
            pass
    return list(KNOWN_MODELS.get(provider, []))


def dynamic_openrouter_specs():
    """ModelSpec для бесплатных моделей OpenRouter из живого списка — чтобы
    проверка «здоровья» гоняла и их, а не только вшитые."""
    from ecodoc.ai.registry import FREE, ModelSpec
    out = []
    for mid in known_models("openrouter"):
        if mid.endswith(":free"):
            out.append(ModelSpec("openrouter", mid, FREE, f"OpenRouter {mid} — бесплатная",
                                 limit="20 запросов/мин, 50–1000/сутки"))
    return out

