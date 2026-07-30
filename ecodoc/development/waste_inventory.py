"""Инвентаризация отходов: перечень отходов, образующихся на объекте.

Первый документ контура «Разработка» по новой схеме: из него потом растут
ПНООЛР, журнал 1028, 2-ТП и кадастр — поэтому он идёт первым.

Данные берём из того, что уже собрано программой:
  * справки-акты (`ctx.waste_acts`) — что реально образуется и куда сдаётся;
  * движение (`ctx.wastes`) — массы за отчётный период;
  * паспорта (`ctx.extra['waste_passports']`) — класс опасности и состав;
  * лабораторные протоколы (`ctx.extra['lab_results']`) — чем подтверждён класс.

Выход — .xlsx: титул, перечень отходов, места накопления, подтверждающие
документы. Отсутствующее не выдумываем, а помечаем как «нет данных» —
эколог видит, что дозаполнить.
"""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import ReportContext
from ecodoc.render import xlsx

TITLE = "Инвентаризация отходов"


def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return None
    return float(d) if d else None


def collect(ctx: ReportContext) -> list[dict]:
    """Свести перечень отходов объекта из всех источников."""
    from ecodoc.core.waste_agg import norm_fkko

    rows: "OrderedDict[str, dict]" = OrderedDict()
    passports = {norm_fkko(p.get("fkko", "")): p
                 for p in (ctx.extra or {}).get("waste_passports", [])
                 if isinstance(p, dict)}

    def slot(code: str, name: str) -> dict:
        key = code or (name or "").lower()
        return rows.setdefault(key, {
            "fkko": code, "name": name, "hazard": 0, "generated": 0.0,
            "transferred": 0.0, "operations": [], "receivers": [],
            "composition": "", "passport": False, "protocols": []})

    for w in ctx.wastes:
        code = norm_fkko(w.fkko_code)
        r = slot(code, w.name or "")
        r["name"] = r["name"] or w.name or ""
        r["hazard"] = r["hazard"] or int(w.hazard_class or 0)
        r["generated"] += _num(w.generated) or 0.0
        r["transferred"] += _num(w.transferred) or 0.0

    for a in ctx.waste_acts:
        code = norm_fkko(a.fkko_code)
        r = slot(code, a.name or "")
        r["name"] = r["name"] or a.name or ""
        r["hazard"] = r["hazard"] or int(a.hazard_class or 0)
        if a.operation and a.operation not in r["operations"]:
            r["operations"].append(a.operation)
        if a.receiver and a.receiver not in r["receivers"]:
            r["receivers"].append(a.receiver)

    for code, p in passports.items():
        r = slot(code, p.get("name", ""))
        r["passport"] = True
        r["hazard"] = r["hazard"] or int(p.get("hazard_class") or 0)
        comps = [c for c in (p.get("components") or []) if isinstance(c, dict)]
        if comps and not r["composition"]:
            r["composition"] = "; ".join(
                f"{c.get('name', '')}{(' ' + str(c['percent']) + '%') if c.get('percent') else ''}"
                for c in comps)

    for lab in (ctx.extra or {}).get("lab_results", []):
        if not isinstance(lab, dict):
            continue
        target = str(lab.get("object") or "").lower()
        kind = str(lab.get("kind") or "")
        for r in rows.values():
            if not target or target in (r["name"] or "").lower() or r["fkko"] in target:
                if kind and kind not in r["protocols"]:
                    r["protocols"].append(kind)

    # класс опасности из последней цифры кода, если иначе неизвестен
    for r in rows.values():
        if not r["hazard"] and len(r["fkko"]) == 11 and r["fkko"][-1].isdigit():
            r["hazard"] = int(r["fkko"][-1])
    return list(rows.values())


def gaps(ctx: ReportContext, rows: list[dict] | None = None) -> list[str]:
    """Чего не хватает для полноценной инвентаризации."""
    rows = rows if rows is not None else collect(ctx)
    out = []
    if not rows:
        out.append("перечень пуст: загрузите справки-акты или заполните отходы вручную")
    for r in rows:
        label = r["name"] or r["fkko"] or "отход"
        if not r["fkko"]:
            out.append(f"{label}: не указан код ФККО")
        if not r["hazard"]:
            out.append(f"{label}: не определён класс опасности")
        if not r["passport"] and r["hazard"] in (1, 2, 3, 4):
            out.append(f"{label}: нет паспорта отхода (нужен для I–IV класса)")
        if not r["composition"]:
            out.append(f"{label}: не указан состав (из паспорта или протокола КХА)")
    # правила протоколов — та же логика, что при загрузке
    from ecodoc.intake.crosscheck import lab_gaps
    out += lab_gaps(ctx)
    return out


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    """Собрать документ инвентаризации отходов (.xlsx)."""
    rows = collect(ctx)
    org = ctx.organization
    wb = xlsx.new_workbook()

    ws = wb.create_sheet("Титул")
    xlsx.merge(ws, "A1:F1", TITLE.upper(), bold=True, align="center")
    xlsx.merge(ws, "A2:F2", f"по объекту НВОС за {ctx.period.year or '____'} год",
               align="center")
    info = [("Организация", org.name or org.short_name), ("ИНН", org.inn),
            ("ОГРН", org.ogrn), ("Адрес", org.address),
            ("Объект НВОС", ", ".join(o.code for o in ctx.objects) or "—"),
            ("Адрес объекта", "; ".join(o.address for o in ctx.objects if o.address) or "—"),
            ("Ответственный", org.director_name or "—")]
    for i, (label, value) in enumerate(info, start=4):
        xlsx.cell(ws, f"A{i}", label, bold=True)
        xlsx.merge(ws, f"B{i}:F{i}", value or "—", align="left")
    xlsx.widths(ws, {"A": 28, "B": 24, "C": 18, "D": 18, "E": 18, "F": 18})

    ws2 = wb.create_sheet("Перечень отходов")
    head = ["№", "Наименование отхода", "Код ФККО", "Класс опасности",
            "Образовано за период, т", "Передано, т", "Вид обращения",
            "Приёмщики / полигоны", "Состав (из паспорта/КХА)",
            "Паспорт", "Протоколы"]
    xlsx.header_row(ws2, 1, head)
    xlsx.widths(ws2, {"A": 5, "B": 42, "C": 16, "D": 8, "E": 12, "F": 12,
                      "G": 18, "H": 26, "I": 34, "J": 9, "K": 16})
    for i, r in enumerate(rows, start=1):
        xlsx.data_row(ws2, i + 1, [
            i, r["name"] or "—", r["fkko"] or "—", r["hazard"] or "—",
            r["generated"] or None, r["transferred"] or None,
            ", ".join(r["operations"]) or "—",
            ", ".join(r["receivers"]) or "—",
            r["composition"] or "нет данных",
            "есть" if r["passport"] else "нет",
            ", ".join(r["protocols"]) or "нет"])

    ws3 = wb.create_sheet("Чего не хватает")
    xlsx.header_row(ws3, 1, ["Замечание"])
    xlsx.widths(ws3, {"A": 110})
    problems = gaps(ctx, rows) or ["замечаний нет — перечень заполнен"]
    for i, text in enumerate(problems, start=2):
        xlsx.data_row(ws3, i, [text])

    return xlsx.save(wb, Path(out_path))
