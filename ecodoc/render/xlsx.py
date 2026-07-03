"""Тонкие хелперы поверх openpyxl для печатных форм Excel."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

THIN = Side(style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEADER_FILL = PatternFill("solid", fgColor="D9E1F2")
BOLD = Font(bold=True)
WRAP = Alignment(wrap_text=True, vertical="center", horizontal="center")
LEFT = Alignment(wrap_text=True, vertical="center", horizontal="left")


def new_workbook() -> Workbook:
    wb = Workbook()
    # удалить дефолтный лист, чтобы формы сами добавляли именованные
    wb.remove(wb.active)
    return wb


def header_row(ws: Worksheet, row: int, values: list[str], widths: list[int] | None = None) -> None:
    for col, val in enumerate(values, start=1):
        c = ws.cell(row=row, column=col, value=val)
        c.font = BOLD
        c.fill = HEADER_FILL
        c.alignment = WRAP
        c.border = BORDER
    if widths:
        for col, w in enumerate(widths, start=1):
            ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = w


def data_row(ws: Worksheet, row: int, values: list, aligns: list[str] | None = None) -> None:
    for col, val in enumerate(values, start=1):
        c = ws.cell(row=row, column=col, value=val)
        c.border = BORDER
        align = (aligns[col - 1] if aligns and col - 1 < len(aligns) else "left")
        c.alignment = LEFT if align == "left" else WRAP


def save(wb: Workbook, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
