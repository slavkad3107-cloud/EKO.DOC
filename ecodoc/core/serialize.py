"""Сериализация ReportContext в JSON и обратно.

JSON — это «форма для ручной доводки»: после парсинга документов контекст
выгружается в .json, эколог правит его в любом редакторе, затем по нему
генерируются XML и печатная форма.
"""
from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path

from ecodoc.core.models import (Medium, NVOSObject, Organization, Pollutant,
                                ReportContext, ReportPeriod, WasteFlow)


def _enc(obj):
    if is_dataclass(obj):
        return {f.name: _enc(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, list):
        return [_enc(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _enc(v) for k, v in obj.items()}
    return obj


def to_json(ctx: ReportContext, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_enc(ctx), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _build(cls, data: dict):
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        kwargs[f.name] = data[f.name]
    return cls(**kwargs)


def _to_int(v):
    """Число из строки/None (формы шлют строки). Мусор -> 0."""
    if v in (None, ""):
        return 0
    try:
        return int(float(str(v).replace(",", ".")))
    except (ValueError, TypeError):
        return 0


def from_json(path: str | Path) -> ReportContext:
    # utf-8-sig: терпим BOM от Блокнота и прочих Windows-редакторов
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    ctx = ReportContext()
    ctx.organization = _build(Organization, data.get("organization", {}))
    ctx.period = _build(ReportPeriod, data.get("period", {}))
    # год/квартал из формы приходят строками — приводим к int
    ctx.period.year = _to_int(ctx.period.year)
    ctx.period.quarter = _to_int(ctx.period.quarter) or None
    ctx.objects = [_build(NVOSObject, o) for o in data.get("objects", [])]
    ctx.extra = data.get("extra", {})
    ctx.provenance = data.get("provenance", {})

    for pd in data.get("pollutants", []):
        p = _build(Pollutant, pd)
        p.medium = Medium(pd.get("medium", "air"))
        for a in ("mass_norm", "mass_limit", "mass_over"):
            setattr(p, a, Decimal(str(pd.get(a, 0) or 0)))
        p.k_ot = Decimal(str(pd["k_ot"])) if pd.get("k_ot") not in (None, "") else None
        ctx.pollutants.append(p)

    dec_fields = ("accumulated_start", "generated", "received", "used",
                  "neutralized", "transferred", "placed_norm", "placed_over",
                  "accumulated_end")
    for wd in data.get("wastes", []):
        w = _build(WasteFlow, wd)
        for a in dec_fields:
            setattr(w, a, Decimal(str(wd.get(a, 0) or 0)))
        w.hazard_class = _to_int(w.hazard_class) or 5   # из формы приходит строкой
        ctx.wastes.append(w)
    return ctx
