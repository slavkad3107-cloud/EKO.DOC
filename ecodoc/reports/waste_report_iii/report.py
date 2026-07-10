"""Отчётность об образовании, утилизации, обезвреживании и размещении отходов
(объекты III категории / субъекты МСП).

ВНИМАНИЕ по НПА: прежний федеральный Приказ Минприроды № 30 от 16.02.2010
УТРАТИЛ СИЛУ с 01.01.2021 (регуляторная гильотина). Отдельной действующей
ФЕДЕРАЛЬНОЙ формы больше нет: для объектов III категории (федеральный надзор)
эти сведения об отходах подаются В СОСТАВЕ отчёта ПЭК (Приказ № 109 от
18.02.2022, форма — Приказ № 173 от 15.03.2024), срок — до 25 марта. Для МСП
на объектах РЕГИОНАЛЬНОГО надзора действуют региональные уведомительные
порядки (СПб/ЛО и др.) со своими сроками. Приказ № 1028 — это Порядок УЧЁТА
(журнал), а не форма отчётности.

Текущий генератор строит самостоятельный упрощённый отчёт (баланс без остатков
на начало/конец и без разбивки передачи) — служит промежуточным/справочным
документом; для официальной подачи ориентируйтесь на раздел отходов отчёта ПЭК
либо на региональный формат.

Данные — из ctx.wastes; получатели отходов — ctx.extra['waste_receivers']:
    [{"fkko": "40211001515", "receiver": "ООО ...", "inn": "...",
      "license": "№... от ...", "operation": "передача на размещение"}, ...]
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


@register
class WasteReportIII(Report):
    code = "waste-report-iii"
    title = "Отчётность об образовании/утилизации отходов (III кат./МСП)"

    def _receivers(self) -> list[dict]:
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        return e.get("waste_receivers", [])

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        if not self.ctx.organization.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.wastes:
            issues.append(Issue("error", "отходы", "нет позиций отходов"))
        transferred = {w.fkko_code for w in self.ctx.wastes if D(w.transferred) > 0}
        with_recv = {r.get("fkko") for r in self._receivers()}
        missing = transferred - with_recv
        if missing:
            issues.append(Issue("warning", "получатели",
                                "для переданных отходов не указаны получатели "
                                f"(extra.waste_receivers): {', '.join(sorted(missing))}"))
        return issues

    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        root = etree.Element("ОтчётностьОтходыIII", version="0.1")
        org = el(root, "Организация")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "ОГРН", o.ogrn)
        el(root, "ОтчётныйГод", self.ctx.period.year)
        items = el(root, "Отходы")
        for w in self.ctx.wastes:
            x = el(items, "Отход", фкко=w.fkko_code, класс=w.hazard_class)
            el(x, "Наименование", w.name)
            el(x, "Образовано", D(w.generated))
            el(x, "Утилизировано", D(w.used))
            el(x, "Обезврежено", D(w.neutralized))
            el(x, "Передано", D(w.transferred))
            el(x, "Размещено", D(w.placed_norm) + D(w.placed_over))
        recv = el(root, "Получатели")
        for r in self._receivers():
            x = el(recv, "Получатель", фкко=r.get("fkko", ""))
            el(x, "Наименование", r.get("receiver", ""))
            el(x, "ИНН", r.get("inn", ""))
            el(x, "Лицензия", r.get("license", ""))
            el(x, "Операция", r.get("operation", ""))
        write_tree(root, out_path)
        return out_path

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        ws = wb.create_sheet("Отходы III кат.")
        xlsx.header_row(ws, 1, ["ФККО", "Наименование", "Класс", "Образовано, т",
                                "Утилизировано, т", "Обезврежено, т",
                                "Передано, т", "Размещено, т"],
                        widths=[14, 34, 7, 13, 14, 13, 12, 12])
        r = 2
        for w in self.ctx.wastes:
            xlsx.data_row(ws, r, [w.fkko_code, w.name, w.hazard_class,
                                  float(D(w.generated)), float(D(w.used)),
                                  float(D(w.neutralized)), float(D(w.transferred)),
                                  float(D(w.placed_norm) + D(w.placed_over))])
            r += 1
        ws2 = wb.create_sheet("Получатели")
        xlsx.header_row(ws2, 1, ["ФККО", "Получатель", "ИНН", "Лицензия", "Операция"],
                        widths=[14, 34, 14, 26, 24])
        r = 2
        for rec in self._receivers():
            xlsx.data_row(ws2, r, [rec.get("fkko", ""), rec.get("receiver", ""),
                                   rec.get("inn", ""), rec.get("license", ""),
                                   rec.get("operation", "")])
            r += 1
        return xlsx.save(wb, out_path)
