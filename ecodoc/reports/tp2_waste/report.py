"""Форма 2-ТП (отходы) — сведения об образовании, обработке, утилизации,
обезвреживании, размещении отходов. Годовая, до 1 февраля, в ЛКПП РПН
(для этой формы в ЛКПП есть пакетный API — первоочередная для контура
«Загрузка»).

Данные — целиком из ctx.wastes (та же модель, что и учёт движения №1028),
двойного ввода нет.
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

from ecodoc.core.models import Issue
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report

_COLS = [
    ("fkko_code", "Код ФККО"),
    ("name", "Наименование отхода"),
    ("hazard_class", "Класс"),
    ("accumulated_start", "Наличие на начало года, т"),
    ("generated", "Образовано, т"),
    ("received", "Поступило от других, т"),
    ("used", "Утилизировано, т"),
    ("neutralized", "Обезврежено, т"),
    ("transferred", "Передано другим, т"),
    ("placed_norm", "Размещено (в пределах лимита), т"),
    ("placed_over", "Размещено (сверх лимита), т"),
    ("accumulated_end", "Наличие на конец года, т"),
]
_TAGS = {
    "fkko_code": "КодФККО", "name": "Наименование", "hazard_class": "Класс",
    "accumulated_start": "НаличиеНачало", "generated": "Образовано",
    "received": "Поступило", "used": "Утилизировано",
    "neutralized": "Обезврежено", "transferred": "Передано",
    "placed_norm": "РазмещеноЛимит", "placed_over": "РазмещеноСверх",
    "accumulated_end": "НаличиеКонец",
}


@register
class TP2Waste(Report):
    code = "2tp-waste"
    title = "2-ТП (отходы)"

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not o.okpo:
            issues.append(Issue("warning", "ОКПО", "для 2-ТП обязателен код ОКПО"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.wastes:
            issues.append(Issue("error", "отходы", "нет позиций отходов"))
        return issues

    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        root = etree.Element("Форма2ТПОтходы", version="0.1")
        org = el(root, "Респондент")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "ОКПО", o.okpo)
        el(org, "ОКВЭД", o.okved)
        el(org, "Адрес", o.address)
        el(root, "ОтчётныйГод", self.ctx.period.year)
        items = el(root, "Отходы")
        for w in self.ctx.wastes:
            x = el(items, "Отход")
            for attr, _ in _COLS:
                el(x, _TAGS[attr], _v(w, attr))
        write_tree(root, out_path)
        return out_path

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        ws = wb.create_sheet("2-ТП (отходы)")
        xlsx.header_row(ws, 1, [c[1] for c in _COLS],
                        widths=[14, 32, 7] + [14] * 9)
        r = 2
        for w in self.ctx.wastes:
            xlsx.data_row(ws, r, [_v(w, a) for a, _ in _COLS])
            r += 1
        # итоговая строка по массам
        total_row = ["", "ИТОГО", ""]
        for attr, _ in _COLS[3:]:
            total_row.append(float(sum((D(getattr(w, attr)) for w in self.ctx.wastes),
                                       start=D(0))))
        xlsx.data_row(ws, r, total_row)
        for col in range(1, len(_COLS) + 1):
            ws.cell(row=r, column=col).font = xlsx.BOLD
        return xlsx.save(wb, out_path)


def _v(w, attr):
    val = getattr(w, attr)
    if attr in ("fkko_code", "name", "hazard_class"):
        return val
    return float(D(val))
