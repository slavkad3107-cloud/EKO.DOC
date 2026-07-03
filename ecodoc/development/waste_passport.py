"""Паспорт отхода I–IV класса опасности (Приказ Минприроды №1026 от 08.12.2020).

Полностью автоматизируемо для отходов с кодом ФККО: типовая форма заполняется
из перечня отходов (ReportContext.wastes) + сведений о составе из
ctx.extra['waste_details'][<код ФККО>]. Для отходов V класса паспорт не нужен.

Состав/агрегатное состояние/происхождение, если не заданы, выводятся
плейсхолдерами — их источник: протоколы КХА/биотестирования (подгружаются как
исходники) либо банк данных об отходах.
"""
from __future__ import annotations

from pathlib import Path

from ecodoc.core.models import ReportContext, WasteFlow

_AGG = "агрегатное состояние и физическая форма"


def _details(ctx: ReportContext, w: WasteFlow) -> dict:
    store = ctx.extra.get("waste_details", {}) if isinstance(ctx.extra, dict) else {}
    return store.get(w.fkko_code, {})


def generate(ctx: ReportContext, out_dir: str | Path) -> list[Path]:
    """Сгенерировать по одному .docx-паспорту на каждый отход I–IV класса."""
    from docx import Document
    from docx.shared import Pt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    org = ctx.organization

    for w in ctx.wastes:
        if not (1 <= int(w.hazard_class) <= 4):
            continue  # паспорт нужен только для I–IV класса
        d = _details(ctx, w)
        doc = Document()
        doc.styles["Normal"].font.name = "Times New Roman"
        doc.styles["Normal"].font.size = Pt(12)

        doc.add_heading("ПАСПОРТ ОТХОДА", level=1)
        doc.add_paragraph("(I–IV класса опасности, форма по Приказу Минприроды России "
                          "от 08.12.2020 №1026)").italic = True

        rows = [
            ("Наименование вида отхода", w.name or "—"),
            ("Код по ФККО", w.fkko_code or "—"),
            ("Класс опасности для окружающей среды", _roman(w.hazard_class)),
            ("Агрегатное состояние и физическая форма", d.get(_AGG, "‹заполнить›")),
            ("Происхождение отхода / технологический процесс", d.get("origin", "‹заполнить›")),
        ]
        t = doc.add_table(rows=0, cols=2)
        t.style = "Table Grid"
        for k, v in rows:
            c = t.add_row().cells
            c[0].text = k
            c[1].text = str(v)

        doc.add_heading("Компонентный состав отхода", level=2)
        comp = d.get("components") or []
        ct = doc.add_table(rows=1, cols=3)
        ct.style = "Table Grid"
        hdr = ct.rows[0].cells
        hdr[0].text, hdr[1].text, hdr[2].text = (
            "Компонент", "Содержание, % масс.", "Документ-основание")
        if comp:
            for it in comp:
                c = ct.add_row().cells
                c[0].text = str(it.get("name", ""))
                c[1].text = str(it.get("percent", ""))
                c[2].text = str(it.get("basis", ""))
        else:
            c = ct.add_row().cells
            c[0].text = "‹состав из протокола КХА — подгрузить›"
            c[1].text = ""
            c[2].text = d.get("basis", "")

        doc.add_paragraph()
        doc.add_paragraph(f"Сведения о лице, в результате деятельности которого образуется отход: "
                          f"{org.name}, ИНН {org.inn}, ОГРН {org.ogrn}, {org.address}")
        doc.add_paragraph()
        sig = doc.add_table(rows=1, cols=2)
        sig.rows[0].cells[0].text = f"{org.director_position}"
        sig.rows[0].cells[1].text = f"______________ / {org.director_name} /"

        fname = f"passport_{w.fkko_code or 'noFKKO'}.docx"
        path = out_dir / fname
        doc.save(path)
        paths.append(path)
    return paths


def _roman(hazard_class) -> str:
    return {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}.get(int(hazard_class), str(hazard_class))
