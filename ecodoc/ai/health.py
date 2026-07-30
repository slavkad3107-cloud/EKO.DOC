"""Проверка моделей ИИ на работоспособность и выбор лучшей на текущий момент.

Требование ТЗ: «при запуске приложения надо чтобы все модели проверялись на
работу/лимит и выбирался лучший для использования на текущий момент по
ранжированию: сначала большие бесплатные, потом локальные и уже потом дипсик
(только он платный)».

Проверка — короткий запрос к каждой модели, у которой есть ключ (для локальных
— доступность сервера). Результат кэшируется: гонять полную проверку на каждый
запуск дорого и упирается в лимиты, поэтому кэш живёт `_TTL` и обновляется в
фоне либо по кнопке «Проверить модели».
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ecodoc.ai import registry
from ecodoc.ai.config import AIConfig, config_dir, has_key, load_config, save_config
from ecodoc.ai.registry import FREE, LOCAL, PAID, ModelSpec

_TTL = 6 * 3600          # сколько секунд доверять кэшу проверки
_PING_TIMEOUT = 45       # на одну модель
_SYSTEM = "Отвечай одним словом, без пояснений."
_USER = "Ответь словом: работает"


def health_path() -> Path:
    return config_dir() / "ai_health.json"


@dataclass
class Health:
    """Состояние одной модели по последней проверке."""
    provider: str
    model: str
    tier: str
    ok: bool = False
    sec: float = 0.0
    error: str = ""
    code: int = 0            # HTTP-код ошибки, если был
    reason: str = ""         # «нет ключа» | «лимит» | «нет средств» | …
    checked: float = 0.0     # epoch

    @property
    def id(self) -> str:
        return f"{self.provider}/{self.model}" if self.model else self.provider


def _reason(err: str) -> tuple[int, str]:
    """HTTP-код и человекочитаемая причина из текста ошибки провайдера."""
    import re
    m = re.search(r"HTTP (\d{3})", err)
    code = int(m.group(1)) if m else 0
    low = err.lower()
    # региональные блокировки проверяем ДО кодов: у Google это 400, у Groq и
    # Cerebras — 403 с телом «error code: 1010» (заглушка Cloudflare), и то и
    # другое легко спутать с «неверным ключом»
    if "location is not supported" in low or "unsupported_country" in low:
        return code, "регион не поддерживается (нужен VPN)"
    if code == 403 and "1010" in err:
        return code, "заблокировано по региону (нужен VPN)"
    if code == 429 or "rate limit" in low or "quota" in low:
        return code, "лимит или квота исчерпана"
    if code in (401, 403):
        return code, "ключ не действует"
    if code == 400 and ("credit" in low or "balance" in low):
        return code, "недостаточно средств"
    if code == 404:
        return code, "модель недоступна"
    if code == 400:
        return code, "запрос отклонён (ключ или модель)"
    if any(w in low for w in ("недоступ", "connection", "refused", "getaddrinfo")):
        return code, "сервер недоступен"
    if "timed out" in low or "timeout" in low:
        return code, "не ответил вовремя"
    if "не задан" in low or "ключ" in low:
        return code, "нет ключа"
    return code, err[:60]


def _ollama_models() -> list[str]:
    from ecodoc.ai.detect import _ollama_models as det
    return det()


def check_one(spec: ModelSpec) -> Health:
    """Один короткий запрос к модели. Никогда не бросает исключение."""
    from ecodoc.ai.providers import AIError, get_provider

    h = Health(provider=spec.provider, model=spec.model, tier=spec.tier,
               checked=time.time())
    model = spec.model
    if spec.tier == LOCAL:
        installed = _ollama_models() if spec.provider == "ollama" else []
        if spec.provider == "ollama":
            if not installed:
                h.reason = "сервер недоступен"
                h.error = "Ollama не запущена"
                return h
            model = model or next(
                (m for m in installed
                 if not any(k in m.lower() for k in ("bge", "embed", "nomic"))),
                installed[0])
    elif not has_key(spec.provider):
        h.reason = "нет ключа"
        h.error = "ключ не задан"
        return h

    h.model = model
    cfg = AIConfig(provider=spec.provider, model=model)
    t0 = time.time()
    try:
        get_provider(cfg).chat(_SYSTEM, _USER)
        h.ok = True
        h.sec = round(time.time() - t0, 1)
        h.reason = "работает"
    except Exception as e:                      # AIError и неожиданные формы ответа
        h.sec = round(time.time() - t0, 1)
        h.error = str(e)[:300]
        h.code, h.reason = _reason(h.error)
    return h


def check_all(specs: list[ModelSpec] | None = None,
              workers: int = 8) -> list[Health]:
    """Проверить все модели параллельно и сохранить результат в кэш."""
    specs = specs if specs is not None else registry.ALL
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(check_one, specs))
    save_cache(results)
    return results


def save_cache(results: list[Health]) -> Path:
    p = health_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"checked": time.time(),
                               "items": [asdict(h) for h in results]},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return p


def load_cache() -> tuple[float, list[Health]]:
    """(время проверки, состояния). (0, []) — кэша нет или он битый."""
    p = health_path()
    if not p.exists():
        return 0.0, []
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        known = set(Health.__dataclass_fields__)
        items = [Health(**{k: v for k, v in it.items() if k in known})
                 for it in data.get("items", [])]
        return float(data.get("checked") or 0), items
    except (OSError, json.JSONDecodeError, TypeError):
        return 0.0, []


def fresh(ttl: int = _TTL) -> list[Health]:
    """Состояния из кэша, если он ещё свеж; иначе пустой список."""
    checked, items = load_cache()
    return items if items and time.time() - checked < ttl else []


def ranked_working(results: list[Health]) -> list[Health]:
    """Рабочие модели в порядке ТЗ: бесплатные → локальные → платный DeepSeek.

    Внутри тарифа — по замеру качества/скорости из реестра, но модель, которая
    только что ответила быстрее, поднимается выше при равных данных реестра."""
    order = {s.id: i for i, s in enumerate(registry.ranked())}
    ok = [h for h in results if h.ok]
    return sorted(ok, key=lambda h: (order.get(h.id, order.get(h.provider, 999)),
                                     h.sec or 999))


def pick_best(results: list[Health] | None = None,
              max_fallbacks: int = 6) -> tuple[AIConfig, list[Health]]:
    """Собрать конфиг: лучшая рабочая модель + цепочка запасных по ранжированию."""
    results = results if results is not None else (fresh() or check_all())
    working = ranked_working(results)
    cfg = load_config()
    if not working:
        return cfg, results
    best, *rest = working
    cfg.provider, cfg.model = best.provider, best.model
    seen = {(best.provider, best.model)}
    fbs = []
    for h in rest:
        if (h.provider, h.model) in seen:
            continue
        seen.add((h.provider, h.model))
        fbs.append({"provider": h.provider, "model": h.model})
        if len(fbs) >= max_fallbacks:
            break
    cfg.fallbacks = fbs
    det = cfg.detected if isinstance(cfg.detected, dict) else {}
    det["free_migrated"] = True          # автовыбор сильнее старой миграции
    det["picked_by"] = "health"
    cfg.detected = det
    return cfg, results


def apply_best(results: list[Health] | None = None) -> AIConfig:
    """Выбрать лучшую модель и сохранить конфиг."""
    cfg, _ = pick_best(results)
    if cfg.provider:
        save_config(cfg)
    return cfg


def summary(results: list[Health]) -> str:
    """Текстовая сводка для CLI и вкладки «Сервис»."""
    lines = ["── Состояние моделей ИИ ──"]
    for h in sorted(results, key=lambda x: (not x.ok, x.tier, x.sec or 999)):
        mark = "✅" if h.ok else "✖"
        tier = registry.tier_label(h.tier)
        sec = f"{h.sec:>5.1f} с" if h.sec else "     —"
        lines.append(f"  {mark} {h.id:44} {tier:9} {sec}  {h.reason}")
    working = ranked_working(results)
    if working:
        lines.append(f"\nВыбрана: {working[0].id} "
                     f"({registry.tier_label(working[0].tier)})")
        if len(working) > 1:
            lines.append("Запасные: " + ", ".join(h.id for h in working[1:6]))
    else:
        lines.append("\n⚠ Ни одна модель не ответила — проверьте ключи и интернет "
                     "(Сервис → Выбор ИИ) или установите Ollama.")
    return "\n".join(lines)
