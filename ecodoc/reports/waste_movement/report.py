"""Учёт в области обращения с отходами (движение отходов), Приказ Минприроды
№1028. Таблица движения: остаток на начало → образовано/принято →
утилизировано/обезврежено/передано/размещено → остаток на конец.

Реализованы печатная форма (Excel) и черновой XML. Баланс проверяется.
"""
from __future__ import annotations

from pathlib import Path

from ecodoc.core.models import Issue, ReportContext
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report

from lxml import etree

_COLS = [
    ("fkko_code", "Код ФККО", 14),
    ("name", "Наименование отхода", 32),
    ("hazard_class", "Класс", 7),
    ("accumulated_start", "Остаток на начало, т", 14),
    ("generated", "Образовано, т", 13),
    ("received", "Принято, т", 12),
    ("used", "Утилизировано, т", 13),
    ("neutralized", "Обезврежено, т", 13),
    ("transferred", "Передано, т", 12),
    ("placed_norm", "Размещено (лимит), т", 14),
    ("placed_over", "Размещено (сверх), т", 14),
    ("accumulated_end", "Остаток на конец, т", 14),
]


@register
class WasteMovement(Report):
    code = "waste-movement"
    title = "Учёт отходов (движение), Приказ №1028"

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        if not self.ctx.organization.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not self.ctx.wastes:
            issues.append(Issue("error", "отходы", "нет ни одной позиции отходов"))
        for w in self.ctx.wastes:
            bal_in = D(w.accumulated_start) + D(w.generated) + D(w.received)
            bal_out = (D(w.used) + D(w.neutralized) + D(w.transferred)
                       + D(w.placed_norm) + D(w.placed_over) + D(w.accumulated_end))
            if abs(bal_in - bal_out) > D("0.001"):
                issues.append(Issue(
                    "warning", f"баланс/{w.fkko_code}",
                    f"приход {bal_in} ≠ расход+остаток {bal_out}"))
        return issues

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        ws = wb.create_sheet("Движение отходов")
        xlsx.header_row(ws, 1, [c[1] for c in _COLS], widths=[c[2] for c in _COLS])
        r = 2
        for w in self.ctx.wastes:
            xlsx.data_row(ws, r, [_cell(w, attr) for attr, _, _ in _COLS])
            r += 1
        xlsx.save(wb, out_path)
        return out_path

    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        root = etree.Element("УчётОтходов", version="0.1")
        p = el(root, "Организация")
        el(p, "Наименование", o.name)
        el(p, "ИНН", o.inn)
        el(p, "КПП", o.kpp)
        el(root, "Год", self.ctx.period.year)
        items = el(root, "Отходы")
        for w in self.ctx.wastes:
            x = el(items, "Отход")
            for attr, ru, _ in _COLS:
                el(x, _xml_tag(attr), _cell(w, attr))
        write_tree(root, out_path)
        return out_path


def _cell(w, attr):
    val = getattr(w, attr)
    if attr in ("fkko_code", "name", "hazard_class"):
        return val
    return float(D(val))


def _xml_tag(attr: str) -> str:
    return {
        "fkko_code": "КодФККО", "name": "Наименование", "hazard_class": "Класс",
        "accumulated_start": "ОстатокНачало", "generated": "Образовано",
        "received": "Принято", "used": "Утилизировано", "neutralized": "Обезврежено",
        "transferred": "Передано", "placed_norm": "РазмещеноЛимит",
        "placed_over": "РазмещеноСверх", "accumulated_end": "ОстатокКонец",
    }[attr]
