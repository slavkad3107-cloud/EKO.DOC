"""Программа производственного экологического контроля (ПЭК).

Основание: ст. 67 ФЗ-7, Приказ Минприроды № 109 от 18.02.2022 (требования к
содержанию программы ПЭК). Программа разрабатывается для объектов I–III
категории и содержит разделы: общие сведения, сведения об инвентаризациях,
подразделения/лица ответственные, а также программы контроля стационарных
источников выбросов, сбросов, в области обращения с отходами.

Данные: реквизиты и объекты из ReportContext; точки/периодичность контроля —
из ctx.extra['pek']['points'] (список {medium, point, indicators, frequency}).
Пустые разделы выводятся каркасом с плейсхолдерами.
"""
from __future__ import annotations

from pathlib import Path

from ecodoc.core.models import ReportContext


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    from docx import Document
    from docx.shared import Pt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    org = ctx.organization
    pek = ctx.extra.get("pek", {}) if isinstance(ctx.extra, dict) else {}
    points = pek.get("points", [])

    doc = Document()
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(12)

    doc.add_heading("ПРОГРАММА", level=1)
    doc.add_heading("производственного экологического контроля", level=2)
    doc.add_paragraph(f"{org.name or '[наименование организации]'} "
                      f"(ИНН {org.inn or '—'})")
    doc.add_paragraph("Основание: ст. 67 ФЗ-7, Приказ Минприроды России "
                      "от 18.02.2022 № 109.").italic = True

    doc.add_heading("1. Общие сведения", level=2)
    for o in ctx.objects:
        doc.add_paragraph(f"Объект НВОС {o.code or '—'} — {o.name or ''}, "
                          f"категория {o.category or '[?]'}, {o.address or ''}")
    if not ctx.objects:
        doc.add_paragraph("[Укажите объекты НВОС и их категории.]").italic = True

    doc.add_heading("2. Сведения об инвентаризациях", level=2)
    doc.add_paragraph("Инвентаризация источников выбросов: [реквизиты, дата].")
    doc.add_paragraph("Инвентаризация отходов / нормативы образования: [реквизиты].")

    doc.add_heading("3. Ответственные за осуществление ПЭК", level=2)
    doc.add_paragraph(f"Ответственное лицо: {org.director_name or '[должность, ФИО]'}. "
                      "Подразделение: [эколог/служба охраны окружающей среды].")

    doc.add_heading("4. Программа контроля (точки, показатели, периодичность)",
                    level=2)
    if points:
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        h = table.rows[0].cells
        h[0].text = "Среда"; h[1].text = "Точка контроля"
        h[2].text = "Показатели"; h[3].text = "Периодичность"
        for p in points:
            r = table.add_row().cells
            r[0].text = str(p.get("medium", ""))
            r[1].text = str(p.get("point", ""))
            r[2].text = str(p.get("indicators", ""))
            r[3].text = str(p.get("frequency", ""))
    else:
        doc.add_paragraph("Стационарные источники выбросов: [точки, вещества, "
                          "периодичность контроля].")
        doc.add_paragraph("Сбросы сточных вод: [выпуски, показатели, периодичность].")
        doc.add_paragraph("Обращение с отходами: [места накопления, контроль].")
        doc.add_paragraph("[Заполните таблицу точек контроля через ctx.extra['pek']"
                          "['points'] или вручную.]").italic = True

    doc.save(str(out_path))
    return out_path
