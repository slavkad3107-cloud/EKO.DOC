"""Заполнение бланка журнала учёта отходов (Приказ №1028) из папки «Формы».

Пользователь ведёт журнал в готовом файле Excel, где часть ячеек — формулы
(ссылки на титул, суммы). Поэтому: не рисуем лист заново, а вписываем данные
в бланк-образец, оставляя формулы на месте (их пересчитает Excel).

Колонки ищем по подписям граф, а не по фиксированным адресам: бланки у разных
организаций смещены на строку-другую.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from ecodoc.render import template_xlsx as tx

CODE = "waste-movement"

# подпись графы (начало) → атрибут WasteFlow
_COLUMNS = [
    ("наименование отход", "name"),
    ("код фкко", "fkko_code"),
    ("класс опасности", "hazard_class"),
    ("образовано отходов", "generated"),
    ("получено отходов", "received"),
    ("утилизировано", "used"),
    ("обезврежено", "neutralized"),
    ("передано отходов", "transferred"),
]

_TITLE_FIELDS = [
    ("наименование юридического лица", "org_name"),
    ("индивидуального предпринимателя", "org_name"),
    ("инн", "inn"),
    ("огрн", "ogrn"),
    ("отчетный год", "year"),
    ("отчётный год", "year"),
]


def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return None
    return float(d) if d else None


def header_row(ws, max_row: int = 40) -> tuple[int, dict] | None:
    """Найти строку шапки таблицы и колонки граф по подписям."""
    pos = tx.find_anchor(ws, "код фкко", limit_rows=max_row)
    if not pos:
        return None
    row = pos[0]
    cols: dict[str, int] = {}
    for r in range(max(1, row - 2), row + 3):          # шапка бывает в 2–3 строки
        for cell in ws[r]:
            if not isinstance(cell.value, str):
                continue
            text = re.sub(r"\s+", " ", cell.value).strip().lower()
            for label, attr in _COLUMNS:
                if attr not in cols and text.startswith(label):
                    cols[attr] = cell.column
    return (row, cols) if "fkko_code" in cols else None


def first_data_row(ws, header: int) -> int:
    """Первая строка под шапкой, где ещё нет данных."""
    row = header + 1
    # пропускаем строку нумерации граф («1», «2», «3» …) и заполненные строки
    while row < header + 200:
        values = [c.value for c in ws[row]]
        if all(v in (None, "") for v in values):
            return row
        row += 1
    return header + 1


def fill(ctx, out_path: str | Path, sample: Path | None = None) -> Path | None:
    """Заполнить бланк журнала. None — если образца нет (рисуем кодом)."""
    from ecodoc.core import forms_registry
    sample = sample or forms_registry.sample_for(CODE)
    if sample is None or sample.suffix.lower() not in (".xlsx", ".xlsm"):
        return None

    wb = tx.open_template(sample)
    org = ctx.organization
    values = {"org_name": org.name or org.short_name, "inn": org.inn,
              "ogrn": org.ogrn, "year": ctx.period.year or ""}

    # титул: подписи → значения (пропускаем ячейки с формулами)
    if wb.sheetnames:
        title_ws = wb[wb.sheetnames[0]]
        pairs = {}
        for label, key in _TITLE_FIELDS:
            if values.get(key) not in (None, ""):
                pairs[label] = values[key]
        tx.fill_by_labels(title_ws, pairs)

    filled_sheets = 0
    for name in wb.sheetnames:
        ws = wb[name]
        head = header_row(ws)
        if not head:
            continue
        header, cols = head
        row = first_data_row(ws, header)
        for w in ctx.wastes:
            if not (w.fkko_code or w.name):
                continue
            data = {
                "name": w.name,
                "fkko_code": w.fkko_code,
                "hazard_class": w.hazard_class or None,
                "generated": _num(w.generated),
                "received": _num(w.received),
                "used": _num(w.used),
                "neutralized": _num(w.neutralized),
                "transferred": _num(w.transferred),
            }
            for attr, col in cols.items():
                value = data.get(attr)
                if value in (None, ""):
                    continue
                if tx.is_formula(ws, row, col):     # расчётную графу не трогаем
                    continue
                ws.cell(row=row, column=col, value=value)
            row += 1
        filled_sheets += 1
    if not filled_sheets:
        return None
    return tx.save_as(wb, out_path)
