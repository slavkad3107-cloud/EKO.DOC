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

    # стр.2 — расчёт суммы платы, официальные коды строк 010–120 -------
    # (сверено с реальной сданной декларацией, Приложение 2 к Приказу № 1043)
    def _sheet_calc(self, wb):
        from decimal import Decimal
        from ecodoc.core.money import D
        o = self.ctx.organization
        c = self.calc
        bs = c.by_section
        # суммы по (раздел, корзина) для строк 041/042/043 и т.п.
        sb: dict = {}
        for ln in c.lines:
            sb[(ln.section, ln.band)] = sb.get((ln.section, ln.band), Decimal("0")) + D(ln.amount)

        def band(sect, b):
            return fmt_money(sb.get((sect, b), Decimal("0")))

        ws = wb.create_sheet("стр.2")
        xlsx.widths(ws, {"A": 10, "B": 60, "C": 26, "D": 18})
        xlsx.merge(ws, "A1:D1", "Расчёт суммы платы, подлежащей внесению в бюджет "
                   "(Приложение 2 к Приказу Минприроды № 1043 в ред. № 241)",
                   bold=True, border=False)
        xlsx.cell(ws, "A3", "Код строки", bold=True, fill=True)
        xlsx.cell(ws, "B3", "Показатели", bold=True, fill=True, align="left")
        xlsx.cell(ws, "C3", "КБК / ОКТМО", bold=True, fill=True)
        xlsx.cell(ws, "D3", "Сумма, руб.", bold=True, fill=True)
        png = fmt_money(D(bs.get("Р2", 0)) + D(bs.get("Р3", 0)))
        # (код, показатель, значение-в-C (КБК/ОКТМО), значение-в-D (сумма))
        rows = [
            ("010", "Код по ОКТМО объекта НВОС", o.oktmo or "", None),
            ("020", "Сумма платы, всего (020 = 021+022+023+024+025)", "", fmt_money(c.total)),
            ("021", "  плата за выбросы стационарными источниками (040)", "", fmt_money(bs.get("Р1", 0))),
            ("022", "  плата за выбросы ПНГ (060)", "", png),
            ("023", "  плата за сбросы (080)", "", fmt_money(bs.get("Р4", 0))),
            ("024", "  плата за размещение отходов производства (100)", "", fmt_money(bs.get("Р5", 0))),
            ("025", "  плата за размещение ТКО (120)", "", fmt_money(bs.get("Р6", 0))),
            ("030", "КБК: плата за выбросы", _KBK_AIR, None),
            ("040", "Сумма платы за выбросы, всего (040 = 041+042+043)", "", fmt_money(bs.get("Р1", 0))),
            ("041", "  в пределах НДВ, ТН", "", band("Р1", "norm")),
            ("042", "  в пределах ВРВ", "", band("Р1", "limit")),
            ("043", "  сверх НДВ, ТН, ВРВ", "", band("Р1", "over")),
            ("050", "КБК: плата за выбросы ПНГ", _KBK_PNG, None),
            ("060", "Сумма платы за выбросы ПНГ, всего", "", png),
            ("070", "КБК: плата за сбросы", _KBK_WATER, None),
            ("080", "Сумма платы за сбросы, всего (080 = 081+082+083)", "", fmt_money(bs.get("Р4", 0))),
            ("081", "  в пределах НДС, ТН", "", band("Р4", "norm")),
            ("082", "  в пределах ВРС", "", band("Р4", "limit")),
            ("083", "  сверх НДС, ТН, ВРС", "", band("Р4", "over")),
            ("090", "КБК: плата за размещение отходов производства", _KBK_WASTE, None),
            ("100", "Сумма платы за размещение отходов производства", "", fmt_money(bs.get("Р5", 0))),
            ("101", "  в пределах лимита", "", band("Р5", "norm")),
            ("102", "  сверх лимита", "", band("Р5", "over")),
            ("110", "КБК: плата за размещение ТКО", _KBK_TKO, None),
            ("120", "Сумма платы за размещение ТКО, всего", "", fmt_money(bs.get("Р6", 0))),
        ]
        r = 4
        for code, label, c_val, d_val in rows:
            bold = code in ("010", "020")
            xlsx.cell(ws, f"A{r}", code, bold=bold)
            xlsx.cell(ws, f"B{r}", label, align="left", bold=bold)
            xlsx.cell(ws, f"C{r}", c_val)
            xlsx.cell(ws, f"D{r}", d_val if d_val is not None else "", bold=bold)
            r += 1
        extra = D(bs.get("Р7", 0)) + D(bs.get("Р8", 0)) + D(bs.get("Р9", 0))
        if extra > 0:
            xlsx.cell(ws, f"B{r}", "Плата за размещение побочных продуктов производства / "
                      "вскрышных пород / побочных продуктов животноводства (Разделы 7–9)",
                      border=False, align="left")
            xlsx.cell(ws, f"D{r}", fmt_money(extra))
            r += 1
        xlsx.cell(ws, f"A{r+1}", "Разделы 2–3 (ПНГ) — по флагу is_flare; строка 025/120 — ТКО "
                  "(ФККО «7 3…»). Сверено с реальной сданной декларацией.",
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
