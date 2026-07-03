"""Региональный кадастр отходов (Санкт-Петербург / Ленинградская область).

Данные — из ctx.wastes (та же модель движения) + получатели из
ctx.extra['waste_receivers'] (общие с формой III категории). Срок подачи —
региональный (ориентир 1 апреля, сверять с порталом региона). Формат выгрузки
регионального ПО отличается от федерального — XML здесь самоописательный,
печатная форма покрывает типовой состав сведений кадастра.
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

_REGIONS = {"78", "47", "40", "41", "46", "47"}  # СПб (78/40...) и ЛО (47/41/46) — коды в номерах ОНВ


@register
class CadastreSPB(Report):
    code = "cadastre-spb"
    title = "Кадастр отходов (СПб/ЛО)"

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.wastes:
            issues.append(Issue("error", "отходы", "нет позиций отходов"))
        regions = {str(ob.region_code) for ob in self.ctx.objects if ob.region_code}
        if regions and not (regions & _REGIONS):
            issues.append(Issue("warning", "регион",
                                "объекты вне СПб/ЛО — проверьте, требуется ли региональный кадастр "
                                f"(коды: {', '.join(sorted(regions))})"))
        issues.append(Issue("warning", "срок",
                            "срок подачи кадастра региональный — сверьте с порталом региона"))
        return issues

    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        root = etree.Element("КадастрОтходов", version="0.1", регион="СПб/ЛО")
        org = el(root, "Организация")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "ОГРН", o.ogrn)
        el(org, "Адрес", o.address)
        el(org, "ОКТМО", o.oktmo)
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
            el(x, "НаличиеКонецГода", D(w.accumulated_end))
        recv = el(root, "Получатели")
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        for r in e.get("waste_receivers", []):
            x = el(recv, "Получатель", фкко=r.get("fkko", ""))
            el(x, "Наименование", r.get("receiver", ""))
            el(x, "ИНН", r.get("inn", ""))
            el(x, "Лицензия", r.get("license", ""))
        write_tree(root, out_path)
        return out_path

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        ws = wb.create_sheet("Кадастр отходов")
        xlsx.header_row(ws, 1, ["ФККО", "Наименование", "Класс", "Образовано, т",
                                "Утилизировано, т", "Обезврежено, т", "Передано, т",
                                "Размещено, т", "Остаток, т"],
                        widths=[14, 32, 7, 13, 14, 13, 12, 12, 11])
        r = 2
        for w in self.ctx.wastes:
            xlsx.data_row(ws, r, [w.fkko_code, w.name, w.hazard_class,
                                  float(D(w.generated)), float(D(w.used)),
                                  float(D(w.neutralized)), float(D(w.transferred)),
                                  float(D(w.placed_norm) + D(w.placed_over)),
                                  float(D(w.accumulated_end))])
            r += 1
        return xlsx.save(wb, out_path)
