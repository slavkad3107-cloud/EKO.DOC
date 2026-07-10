"""Декларация о плате за НВОС (XML + Excel).

Форма — Приказ Минприроды России от 10.12.2020 № 1043 (в ред. Приказа № 241
от 29.04.2025, действует с 01.09.2025). Срок — до 10 марта года, следующего
за отчётным.

ВНИМАНИЕ: действующая редакция содержит 9 разделов расчёта (Р1 выбросы
стационарными; Р2/Р3 сжигание/рассеивание ПНГ на факелах в пределах/сверх
лимита; Р4 сбросы; Р5 отходы производства; Р6 ТКО; Р7 побочные продукты
производства; Р8 вскрышные/вмещающие горные породы; Р9 побочные продукты
животноводства). Текущий генератор строит только 3 (выбросы/сбросы/отходы) —
для полных деклараций с ТКО, ПНГ, побочными продуктами требуется расширение
разделов и потоков платы в calc.py. Коды строк 010–100 листа «стр.2» и точный
состав итогового раздела следует сверить с бланком (Приложение 2 к Приказу
№ 1043 в ред. № 241).
"""
from __future__ import annotations

from pathlib import Path

from ecodoc.core.models import Issue, Medium, ReportContext
from ecodoc.core.money import fmt_money
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report
from ecodoc.reports.declaration_nvos.calc import SECTIONS, PaymentResult, calculate

from lxml import etree

_BAND_RU = {"norm": "в пределах норматива", "limit": "в пределах лимита",
            "over": "сверх лимита/норматива"}

# КБК платы за НВОС (администратор 048 — Росприроднадзор), проверены на 2025
_KBK_AIR = "048 1 12 01010 01 6000 120"    # выбросы стационарными объектами
_KBK_PNG = "048 1 12 01070 01 6000 120"    # выбросы при сжигании/рассеивании ПНГ
_KBK_WATER = "048 1 12 01030 01 6000 120"  # сбросы в водные объекты
_KBK_WASTE = "048 1 12 01041 01 6000 120"  # размещение отходов производства (кроме ТКО)
_KBK_TKO = "048 1 12 01042 01 6000 120"    # размещение ТКО

# КБК по разделу декларации. Р7–Р9 (побочные продукты, породы, животноводство)
# редки; КБК уточняйте по действующему перечню — для Р7/Р8 обычно КБК отходов.
_KBK_BY_SECTION = {
    "Р1": _KBK_AIR, "Р2": _KBK_PNG, "Р3": _KBK_PNG, "Р4": _KBK_WATER,
    "Р5": _KBK_WASTE, "Р6": _KBK_TKO, "Р7": _KBK_WASTE, "Р8": _KBK_WASTE, "Р9": "",
}


@register
class DeclarationNVOS(Report):
    code = "declaration-nvos"
    title = "Декларация о плате за НВОС"

    def __init__(self, context: ReportContext):
        super().__init__(context)
        self._calc: PaymentResult | None = None

    @property
    def calc(self) -> PaymentResult:
        if self._calc is None:
            self._calc = calculate(self.ctx)
        return self._calc

    # ------------------------------------------------------------------ #
    def validate(self) -> list[Issue]:
        from ecodoc.core.validators import inn_valid, ogrn_valid
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН плательщика"))
        elif not inn_valid(o.inn):
            issues.append(Issue("error", "ИНН",
                                f"ИНН {o.inn} не проходит проверку контрольной "
                                f"суммы — вероятна опечатка"))
        if o.ogrn and not ogrn_valid(o.ogrn):
            issues.append(Issue("warning", "ОГРН",
                                f"ОГРН {o.ogrn} не проходит проверку — сверьте"))
        if not o.name:
            issues.append(Issue("error", "наименование", "не указано наименование организации"))
        if not o.oktmo:
            issues.append(Issue("warning", "ОКТМО", "не указан ОКТМО — обязателен для распределения платы"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.objects:
            issues.append(Issue("warning", "объекты", "не указан ни один объект НВОС"))
        if not (self.ctx.pollutants or self.ctx.wastes):
            issues.append(Issue("error", "данные", "нет ни выбросов/сбросов, ни отходов — нечего декларировать"))
        for w in self.calc.warnings:
            issues.append(Issue("warning", "ставка", w))
        return issues

    # ------------------------------------------------------------------ #
    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        per = self.ctx.period
        c = self.calc

        root = etree.Element("ДекларацияНВОС", version="0.1", форма=self.code)
        # ── плательщик ──
        plat = el(root, "Плательщик")
        el(plat, "Наименование", o.name)
        el(plat, "ИНН", o.inn)
        el(plat, "КПП", o.kpp)
        el(plat, "ОГРН", o.ogrn)
        el(plat, "ОКТМО", o.oktmo)
        el(plat, "Адрес", o.address)
        el(plat, "Руководитель", o.director_name)
        el(root, "ОтчётныйГод", per.year)

        # ── объекты ──
        objs = el(root, "ОбъектыНВОС")
        for ob in self.ctx.objects:
            x = el(objs, "Объект")
            el(x, "Код", ob.code)
            el(x, "Наименование", ob.name)
            el(x, "Категория", ob.category)
            el(x, "ОКТМО", ob.oktmo or o.oktmo)

        # ── строки расчёта ──
        lines_el = el(root, "СтрокиРасчёта")
        for ln in c.lines:
            x = el(lines_el, "Строка", среда=ln.medium, норматив=ln.band,
                   раздел=ln.section)
            el(x, "Код", ln.code)
            el(x, "Наименование", ln.name)
            el(x, "Масса", ln.mass)
            el(x, "Ставка", ln.rate)
            el(x, "КоэффИндексации", ln.k_ind)
            el(x, "КоэффНорматива", ln.k_band)
            el(x, "КоэффДоп", ln.k_extra)
            el(x, "Плата", ln.amount)

        # ── итоги ──
        tot = el(root, "Итоги")
        for key in ("Р1", "Р2", "Р3", "Р4", "Р5", "Р6", "Р7", "Р8", "Р9"):
            el(tot, "Раздел", c.by_section.get(key, 0), код=key, наим=SECTIONS[key])
        el(tot, "ПлатаВыбросы", c.total_air)
        el(tot, "ПлатаСбросы", c.total_water)
        el(tot, "ПлатаОтходы", c.total_waste)
        el(tot, "ПлатаВсего", c.total)

        write_tree(root, out_path)
        return out_path

    # ------------------------------------------------------------------ #
    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        self._sheet_title(wb)          # стр.1 — титульный лист
        self._sheet_calc(wb)           # стр.2 — расчёт суммы платы по разделам
        self._sheet_lines(wb, "Разделы 1-3 (выбросы)", Medium.AIR.value)
        self._sheet_lines(wb, "Раздел 4 (сбросы)", Medium.WATER.value)
        self._sheet_lines(wb, "Разделы 5-9 (отходы)", "waste")
        xlsx.save(wb, out_path)
        return out_path

    # стр.1 — титульный лист официального бланка -----------------------
    def _sheet_title(self, wb):
        o = self.ctx.organization
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        year = self.ctx.period.year or ""
        ws = wb.create_sheet("стр.1")
        xlsx.widths(ws, {"A": 4, "B": 40, "C": 52})
        xlsx.merge(ws, "B1:C1",
                   "ДЕКЛАРАЦИЯ О ПЛАТЕ ЗА НЕГАТИВНОЕ ВОЗДЕЙСТВИЕ НА ОКРУЖАЮЩУЮ СРЕДУ",
                   bold=True, border=False)
        xlsx.merge(ws, "B2:C2", f"за {year} год", border=False, bold=True)
        rows = [
            ("1", "Вид документа (первичный «0» / уточнённый)",
             e.get("doc_kind", "первичный")),
            ("2", "Декларация представляется в территориальный орган Росприроднадзора",
             e.get("rospr", "")),
            ("3", "Организационно-правовая форма и полное наименование ЮЛ", o.name),
            ("4", "Сокращённое наименование", o.short_name or o.name),
            ("5", "Адрес ЮЛ/ИП", o.address),
            ("6", "Код города и номер контактного телефона", o.phone),
            ("7", "ИНН", o.inn),
            ("8", "КПП", o.kpp),
            ("9", "ОГРН", o.ogrn),
            ("10", "Руководитель ЮЛ / уполномоченное лицо / ИП",
             f"{o.director_position} {o.director_name}".strip()),
        ]
        r = 4
        for num, label, value in rows:
            xlsx.cell(ws, f"A{r}", num)
            xlsx.cell(ws, f"B{r}", label, align="left")
            xlsx.cell(ws, f"C{r}", value or "", align="left")
            r += 1
        r += 1
        xlsx.cell(ws, f"B{r}", "Достоверность и полноту сведений подтверждаю.",
                  border=False, align="left")
        xlsx.cell(ws, f"B{r+2}", "Дата: «____» __________ 20___ г.",
                  border=False, align="left")

    # стр.2 — расчёт суммы платы по 9 разделам (Приказ №1043 ред. №241) ----
    def _sheet_calc(self, wb):
        o = self.ctx.organization
        c = self.calc
        ws = wb.create_sheet("стр.2")
        xlsx.widths(ws, {"A": 6, "B": 52, "C": 24, "D": 18})
        xlsx.merge(ws, "A1:D1",
                   "Расчёт суммы платы, подлежащей внесению в бюджет "
                   "(по разделам формы, Приказ Минприроды № 1043 в ред. № 241)",
                   bold=True, border=False)
        xlsx.cell(ws, "A2", "Код по ОКТМО объекта НВОС:", border=False, align="left")
        xlsx.cell(ws, "B2", o.oktmo or "", border=False, bold=True, align="left")
        xlsx.cell(ws, "A4", "Раздел", bold=True, fill=True)
        xlsx.cell(ws, "B4", "Вид платы", bold=True, fill=True, align="left")
        xlsx.cell(ws, "C4", "КБК", bold=True, fill=True)
        xlsx.cell(ws, "D4", "Сумма, руб.", bold=True, fill=True)
        r = 5
        for key in ("Р1", "Р2", "Р3", "Р4", "Р5", "Р6", "Р7", "Р8", "Р9"):
            amount = c.by_section.get(key, 0)
            xlsx.cell(ws, f"A{r}", key)
            xlsx.cell(ws, f"B{r}", SECTIONS[key], align="left")
            xlsx.cell(ws, f"C{r}", _KBK_BY_SECTION.get(key, "") or "—")
            xlsx.cell(ws, f"D{r}", fmt_money(amount))
            r += 1
        xlsx.cell(ws, f"B{r}", "ИТОГО плата, подлежащая внесению", bold=True, align="left")
        xlsx.cell(ws, f"D{r}", fmt_money(c.total), bold=True)
        r += 2
        xlsx.cell(ws, f"A{r}", "Разделы 2–3 — ПНГ (флаг is_flare у вещества); Р6 — ТКО "
                  "(ФККО «7 3…» или waste_kind=tko); Р7–Р9 (побочные продукты, породы, "
                  "животноводство) — по waste_kind. Точные коды строк итогового раздела "
                  "сверьте с бланком (Приложение 2 к Приказу № 1043 в ред. № 241).",
                  border=False, italic=True, size=9, align="left")

    # ----- листы Excel -----
    def _sheet_lines(self, wb, title: str, medium: str):
        c = self.calc
        rows = [ln for ln in c.lines if ln.medium == medium]
        ws = wb.create_sheet(title)
        headers = ["Раздел", "Код", "Наименование", "Норматив", "Масса, т",
                   "Ставка, руб.", "Кинд", "Кнорм", "Кдоп", "Плата, руб."]
        xlsx.header_row(ws, 1, headers,
                        widths=[8, 12, 32, 22, 12, 14, 8, 8, 8, 16])
        r = 2
        for ln in rows:
            xlsx.data_row(ws, r, [
                ln.section, ln.code, ln.name, _BAND_RU.get(ln.band, ln.band),
                float(ln.mass), float(ln.rate), float(ln.k_ind),
                float(ln.k_band), float(ln.k_extra), fmt_money(ln.amount)])
            r += 1
        # итог по листу
        total = sum((ln.amount for ln in rows), start=type(rows[0].amount)(0)) if rows else 0
        tcell = ws.cell(row=r, column=9, value="ИТОГО:")
        tcell.font = xlsx.BOLD
        v = ws.cell(row=r, column=10, value=fmt_money(total))
        v.font = xlsx.BOLD
