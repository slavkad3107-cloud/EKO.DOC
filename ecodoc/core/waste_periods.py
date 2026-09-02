"""Разбивка отходов по периодам (год → квартал → месяц) в тоннах И м³.

Для вкладки ОТХОДЫ: таблица как в бланке пользователя «форма таблички по
отходам» — строки-отходы по классам опасности, столбцы-периоды, в ячейке
т и м³. Периоды берутся из справок-актов (waste_agg.act_period: дата или
текст «3 кв 2025»); объём — из акта, иначе из плотности; ничего не
выдумывается — без плотности м³ остаётся пустым.
"""
from __future__ import annotations

from decimal import Decimal

from ecodoc.core import fkko
from ecodoc.core.waste_agg import act_period, norm_fkko


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def build(ctx) -> dict:
    """Структура для GUI: rows × periods, итоги по годам, «без периода»."""
    rows: dict[str, dict] = {}
    years: set[int] = set()
    no_period = {"t": 0.0, "m3": 0.0, "count": 0}
    for a in ctx.waste_acts:
        code = norm_fkko(a.fkko_code)
        key = code or (a.name or "").strip().lower()
        if not key:
            continue
        r = rows.setdefault(key, {
            "fkko": code, "fkko_fmt": fkko.fmt(code) if code else "",
            "name": "", "hazard": int(a.hazard_class or 0) or (int(code[-1]) if code else 0),
            "periods": {}, "t_total": 0.0, "m3_total": 0.0})
        if len(a.name or "") > len(r["name"]):
            r["name"] = (a.name or "").strip()
        t = _f(a.mass)
        m3 = _f(a.volume_m3)
        if not m3 and a.density and t:
            m3 = t / _f(a.density)
        y, q, mo = act_period(a)
        r["t_total"] += t
        r["m3_total"] += m3
        if not y:
            no_period["t"] += t
            no_period["m3"] += m3
            no_period["count"] += 1
            continue
        years.add(y)
        py = r["periods"].setdefault(str(y), {"t": 0.0, "m3": 0.0, "q": {}, "m": {}})
        py["t"] += t
        py["m3"] += m3
        if q:
            cq = py["q"].setdefault(str(q), {"t": 0.0, "m3": 0.0})
            cq["t"] += t
            cq["m3"] += m3
        if mo:
            cm = py["m"].setdefault(str(mo), {"t": 0.0, "m3": 0.0})
            cm["t"] += t
            cm["m3"] += m3
    out_rows = sorted(rows.values(), key=lambda r: (r["hazard"] or 9, r["fkko"], r["name"]))
    totals = {}
    for r in out_rows:
        for y, p in r["periods"].items():
            ty = totals.setdefault(y, {"t": 0.0, "m3": 0.0})
            ty["t"] += p["t"]
            ty["m3"] += p["m3"]
    # округление — только в выдаче (Decimal-хвосты вида 469.022089211970074 не нужны)
    def rnd(d: dict):
        for k, v in list(d.items()):
            if isinstance(v, float):
                d[k] = round(v, 4)
            elif isinstance(v, dict):
                rnd(v)
    for r in out_rows:
        rnd(r)
    rnd(totals)
    rnd(no_period)
    return {"years": sorted(years), "rows": out_rows,
            "no_period": no_period, "totals": totals}
