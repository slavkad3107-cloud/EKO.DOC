"""План мероприятий по уменьшению выбросов в периоды НМУ.

Основание: ст. 19 ФЗ-96 «Об охране атмосферного воздуха», Приказ Минприроды
№ 811 от 28.11.2019 (порядок разработки). План содержит мероприятия по трём
режимам работы предприятия при получении предупреждений I, II, III степени
опасности НМУ с целевым процентом сокращения выбросов.

Данные: реквизиты из ReportContext.organization/objects; мероприятия — из
ctx.extra['nmu']['measures'] (список {mode: 1|2|3, text, reduction_pct}).
Если мероприятий нет — выводится типовой каркас режимов с плейсхолдерами.
"""
from __future__ import annotations

from pathlib import Path

from ecodoc.core.models import ReportContext

_MODES = {
    1: ("Первый режим (I степень опасности НМУ)",
        "Организационно-технические мероприятия, не снижающие производственные "
        "показатели: усиление контроля за работой ГОУ и технологического "
        "оборудования, запрет пусковых/наладочных работ, интенсификация "
        "влажной уборки, контроль работы двигателей. Ориентир сокращения "
        "выбросов — 15–20 %."),
    2: ("Второй режим (II степень опасности НМУ)",
        "Мероприятия первого режима + снижение производительности отдельных "
        "источников, перевод на резервное топливо с меньшим содержанием серы, "
        "ограничение погрузо-разгрузочных работ с пылящими материалами. "
        "Ориентир сокращения — 20–40 %."),
    3: ("Третий режим (III степень опасности НМУ)",
        "Мероприятия первого и второго режимов + частичная остановка "
        "источников и производств, не имеющих непрерывного цикла; снижение "
        "нагрузки до технологического минимума. Ориентир сокращения — 40–60 %."),
}


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    from docx import Document
    from docx.shared import Pt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    org = ctx.organization
    measures = (ctx.extra.get("nmu", {}) or {}).get("measures", []) \
        if isinstance(ctx.extra, dict) else []

    doc = Document()
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(12)

    doc.add_heading("ПЛАН МЕРОПРИЯТИЙ", level=1)
    doc.add_heading("по уменьшению выбросов загрязняющих веществ в атмосферный "
                    "воздух в периоды неблагоприятных метеорологических условий",
                    level=2)
    doc.add_paragraph(f"{org.name or '[наименование организации]'} "
                      f"(ИНН {org.inn or '—'})")
    for o in ctx.objects:
        doc.add_paragraph(f"Объект НВОС: {o.code or '—'} — {o.name or ''}, "
                          f"{o.address or ''}")
    doc.add_paragraph("Основание: ст. 19 ФЗ-96, Приказ Минприроды России "
                      "от 28.11.2019 № 811.").italic = True

    for mode in (1, 2, 3):
        title, default_text = _MODES[mode]
        doc.add_heading(title, level=2)
        own = [m for m in measures if int(m.get("mode", 0)) == mode]
        if own:
            table = doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            hdr = table.rows[0].cells
            hdr[0].text = "№"; hdr[1].text = "Мероприятие"
            hdr[2].text = "Сокращение выбросов, %"
            for i, m in enumerate(own, 1):
                row = table.add_row().cells
                row[0].text = str(i)
                row[1].text = str(m.get("text", ""))
                row[2].text = str(m.get("reduction_pct", ""))
        else:
            doc.add_paragraph(default_text)
            doc.add_paragraph("[Впишите конкретные мероприятия по вашим "
                              "источникам — раздел заполняется предприятием.]").italic = True

    doc.add_heading("Ответственные и порядок оповещения", level=2)
    doc.add_paragraph("Ответственный за проведение мероприятий: "
                      f"{org.director_name or '[должность, ФИО]'}.")
    doc.add_paragraph("Предупреждения о НМУ принимаются от территориального "
                      "органа Росгидромета; мероприятия вводятся в срок не "
                      "позднее 3 часов с момента получения предупреждения.")
    doc.save(str(out_path))
    return out_path
