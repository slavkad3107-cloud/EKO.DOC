"""Форма 2-ТП (воздух) — сведения об охране атмосферного воздуха.
Годовая, до 22 января, в ЛКПП РПН (есть пакетный API).

Данные — из ctx.pollutants (medium=air): выброшено всего = норматив + лимит +
сверх. Уловлено/обезврежено — ctx.extra['tp2_air'] = {"captured": т, ...}.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from lxml import etree

from ecodoc.core.models import Issue, Medium
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report


@register
class TP2Air(Report):
    code = "2tp-air"
    title = "2-ТП (воздух)"

    def _air(self):
        return [p for p in self.ctx.pollutants if p.medium == Medium.AIR]

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not o.okpo:
            issues.append(Issue("warning", "ОКПО", "для 2-ТП обязателен код ОКПО"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self._air():
            issues.append(Issue("error", "выбросы", "нет веществ с выбросами в воздух"))
        return issues

    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        root = etree.Element("Форма2ТПВоздух", version="0.1")
        org = el(root, "Респондент")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "ОКПО", o.okpo)
        el(org, "ОКВЭД", o.okved)
        el(root, "ОтчётныйГод", self.ctx.period.year)
        items = el(root, "Выбросы")
        total = Decimal("0")
        for p in self._air():
            t = _tot(p)
            total += t
            x = el(items, "Вещество", код=p.code)
            el(x, "Наименование", p.name)
            el(x, "ВыброшеноВсего", t)
            el(x, "ВПределахНорматива", D(p.mass_norm))
            el(x, "ВПределахЛимита", D(p.mass_limit))
            el(x, "СверхНорматива", D(p.mass_over))
        el(root, "ИтогоВыброшено", total)
        extra = self.ctx.extra.get("tp2_air", {}) if isinstance(self.ctx.extra, dict) else {}
        if extra:
            g = el(root, "УловленоОбезврежено")
            el(g, "Уловлено", extra.get("captured", 0))
        write_tree(root, out_path)
        return out_path

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        ws = wb.create_sheet("2-ТП (воздух)")
        xlsx.header_row(ws, 1, ["Код", "Вещество", "Выброшено всего, т",
                                "В пределах норматива, т", "В пределах лимита, т",
                                "Сверх, т"],
                        widths=[10, 36, 16, 18, 18, 12])
        r = 2
        total = Decimal("0")
        for p in self._air():
            t = _tot(p)
            total += t
            xlsx.data_row(ws, r, [p.code, p.name, float(t), float(D(p.mass_norm)),
                                  float(D(p.mass_limit)), float(D(p.mass_over))])
            r += 1
        xlsx.data_row(ws, r, ["", "ИТОГО", float(total), "", "", ""])
        for col in range(1, 7):
            ws.cell(row=r, column=col).font = xlsx.BOLD
        return xlsx.save(wb, out_path)


def _tot(p) -> Decimal:
    return D(p.mass_norm) + D(p.mass_limit) + D(p.mass_over)
