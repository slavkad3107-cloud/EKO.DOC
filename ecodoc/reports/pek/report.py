"""Отчёт об организации и о результатах осуществления ПЭК (Приказ Минприроды
№109 от 14.06.2018, форма — Приказ №261 от 14.06.2018).

Полностью автоматическая сборка из ReportContext:
  * общие сведения        — organization + objects;
  * выбросы (раздел 2)    — ctx.pollutants (medium=air);
  * сбросы (раздел 3)     — ctx.pollutants (medium=water);
  * отходы (раздел 4)     — ctx.wastes;
  * сведения о программе ПЭК и результаты наблюдений — ctx.extra['pek']:
        {"program_number": "...", "program_date": "ДД.ММ.ГГГГ",
         "lab": "аккредитованная лаборатория (аттестат ...)",
         "results": [{"point": "ист. №1", "substance": "0301",
                      "plan": 4, "fact": 4, "exceed": false}, ...]}

Протоколы КХА/биотестирования подгружаются как исходники (analyze) и
перечисляются в реестре результатов.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from lxml import etree

from ecodoc.core.models import Issue, Medium, ReportContext
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report


@register
class PEKReport(Report):
    code = "pek"
    title = "Отчёт по ПЭК (Приказ №109)"

    # ------------------------------------------------------------------ #
    def _pek(self) -> dict:
        return self.ctx.extra.get("pek", {}) if isinstance(self.ctx.extra, dict) else {}

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not o.name:
            issues.append(Issue("error", "наименование", "не указано наименование организации"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.objects:
            issues.append(Issue("error", "объекты", "ПЭК сдаётся по объектам I–III категории — добавьте объект НВОС"))
        cats = {str(ob.category).strip().upper() for ob in self.ctx.objects}
        if cats and cats <= {"IV", "4"}:
            issues.append(Issue("warning", "категория", "для объектов только IV категории отчёт ПЭК не требуется"))
        pek = self._pek()
        if not pek.get("program_number") and not pek.get("program_date"):
            issues.append(Issue("warning", "программа",
                                "нет сведений о программе ПЭК (extra.pek.program_number/program_date)"))
        if not pek.get("results"):
            issues.append(Issue("warning", "результаты",
                                "нет результатов наблюдений (extra.pek.results) — раздел будет пустым; "
                                "подгрузите протоколы КХА как исходники"))
        if not (self.ctx.pollutants or self.ctx.wastes):
            issues.append(Issue("error", "данные", "нет ни выбросов/сбросов, ни отходов"))
        return issues

    # ------------------------------------------------------------------ #
    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        pek = self._pek()

        root = etree.Element("ОтчётПЭК", version="0.1", форма=self.code)
        org = el(root, "Организация")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "КПП", o.kpp)
        el(org, "ОГРН", o.ogrn)
        el(org, "Адрес", o.address)
        el(root, "ОтчётныйГод", self.ctx.period.year)

        prog = el(root, "ПрограммаПЭК")
        el(prog, "Номер", pek.get("program_number", ""))
        el(prog, "ДатаУтверждения", pek.get("program_date", ""))
        el(prog, "Лаборатория", pek.get("lab", ""))

        objs = el(root, "ОбъектыНВОС")
        for ob in self.ctx.objects:
            x = el(objs, "Объект")
            el(x, "Код", ob.code)
            el(x, "Наименование", ob.name)
            el(x, "Категория", ob.category)

        air = el(root, "Выбросы")
        for p in (x for x in self.ctx.pollutants if x.medium == Medium.AIR):
            x = el(air, "Вещество", код=p.code)
            el(x, "Наименование", p.name)
            el(x, "МассаВсего", _tot(p))
        water = el(root, "Сбросы")
        for p in (x for x in self.ctx.pollutants if x.medium == Medium.WATER):
            x = el(water, "Вещество", код=p.code)
            el(x, "Наименование", p.name)
            el(x, "МассаВсего", _tot(p))

        waste = el(root, "Отходы")
        for w in self.ctx.wastes:
            x = el(waste, "Отход", фкко=w.fkko_code, класс=w.hazard_class)
            el(x, "Наименование", w.name)
            el(x, "Образовано", w.generated)
            el(x, "Передано", w.transferred)
            el(x, "Размещено", D(w.placed_norm) + D(w.placed_over))

        res = el(root, "РезультатыНаблюдений")
        for r in pek.get("results", []):
            x = el(res, "Наблюдение")
            el(x, "Точка", r.get("point", ""))
            el(x, "Показатель", r.get("substance", ""))
            el(x, "План", r.get("plan", ""))
            el(x, "Факт", r.get("fact", ""))
            el(x, "Превышение", "да" if r.get("exceed") else "нет")

        write_tree(root, out_path)
        return out_path

    # ------------------------------------------------------------------ #
    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        pek = self._pek()
        wb = xlsx.new_workbook()

        ws = wb.create_sheet("Титул")
        ws.column_dimensions["A"].width = 40
        ws.column_dimensions["B"].width = 52
        rows = [
            ("ОТЧЁТ ОБ ОРГАНИЗАЦИИ И О РЕЗУЛЬТАТАХ ПЭК", ""),
            ("Отчётный год", self.ctx.period.year),
            ("Организация", o.name),
            ("ИНН / КПП", f"{o.inn} / {o.kpp}"),
            ("Адрес", o.address),
            ("Программа ПЭК", f"№{pek.get('program_number','—')} от {pek.get('program_date','—')}"),
            ("Лаборатория", pek.get("lab", "—")),
            ("Объекты НВОС", ", ".join(f"{x.code} ({x.category})" for x in self.ctx.objects)),
        ]
        for i, (k, v) in enumerate(rows, 1):
            a = ws.cell(row=i, column=1, value=k)
            ws.cell(row=i, column=2, value=v)
            if i == 1:
                a.font = xlsx.BOLD

        ws = wb.create_sheet("Выбросы")
        xlsx.header_row(ws, 1, ["Код", "Вещество", "Масса всего, т"], widths=[10, 40, 16])
        r = 2
        for p in (x for x in self.ctx.pollutants if x.medium == Medium.AIR):
            xlsx.data_row(ws, r, [p.code, p.name, float(_tot(p))])
            r += 1

        ws = wb.create_sheet("Сбросы")
        xlsx.header_row(ws, 1, ["Код", "Вещество", "Масса всего, т"], widths=[10, 40, 16])
        r = 2
        for p in (x for x in self.ctx.pollutants if x.medium == Medium.WATER):
            xlsx.data_row(ws, r, [p.code, p.name, float(_tot(p))])
            r += 1

        ws = wb.create_sheet("Отходы")
        xlsx.header_row(ws, 1, ["ФККО", "Наименование", "Класс", "Образовано, т",
                                "Передано, т", "Размещено, т"],
                        widths=[14, 36, 8, 14, 14, 14])
        r = 2
        for w in self.ctx.wastes:
            xlsx.data_row(ws, r, [w.fkko_code, w.name, w.hazard_class,
                                  float(D(w.generated)), float(D(w.transferred)),
                                  float(D(w.placed_norm) + D(w.placed_over))])
            r += 1

        ws = wb.create_sheet("Результаты наблюдений")
        xlsx.header_row(ws, 1, ["Точка контроля", "Показатель", "План (изм./год)",
                                "Факт", "Превышение"], widths=[24, 22, 16, 12, 12])
        r = 2
        for rr in pek.get("results", []):
            xlsx.data_row(ws, r, [rr.get("point", ""), rr.get("substance", ""),
                                  rr.get("plan", ""), rr.get("fact", ""),
                                  "да" if rr.get("exceed") else "нет"])
            r += 1

        return xlsx.save(wb, out_path)


def _tot(p) -> Decimal:
    return D(p.mass_norm) + D(p.mass_limit) + D(p.mass_over)
