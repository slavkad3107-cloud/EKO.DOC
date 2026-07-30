"""ПНООЛР — проект нормативов образования отходов и лимитов на размещение.

Опирается на инвентаризацию отходов: перечень, классы, фактические массы.
Норматив образования по каждому отходу берём из фактических данных за
отчётный период (это и есть основание для норматива), лимит на размещение —
из фактически размещённых объёмов.

Документ большой и во многом описательный, поэтому программа собирает
**расчётную часть** (таблицы, которые считаются из данных) и обозначает
разделы, которые эколог дописывает сам. Выдумывать текст обоснований
нельзя — вместо этого в листе «Чего не хватает» перечислено, что дописать.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import ReportContext
from ecodoc.render import xlsx

TITLE = "Проект нормативов образования отходов и лимитов на их размещение"

# разделы ПНООЛР, которые заполняет эколог (программа их только обозначает)
_NARRATIVE = [
    "Общие сведения о хозяйственной деятельности",
    "Сведения о производственных процессах, где образуются отходы",
    "Схема операционного движения отходов",
    "Характеристика мест накопления отходов",
    "Мониторинг состояния окружающей среды на объектах размещения",
    "Мероприятия по снижению количества образующихся отходов",
]


def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return None
    return float(d) if d else None


def rows(ctx: ReportContext) -> list[dict]:
    """Расчётная таблица: норматив образования и лимит размещения по отходам."""
    from ecodoc.development.waste_inventory import collect
    out = []
    for r in collect(ctx):
        placed = 0.0
        for w in ctx.wastes:
            from ecodoc.core.waste_agg import norm_fkko
            if norm_fkko(w.fkko_code) == r["fkko"]:
                placed += (_num(w.placed_norm) or 0.0) + (_num(w.placed_over) or 0.0)
        out.append({**r, "norm": r["generated"] or None, "limit": placed or None})
    return out


def gaps(ctx: ReportContext, data: list[dict] | None = None) -> list[str]:
    from ecodoc.development.waste_inventory import gaps as inv_gaps
    data = data if data is not None else rows(ctx)
    out = list(inv_gaps(ctx))
    if not ctx.period.year:
        out.append("не указан отчётный год — норматив считается за конкретный период")
    for r in data:
        if not r["norm"]:
            out.append(f"{r['name'] or r['fkko']}: нет фактического образования — "
                       f"норматив не на чем обосновать")
    out += [f"раздел «{name}» пишется экологом (в программе не формируется)"
            for name in _NARRATIVE]
    return out


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    """Расчётная часть ПНООЛР (.xlsx)."""
    org = ctx.organization
    data = rows(ctx)
    wb = xlsx.new_workbook()

    ws = wb.create_sheet("Титул")
    xlsx.merge(ws, "A1:F1", TITLE.upper(), bold=True, align="center")
    xlsx.merge(ws, "A2:F2", f"{org.name or org.short_name} · "
                            f"{ctx.period.year or '____'} год", align="center")
    info = [("ИНН", org.inn), ("ОГРН", org.ogrn),
            ("Объект НВОС", ", ".join(o.code for o in ctx.objects) or "—"),
            ("Адрес объекта", "; ".join(o.address for o in ctx.objects if o.address) or "—"),
            ("Видов отходов", str(len(data)))]
    for i, (label, value) in enumerate(info, start=4):
        xlsx.cell(ws, f"A{i}", label, bold=True)
        xlsx.merge(ws, f"B{i}:F{i}", value or "—", align="left")
    xlsx.widths(ws, {"A": 26, "B": 30, "C": 18, "D": 18, "E": 18, "F": 18})

    ws2 = wb.create_sheet("Нормативы и лимиты")
    xlsx.header_row(ws2, 1, ["№", "Наименование отхода", "Код ФККО", "Класс",
                             "Норматив образования, т/год",
                             "Лимит на размещение, т/год",
                             "Обращение", "Объекты размещения / приёмщики"])
    xlsx.widths(ws2, {"A": 5, "B": 44, "C": 16, "D": 8, "E": 18, "F": 18,
                      "G": 20, "H": 30})
    for i, r in enumerate(data, start=1):
        xlsx.data_row(ws2, i + 1, [i, r["name"] or "—", r["fkko"] or "—",
                                   r["hazard"] or "—", r["norm"], r["limit"],
                                   ", ".join(r["operations"]) or "—",
                                   ", ".join(r["receivers"]) or "—"])
    total_row = len(data) + 2
    xlsx.cell(ws2, f"B{total_row}", "ИТОГО", bold=True)
    xlsx.cell(ws2, f"E{total_row}", sum(r["norm"] or 0 for r in data) or None, bold=True)
    xlsx.cell(ws2, f"F{total_row}", sum(r["limit"] or 0 for r in data) or None, bold=True)

    ws3 = wb.create_sheet("Чего не хватает")
    xlsx.header_row(ws3, 1, ["Что дописать или уточнить"])
    xlsx.widths(ws3, {"A": 110})
    for i, text in enumerate(gaps(ctx, data) or ["замечаний нет"], start=2):
        xlsx.data_row(ws3, i, [text])

    return xlsx.save(wb, Path(out_path))
