"""Отчёт об организации и о результатах осуществления ПЭК.

ДЕЙСТВУЮЩАЯ форма — Приказ Минприроды России от 15.03.2024 № 173 (в ред.
Приказа № 262 от 12.05.2025, действует с 01.09.2024). Требования к программе
ПЭК и сроки представления отчёта (до 25 марта, электронно с УКЭП через ЛК
природопользователя) — Приказ Минприроды России от 18.02.2022 № 109.
Прежняя форма (Приказ № 261 от 14.06.2018) утратила силу с 01.09.2024.

ВНИМАНИЕ: текущий генератор строит упрощённую структуру (выбросы/сбросы/
отходы/результаты) и НЕ соответствует табличной структуре Приказа № 173 —
в частности, отсутствуют Раздел 5 (побочные продукты производства) и Раздел 6
(искусственные грунты из органической части ТКО, с отчёта за 2025 г.). XML
самоописательный, для официальной подачи через ЛК РПН не годится. Требуется
переработка под разделы и таблицы № 173.

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
    title = "Отчёт по ПЭК (форма — Приказ №173/2024, разделы 1–6)"

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

        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        ppp = el(root, "ПобочныеПродуктыПроизводства")  # Раздел 5
        for p in e.get("ppp", []):
            x = el(ppp, "ППП")
            el(x, "Наименование", p.get("name", ""))
            el(x, "Образовано", p.get("formed", ""))
            el(x, "Использовано", p.get("used", ""))
        soil = el(root, "ИскусственныеГрунтыТКО")  # Раздел 6 (с 2025)
        for s in e.get("artificial_soil", []):
            x = el(soil, "Грунт")
            el(x, "Наименование", s.get("name", ""))
            el(x, "Образовано", s.get("formed", ""))

        write_tree(root, out_path)
        return out_path

    # ------------------------------------------------------------------ #
    def render_print(self, out_path: Path) -> Path:
        """Печать по структуре Приказа Минприроды № 173 от 15.03.2024:
        Титул + Разделы 1-6 (общие сведения / воздух / вода / отходы /
        побочные продукты производства / искусственные грунты из ТКО)."""
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        self._title(wb)
        self._sect1(wb)
        self._sect2_air(wb)
        self._sect3_water(wb)
        self._sect4_waste(wb)
        self._sect5_ppp(wb)
        self._sect6_soil(wb)
        return xlsx.save(wb, out_path)

    def _title(self, wb):
        o = self.ctx.organization
        pek = self._pek()
        ws = wb.create_sheet("Титул")
        ws.column_dimensions["A"].width = 40
        ws.column_dimensions["B"].width = 56
        rows = [
            ("ОТЧЁТ ОБ ОРГАНИЗАЦИИ И О РЕЗУЛЬТАТАХ ОСУЩЕСТВЛЕНИЯ ПЭК", ""),
            ("(форма — Приказ Минприроды России от 15.03.2024 № 173, ред. № 262)", ""),
            ("Отчётный год", self.ctx.period.year),
            ("Организация", o.name),
            ("ИНН / КПП", f"{o.inn} / {o.kpp}"),
            ("Адрес", o.address),
            ("Программа ПЭК", f"№{pek.get('program_number','—')} от {pek.get('program_date','—')}"),
            ("Лаборатория (аттестат аккредитации)", pek.get("lab", "—")),
            ("Объекты НВОС", ", ".join(f"{x.code} ({x.category})" for x in self.ctx.objects)),
            ("Срок представления", "до 25 марта года, следующего за отчётным, "
                                   "электронно с УКЭП через ЛК природопользователя"),
        ]
        for i, (k, v) in enumerate(rows, 1):
            a = ws.cell(row=i, column=1, value=k)
            ws.cell(row=i, column=2, value=v)
            if i == 1:
                a.font = xlsx.BOLD

    def _sect1(self, wb):
        o = self.ctx.organization
        pek = self._pek()
        ws = wb.create_sheet("Раздел 1")
        xlsx.widths(ws, {"A": 6, "B": 44, "C": 14, "D": 10, "E": 40})
        xlsx.merge(ws, "A1:E1", "Раздел 1. Общие сведения об объекте и о применяемых "
                   "технологиях, лабораториях контроля", bold=True, border=False)
        xlsx.cell(ws, "A3", "№", bold=True, fill=True)
        xlsx.cell(ws, "B3", "Объект НВОС / наименование", bold=True, fill=True)
        xlsx.cell(ws, "C3", "Код объекта", bold=True, fill=True)
        xlsx.cell(ws, "D3", "Категория", bold=True, fill=True)
        xlsx.cell(ws, "E3", "Адрес / ОКТМО", bold=True, fill=True)
        r = 4
        for n, ob in enumerate(self.ctx.objects, 1):
            xlsx.cell(ws, f"A{r}", n)
            xlsx.cell(ws, f"B{r}", ob.name or o.name, align="left")
            xlsx.cell(ws, f"C{r}", ob.code)
            xlsx.cell(ws, f"D{r}", ob.category)
            xlsx.cell(ws, f"E{r}", f"{ob.address or ''} {ob.oktmo or ''}".strip(), align="left")
            r += 1
        r += 1
        xlsx.cell(ws, f"A{r}", "Лаборатория контроля (наименование, аттестат "
                  "аккредитации, область):", border=False, align="left")
        xlsx.cell(ws, f"B{r+1}", pek.get("lab", "—"), border=False, align="left")

    def _sect2_air(self, wb):
        ws = wb.create_sheet("Раздел 2 (воздух)")
        pek = self._pek()
        xlsx.widths(ws, {"A": 10, "B": 40, "C": 18, "D": 18})
        xlsx.merge(ws, "A1:D1", "Раздел 2. ПЭК в области охраны атмосферного воздуха "
                   "(контроль источников выбросов и наблюдения)", bold=True, border=False)
        xlsx.header_row(ws, 3, ["Код ЗВ", "Загрязняющее вещество",
                                "Масса выброса за год, т", "Норматив (ПДВ/ВСВ), т"])
        r = 4
        for p in (x for x in self.ctx.pollutants if x.medium == Medium.AIR):
            xlsx.data_row(ws, r, [p.code, p.name, float(_tot(p)),
                                  float(D(p.mass_norm) + D(p.mass_limit))])
            r += 1
        r += 1
        xlsx.cell(ws, f"A{r}", "Результаты контроля (замеры на источниках / "
                  "на границе СЗЗ):", border=False, bold=True, align="left")
        r += 1
        self._results_table(ws, r, pek.get("results", []))

    def _sect3_water(self, wb):
        ws = wb.create_sheet("Раздел 3 (вода)")
        pek = self._pek()
        xlsx.widths(ws, {"A": 10, "B": 40, "C": 18, "D": 18})
        xlsx.merge(ws, "A1:D1", "Раздел 3. ПЭК в области охраны водных объектов "
                   "(забор/сброс воды, качество вод)", bold=True, border=False)
        xlsx.header_row(ws, 3, ["Код ЗВ", "Загрязняющее вещество",
                                "Масса сброса за год, т", "Норматив (НДС/ВСС), т"])
        r = 4
        for p in (x for x in self.ctx.pollutants if x.medium == Medium.WATER):
            xlsx.data_row(ws, r, [p.code, p.name, float(_tot(p)),
                                  float(D(p.mass_norm) + D(p.mass_limit))])
            r += 1

    def _sect4_waste(self, wb):
        ws = wb.create_sheet("Раздел 4 (отходы)")
        xlsx.widths(ws, {"A": 14, "B": 34, "C": 6, **{c: 12 for c in "DEFGHIJ"}})
        xlsx.merge(ws, "A1:J1", "Раздел 4. ПЭК в области обращения с отходами "
                   "(движение отходов, контрагенты)", bold=True, border=False)
        xlsx.header_row(ws, 3, ["ФККО", "Наименование", "Кл.", "Нач. года, т",
                                "Образовано, т", "Утилизир., т", "Обезвр., т",
                                "Передано, т", "Размещено, т", "Кон. года, т"])
        r = 4
        for w in self.ctx.wastes:
            xlsx.data_row(ws, r, [w.fkko_code, w.name, w.hazard_class,
                                  float(D(w.accumulated_start)), float(D(w.generated)),
                                  float(D(w.used)), float(D(w.neutralized)),
                                  float(D(w.transferred)),
                                  float(D(w.placed_norm) + D(w.placed_over)),
                                  float(D(w.accumulated_end))])
            r += 1
        recv = self.ctx.extra.get("waste_receivers", []) if isinstance(self.ctx.extra, dict) else []
        if recv:
            r += 1
            xlsx.cell(ws, f"A{r}", "Контрагенты (кому переданы отходы):",
                      border=False, bold=True, align="left")
            r += 1
            xlsx.header_row(ws, r, ["ФККО", "Получатель", "ИНН", "Лицензия", "Операция"])
            r += 1
            for rc in recv:
                xlsx.data_row(ws, r, [rc.get("fkko", ""), rc.get("receiver", ""),
                                      rc.get("inn", ""), rc.get("license", ""),
                                      rc.get("operation", "")])
                r += 1

    def _sect5_ppp(self, wb):
        """Раздел 5 — обращение с побочными продуктами производства (с 01.09.2024)."""
        ws = wb.create_sheet("Раздел 5 (ППП)")
        xlsx.widths(ws, {"A": 6, "B": 40, "C": 16, "D": 20, "E": 20, "F": 24})
        xlsx.merge(ws, "A1:F1", "Раздел 5. ПЭК в области обращения с побочными "
                   "продуктами производства (ППП)", bold=True, border=False)
        xlsx.header_row(ws, 3, ["№", "Наименование ППП", "Объём образования, т",
                                "Использовано/реализовано, т", "Передано, т",
                                "Отнесено к отходам, т"])
        ppp = self.ctx.extra.get("ppp", []) if isinstance(self.ctx.extra, dict) else []
        r = 4
        if ppp:
            for n, p in enumerate(ppp, 1):
                xlsx.data_row(ws, r, [n, p.get("name", ""), p.get("formed", ""),
                                      p.get("used", ""), p.get("transferred", ""),
                                      p.get("to_waste", "")])
                r += 1
        else:
            xlsx.data_row(ws, r, ["-", "побочные продукты производства не образуются",
                                  "", "", "", ""])

    def _sect6_soil(self, wb):
        """Раздел 6 — искусственные грунты из органической части ТКО (с 01.09.2025)."""
        ws = wb.create_sheet("Раздел 6 (искусств. грунты)")
        xlsx.widths(ws, {"A": 6, "B": 40, "C": 20, "D": 24, "E": 24})
        xlsx.merge(ws, "A1:E1", "Раздел 6. ПЭК в области обращения с искусственными "
                   "грунтами из органической части ТКО (с отчёта за 2025 г.)",
                   bold=True, border=False)
        xlsx.header_row(ws, 3, ["№", "Наименование ИГ", "Объём образования, т",
                                "Использовано/передано, т", "Получатель (ИНН)"])
        soil = self.ctx.extra.get("artificial_soil", []) if isinstance(self.ctx.extra, dict) else []
        r = 4
        if soil and (self.ctx.period.year or 0) >= 2025:
            for n, s in enumerate(soil, 1):
                xlsx.data_row(ws, r, [n, s.get("name", ""), s.get("formed", ""),
                                      s.get("used", ""), s.get("receiver", "")])
                r += 1
        else:
            xlsx.data_row(ws, r, ["-", "искусственные грунты из органической части "
                                  "ТКО не производятся", "", "", ""])

    def _results_table(self, ws, r, results):
        xlsx.header_row(ws, r, ["Точка контроля", "Показатель", "План (изм./год)",
                                "Факт", "Превышение"])
        r += 1
        for rr in results:
            xlsx.data_row(ws, r, [rr.get("point", ""), rr.get("substance", ""),
                                  rr.get("plan", ""), rr.get("fact", ""),
                                  "да" if rr.get("exceed") else "нет"])
            r += 1


def _tot(p) -> Decimal:
    return D(p.mass_norm) + D(p.mass_limit) + D(p.mass_over)
