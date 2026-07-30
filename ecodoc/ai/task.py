"""Доп. задание модели вручную: «переформатируй это», «добавь то-то».

Требование ТЗ: «Добавить окно в каждом разделе для доп. задания для ИИ модели
вручную: например переформатируй так то данные или добавь то-то».

Работает так: пользователь пишет задание, программа отдаёт модели ТОЛЬКО данные
своего раздела (не весь контекст — экономнее и безопаснее), получает ответ и
показывает его. Изменения в базу вносятся отдельным подтверждением: модель
возвращает JSON того же вида, что и данные раздела, и он применяется поверх.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from decimal import Decimal

from ecodoc.core.models import Medium, ReportContext

SYSTEM = """Ты — помощник инженера-эколога РФ. Тебе дают ФРАГМЕНТ базы данных
объекта (JSON) и задание пользователя. Выполни задание и верни ответ строго в
виде одного JSON-объекта:
{
 "answer": "короткое пояснение для человека, что сделано или что ты выяснил",
 "data": <тот же JSON, что тебе дали, с внесёнными изменениями — ТОЛЬКО если
          задание требует изменить данные; иначе не включай это поле>,
 "warnings": ["сомнительные места, если есть"]
}
Правила: не выдумывай значения — если данных не хватает, скажи об этом в answer;
числа возвращай строками с точкой; структуру и названия полей не меняй;
не удаляй записи, если об этом прямо не попросили."""

# какие части контекста отдаём модели для каждого раздела
_SCOPES = {
    "org": ("organization",),
    "object": ("objects",),
    "waste": ("wastes", "waste_acts"),
    "air": ("pollutants_air",),
    "water": ("pollutants_water", "water"),
    "all": ("organization", "objects", "wastes", "waste_acts",
            "pollutants_air", "pollutants_water"),
}


def _plain(value):
    """dataclass/Decimal → простые типы для JSON."""
    if is_dataclass(value):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Medium):
        return value.value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def slice_context(ctx: ReportContext, scope: str) -> dict:
    """Данные одного раздела в простом JSON-виде."""
    parts = _SCOPES.get(scope) or _SCOPES["all"]
    out: dict = {}
    for part in parts:
        if part == "organization":
            out["organization"] = _plain(ctx.organization)
        elif part == "objects":
            out["objects"] = _plain(ctx.objects)
        elif part == "wastes":
            out["wastes"] = _plain(ctx.wastes)
        elif part == "waste_acts":
            out["waste_acts"] = _plain(ctx.waste_acts)
        elif part == "pollutants_air":
            out["pollutants_air"] = [_plain(p) for p in ctx.pollutants
                                     if p.medium == Medium.AIR]
        elif part == "pollutants_water":
            out["pollutants_water"] = [_plain(p) for p in ctx.pollutants
                                       if p.medium == Medium.WATER]
        elif part == "water":
            out["water"] = _plain((ctx.extra or {}).get("water", {}))
    out["period"] = _plain(ctx.period)
    return out


def apply_data(ctx: ReportContext, data: dict) -> list[str]:
    """Применить ответ модели к контексту. Возвращает список изменений.

    Пишем только известные разделы и только через штатный разбор
    (`serialize`), чтобы типы (Decimal, Medium, класс опасности) получились
    правильными и никакой мусор из ответа модели в базу не попал."""
    from ecodoc.core import serialize
    changes: list[str] = []
    raw = {}
    if "organization" in data:
        raw["organization"] = data["organization"]
    if "objects" in data:
        raw["objects"] = data["objects"]
    if "wastes" in data:
        raw["wastes"] = data["wastes"]
    if "waste_acts" in data:
        raw["waste_acts"] = data["waste_acts"]
    pollutants = []
    for key, medium in (("pollutants_air", "air"), ("pollutants_water", "water")):
        for p in data.get(key) or []:
            p = dict(p)
            p["medium"] = medium
            pollutants.append(p)
    if pollutants:
        raw["pollutants"] = pollutants
    if not raw:
        return changes
    raw["period"] = _plain(ctx.period)
    parsed = serialize.from_dict(raw)
    if "organization" in raw:
        ctx.organization = parsed.organization
        changes.append("реквизиты организации")
    if "objects" in raw:
        ctx.objects = parsed.objects
        changes.append(f"объекты НВОС ({len(parsed.objects)})")
    if "waste_acts" in raw:
        ctx.waste_acts = parsed.waste_acts
        changes.append(f"справки-акты ({len(parsed.waste_acts)})")
    if "wastes" in raw:
        ctx.wastes = parsed.wastes
        changes.append(f"движение отходов ({len(parsed.wastes)})")
    if pollutants:
        keep_air = "pollutants_air" not in data
        keep_water = "pollutants_water" not in data
        rest = [p for p in ctx.pollutants
                if (p.medium == Medium.AIR and keep_air)
                or (p.medium == Medium.WATER and keep_water)]
        ctx.pollutants = rest + parsed.pollutants
        changes.append(f"вещества ({len(parsed.pollutants)})")
    return changes


def run_task(ctx: ReportContext, scope: str, task: str,
             apply_changes: bool = False, org: str = "", site: str = "") -> dict:
    """Выполнить задание пользователя над данными раздела."""
    from ecodoc.ai.analyzer import _parse_json
    from ecodoc.ai.detect import ensure_configured
    from ecodoc.ai.providers import chat_with_fallback

    cfg = ensure_configured()
    if not cfg.provider:
        return {"error": "ИИ не настроен: Сервис → Выбор ИИ (или «Проверить модели»)."}
    payload = slice_context(ctx, scope)
    user = (f"Данные раздела «{scope}»:\n{json.dumps(payload, ensure_ascii=False)}"
            f"\n\nЗадание: {task}")
    text, model = chat_with_fallback(cfg, SYSTEM, user)
    try:
        out = _parse_json(text)
    except ValueError:
        return {"model": model, "answer": text[:4000], "applied": []}
    res = {"model": model, "answer": str(out.get("answer") or "")[:4000],
           "warnings": [str(w)[:300] for w in (out.get("warnings") or [])],
           "data": out.get("data"), "applied": []}
    if apply_changes and isinstance(out.get("data"), dict):
        from ecodoc.core import workspace
        changes = apply_data(ctx, out["data"])
        if changes and org and site:
            workspace.save_context(org, site, ctx)
        res["applied"] = changes
    return res
