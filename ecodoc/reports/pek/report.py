"""Отчёт об организации и о результатах осуществления ПЭК.

ДЕЙСТВУЮЩАЯ форма — Приказ Минприроды России от 15.03.2024 № 173 (в ред.
Приказа № 262 от 12.05.2025, действует с 01.09.2024). Требования к программе
ПЭК и сроки представления отчёта (до 25 марта, электронно с УКЭП через ЛК
природопользователя) — Приказ Минприроды России от 18.02.2022 № 109.
Прежняя форма (Приказ № 261 от 14.06.2018) утратила силу с 01.09.2024.

Печатная форма собирается по разделам и таблицам приказа: раздел 2 — таблицы
2.1 (перечень контролируемых веществ), 2.2 (контроль стационарных источников,
по источникам, с граф г/с и т/год) и 2.3 (наблюдения в СЗЗ); раздел 3 —
таблицы 3.1 (объёмы забора и сброса) и 3.2 (качество сточных вод); далее
разделы 4–6. XML самоописательный: официальной XSD у формы нет, отчёт
подаётся через ЛК РПН заполнением или прикреплением печатной формы.

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
        # категорию пишут как «III», «3», «III категория» — сравнение сырых
        # строк не срабатывало, и предупреждение не показывалось никогда
        from ecodoc.calendar.engine import category_of
        cats = {category_of(ob) for ob in self.ctx.objects}
        cats.discard("")
        if cats and cats == {"IV"}:
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
            x = el(air, "Вещество", код=_code(p.code))
            el(x, "Наименование", p.name)
            el(x, "МассаВсего", _tot(p))
        water = el(root, "Сбросы")
        for p in (x for x in self.ctx.pollutants if x.medium == Medium.WATER):
            x = el(water, "Вещество", код=_code(p.code))
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
        # титул бланка: гриф приложения, утверждающая подпись руководителя,
        # затем наименование отчёта и период. Сведения о программе ПЭК и
        # лаборатории — это раздел 1 формы, на титуле их нет.
        obj = ", ".join(x.code for x in self.ctx.objects) or "—"
        rows = [
            ("Приложение к приказу Минприроды России от 15.03.2024 № 173", ""),
            ("(в действующей редакции)", ""),
            ("Экз. №", pek.get("copy_no", "1")),
            ("", ""),
            ("УТВЕРЖДАЮ", ""),
            (f"{o.director_position or 'Руководитель'} "
             f"{o.short_name or o.name}", ""),
            ("_______________ / " + (o.director_name or "___________________"), ""),
            ("«____» __________ 20___ г.                                М.П.", ""),
            ("", ""),
            ("ОТЧЁТ", ""),
            ("об организации и о результатах осуществления производственного "
             "экологического контроля", ""),
            (f"объект НВОС: {obj}", ""),
            (f"за {self.ctx.period.year or '____'} год", ""),
            ("", ""),
            ("Наименование юридического лица / ИП", o.name),
            ("Место нахождения", o.address),
            ("Телефон / e-mail", f"{o.phone or '—'} / {o.email or '—'}"),
        ]
        for i, (k, v) in enumerate(rows, 1):
            a = ws.cell(row=i, column=1, value=k)
            ws.cell(row=i, column=2, value=v)
            if k in ("ОТЧЁТ", "УТВЕРЖДАЮ") or i == 11:
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
        """Раздел 2 формы: таблицы 2.1 (перечень ЗВ) и 2.2 (контроль источников).

        Таблица 2.2 в бланке — по ИСТОЧНИКАМ, с граф «г/с» и «т/год» и
        нормативом на источнике. Данные для неё уже есть в базе
        (extra.emission_sources), раньше форма их не использовала и печатала
        только сводный перечень веществ."""
        ws = wb.create_sheet("Раздел 2 (воздух)")
        pek = self._pek()
        xlsx.widths(ws, {"A": 8, "B": 26, "C": 10, "D": 26, "E": 10, "F": 30,
                         "G": 12, "H": 12, "I": 12, "J": 12, "K": 14, "L": 22})
        xlsx.merge(ws, "A1:L1", "Раздел 2. Сведения о ПЭК в области охраны "
                   "атмосферного воздуха", bold=True, border=False)

        # ── 2.1 перечень контролируемых веществ ──────────────────────
        xlsx.merge(ws, "A3:F3", "Таблица 2.1. Перечень загрязняющих веществ, "
                   "подлежащих контролю", bold=True, border=False)
        xlsx.header_row(ws, 4, ["№", "Код ЗВ", "Загрязняющее вещество",
                                "Норматив (ПДВ/ВСВ), т/год",
                                "Фактический выброс, т/год", "Периодичность"])
        r = 5
        period = pek.get("air_period") or "по программе ПЭК"
        for n, p in enumerate((x for x in self.ctx.pollutants
                               if x.medium == Medium.AIR), 1):
            xlsx.data_row(ws, r, [n, _code(p.code), p.name,
                                  float(D(p.mass_norm) + D(p.mass_limit)),
                                  float(_tot(p)), period])
            r += 1
        if r == 5:
            xlsx.cell(ws, f"A{r}", "— выбросы отсутствуют", border=False,
                      italic=True, align="left")
            r += 1

        # ── 2.2 результаты контроля стационарных источников ──────────
        r += 1
        xlsx.merge(ws, f"A{r}:L{r}", "Таблица 2.2. Результаты контроля "
                   "стационарных источников выбросов", bold=True, border=False)
        r += 1
        xlsx.header_row(ws, r, [
            "№ п/п", "Структурное подразделение (площадка, цех)",
            "Номер источника", "Наименование источника", "Код ЗВ",
            "Наименование ЗВ", "Норматив, г/с", "Факт, г/с",
            "Норматив, т/год", "Факт, т/год", "Дата отбора",
            "Протокол / лаборатория"])
        r += 1
        n = 0
        for src in (self.ctx.extra or {}).get("emission_sources", []) or []:
            if not isinstance(src, dict):
                continue
            for sub in src.get("pollutants") or []:
                n += 1
                xlsx.data_row(ws, r, [
                    n, src.get("workshop", ""), src.get("number", ""),
                    src.get("name", ""), _code(sub.get("code")),
                    sub.get("name", ""), sub.get("g_s_norm", ""),
                    sub.get("g_s", ""), sub.get("t_year_norm", ""),
                    sub.get("t_year", ""), sub.get("date", ""),
                    sub.get("protocol", pek.get("lab", ""))])
                r += 1
        if n == 0:
            xlsx.cell(ws, f"A{r}", "— источники выбросов не заведены: "
                      "загрузите инвентаризацию выбросов во вкладке ВЫБРОСЫ",
                      border=False, italic=True, align="left")
            r += 1

        # ── 2.3 наблюдения на границе СЗЗ / в жилой зоне ─────────────
        r += 1
        xlsx.merge(ws, f"A{r}:L{r}", "Таблица 2.3. Результаты наблюдений за "
                   "загрязнением атмосферного воздуха (СЗЗ, жилая зона)",
                   bold=True, border=False)
        r += 1
        self._results_table(ws, r, pek.get("results", []))

    def _sect3_water(self, wb):
        """Раздел 3 формы: 3.1 объёмы забора/сброса, 3.2 качество сточных вод."""
        ws = wb.create_sheet("Раздел 3 (вода)")
        pek = self._pek()
        water = (self.ctx.extra or {}).get("water") or {}
        xlsx.widths(ws, {"A": 8, "B": 34, "C": 22, "D": 18, "E": 18, "F": 18,
                         "G": 18, "H": 22})
        xlsx.merge(ws, "A1:H1", "Раздел 3. Сведения о ПЭК в области охраны и "
                   "использования водных объектов", bold=True, border=False)

        # ── 3.1 учёт объёмов забора и сброса ─────────────────────────
        xlsx.merge(ws, "A3:H3", "Таблица 3.1. Результаты учёта объёма забора "
                   "(изъятия) водных ресурсов и объёма сброса сточных вод",
                   bold=True, border=False)
        xlsx.header_row(ws, 4, ["№", "Водный объект / приёмник",
                                "Вид (забор / сброс)", "Номер выпуска",
                                "Объём за год, тыс. м³", "Средство измерения",
                                "Периодичность учёта", "Примечание"])
        r, n = 5, 0
        for kind, key in (("забор", "intake"), ("сброс", "discharge")):
            for item in water.get(key) or []:
                if not isinstance(item, dict):
                    continue
                n += 1
                xlsx.data_row(ws, r, [
                    n, item.get("name") or item.get("receiver", ""), kind,
                    item.get("outlet", ""), item.get("volume", ""),
                    item.get("meter", ""), item.get("period", ""),
                    item.get("quality", "")])
                r += 1
        if n == 0:
            xlsx.cell(ws, f"A{r}", "— водопользование не заведено (вкладка СБРОСЫ)",
                      border=False, italic=True, align="left")
            r += 1

        # ── 3.2 качество сточных вод по веществам ────────────────────
        r += 1
        xlsx.merge(ws, f"A{r}:H{r}", "Таблица 3.2. Результаты контроля качества "
                   "сточных вод", bold=True, border=False)
        r += 1
        xlsx.header_row(ws, r, ["№", "Код ЗВ", "Загрязняющее вещество",
                                "Норматив (НДС/ВСС), т/год", "Факт, т/год",
                                "Концентрация, мг/дм³", "Дата отбора",
                                "Протокол / лаборатория"])
        r += 1
        n = 0
        for p in (x for x in self.ctx.pollutants if x.medium == Medium.WATER):
            n += 1
            xlsx.data_row(ws, r, [n, _code(p.code), p.name,
                                  float(D(p.mass_norm) + D(p.mass_limit)),
                                  float(_tot(p)), "", "", pek.get("lab", "")])
            r += 1
        if n == 0:
            xlsx.cell(ws, f"A{r}", "— сбросы загрязняющих веществ не заведены",
                      border=False, italic=True, align="left")

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


def _code(value) -> str:
    """Код ЗВ в официальном виде: четыре цифры с ведущим нулём."""
    from ecodoc.core import sanitize
    return sanitize.norm_code(value) or str(value or "")


def _tot(p) -> Decimal:
    return D(p.mass_norm) + D(p.mass_limit) + D(p.mass_over)
