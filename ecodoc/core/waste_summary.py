"""Сводная таблица по отходам из справок-актов — «как Справки-2025 у ЛСС».

Форма эталона (D:\\S\\..._ЛСС\\2025\\Справки-2025.xls, лист на площадку):
строки — отходы (Наименование | Код ФККО | Класс | плотность), колонки —
периоды парами «т | м3», хвост — Вид обращения | Перевозчик | Приёмщик.
Здесь периоды — месяцы, кварталы и итог за год (у ЛСС были годы).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import ReportContext
from ecodoc.core.waste_agg import act_year_month, norm_fkko

_MONTHS = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
           "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]


def _fmt_fkko(digits: str) -> str:
    """11 цифр → «4 71 101 01 52 1» (группировка как в каталоге ФККО)."""
    d = norm_fkko(digits)
    if len(d) != 11:
        return digits
    return f"{d[0]} {d[1:3]} {d[3:6]} {d[6:8]} {d[8:10]} {d[10]}"


def build_rows(ctx: ReportContext, year=None) -> list[dict]:
    """Свернуть акты в строки сводной: по отходу — массы/объёмы по месяцам.

    year — фильтр по году из дат актов (акты без даты включаются всегда,
    их массы попадают в колонку «без даты» и в итог за год)."""
    year = int(year) if year else None
    rows: dict[str, dict] = {}
    for a in ctx.waste_acts:
        fkko = norm_fkko(a.fkko_code)
        key = fkko or (a.name or "").strip().lower()
        if not key:
            continue
        yr, mon = act_year_month(a)
        if year and yr is not None and yr != year:
            continue
        r = rows.setdefault(key, {
            "name": "", "fkko": fkko, "hazard_class": 0,
            "density": Decimal("0"),
            "mass_m": {}, "vol_m": {},          # месяц -> Decimal
            "mass_nodate": Decimal("0"), "vol_nodate": Decimal("0"),
            "operations": [], "carriers": [], "receivers": [],
        })
        if len(a.name or "") > len(r["name"]):
            r["name"] = a.name.strip()
        r["hazard_class"] = r["hazard_class"] or a.hazard_class
        mass = a.mass or Decimal("0")
        vol = a.volume_m3 or Decimal("0")
        if not vol and a.density:
            vol = mass / a.density
        if a.density and not r["density"]:
            r["density"] = a.density
        elif mass and vol and not r["density"]:
            r["density"] = mass / vol
        if mon:
            r["mass_m"][mon] = r["mass_m"].get(mon, Decimal("0")) + mass
            r["vol_m"][mon] = r["vol_m"].get(mon, Decimal("0")) + vol
        else:
            r["mass_nodate"] += mass
            r["vol_nodate"] += vol
        for fld, val in (("operations", a.operation), ("carriers", a.carrier),
                         ("receivers", a.receiver)):
            v = (val or "").strip()
            if v and v not in r[fld]:
                r[fld].append(v)
    out = sorted(rows.values(), key=lambda r: (r["hazard_class"] or 9,
                                               r["fkko"], r["name"]))
    for r in out:
        r["mass_q"] = {q: sum((r["mass_m"].get(m, Decimal("0"))
                               for m in range(q * 3 - 2, q * 3 + 1)),
                              Decimal("0")) for q in (1, 2, 3, 4)}
        r["vol_q"] = {q: sum((r["vol_m"].get(m, Decimal("0"))
                              for m in range(q * 3 - 2, q * 3 + 1)),
                             Decimal("0")) for q in (1, 2, 3, 4)}
        r["mass_y"] = sum(r["mass_m"].values(), Decimal("0")) + r["mass_nodate"]
        r["vol_y"] = sum(r["vol_m"].values(), Decimal("0")) + r["vol_nodate"]
    return out


def _num(v: Decimal):
    """Decimal → float для ячейки; ноль оставляем пустым (как в эталоне)."""
    return float(v) if v else None


def build_xlsx(ctx: ReportContext, out_path: str | Path, year=None) -> Path:
    """Сводная xlsx: листы «По месяцам», «По кварталам», «За год»."""
    from ecodoc.render import xlsx
    year = int(year) if year else (int(ctx.period.year)
                                   if getattr(ctx.period, "year", 0) else None)
    rows = build_rows(ctx, year)
    wb = xlsx.new_workbook()
    org = ctx.organization
    title = f"{org.short_name or org.name} — сводная по отходам из справок-актов" \
            + (f" за {year} г." if year else "")
    base = ["Наименование отхода", "Код отхода (по ФККО)", "Класс опасности",
            "Плотность, т/м³"]
    tail = ["Вид обращения", "Перевозчик", "Приёмщик/полигон"]
    has_nodate = any(r["mass_nodate"] or r["vol_nodate"] for r in rows)

    def _sheet(name: str, periods: list, mkey: str, vkey: str):
        ws = wb.create_sheet(name)
        xlsx.merge(ws, "A1:F1", title, bold=True, align="left")
        head = base[:]
        for p_label in periods:
            head += [f"{p_label}, т", f"{p_label}, м³"]
        if has_nodate:
            head += ["без даты, т", "без даты, м³"]
        head += ["ИТОГО, т", "ИТОГО, м³"] + tail
        xlsx.header_row(ws, 3, head)
        ws.column_dimensions["A"].width = 42
        ws.column_dimensions["B"].width = 18
        for r_i, r in enumerate(rows, start=4):
            vals = [r["name"], _fmt_fkko(r["fkko"]),
                    r["hazard_class"] or "", _num(r["density"])]
            for p_i in range(len(periods)):
                vals += [_num(r[mkey].get(p_i + 1, Decimal("0"))),
                         _num(r[vkey].get(p_i + 1, Decimal("0")))]
            if has_nodate:
                vals += [_num(r["mass_nodate"]), _num(r["vol_nodate"])]
            vals += [_num(r["mass_y"]), _num(r["vol_y"]),
                     ", ".join(r["operations"]), ", ".join(r["carriers"]),
                     ", ".join(r["receivers"])]
            xlsx.data_row(ws, r_i, vals)

    _sheet("По месяцам", _MONTHS, "mass_m", "vol_m")
    _sheet("По кварталам", ["1 кв", "2 кв", "3 кв", "4 кв"], "mass_q", "vol_q")
    _sheet("За год", [], "mass_m", "vol_m")
    return xlsx.save(wb, Path(out_path))
