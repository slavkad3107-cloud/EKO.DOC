"""Декларация о плате за НВОС — полная реализация (XML + Excel)."""
from __future__ import annotations

from pathlib import Path

from ecodoc.core.models import Issue, Medium, ReportContext
from ecodoc.core.money import fmt_money
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report
from ecodoc.reports.declaration_nvos.calc import PaymentResult, calculate

from lxml import etree

_BAND_RU = {"norm": "в пределах норматива", "limit": "в пределах лимита",
            "over": "сверх лимита/норматива"}

# КБК платы за НВОС (администратор 048 — Росприроднадзор)
_KBK_AIR = "048 1 12 01010 01 6000 120"    # выбросы стационарными объектами
_KBK_PNG = "048 1 12 01070 01 6000 120"    # выбросы при сжигании/рассеивании ПНГ
_KBK_WATER = "048 1 12 01030 01 6000 120"  # сбросы в водные объекты
_KBK_WASTE = "048 1 12 01041 01 6000 120"  # размещение отходов (кроме ТКО)


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
            x = el(lines_el, "Строка", среда=ln.medium, норматив=ln.band)
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
        self._sheet_calc(wb)           # стр.2 — расчёт суммы платы (коды 010-100)
        self._sheet_lines(wb, "Раздел 1 (выбросы)", Medium.AIR.value)
        self._sheet_lines(wb, "Раздел 2 (сбросы)", Medium.WATER.value)
        self._sheet_lines(wb, "Раздел 3 (отходы)", "waste")
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

    # стр.2 — расчёт суммы платы (официальные коды строк) --------------
    def _sheet_calc(self, wb):
        o = self.ctx.organization
        c = self.calc
        ws = wb.create_sheet("стр.2")
        xlsx.widths(ws, {"A": 66, "B": 12, "C": 22})
        xlsx.merge(ws, "A1:C1",
                   "Расчёт суммы платы, подлежащей внесению в бюджет", bold=True, border=False)
        xlsx.cell(ws, "A2", "Показатели", bold=True, fill=True, align="left")
        xlsx.cell(ws, "B2", "Код строки", bold=True, fill=True)
        xlsx.cell(ws, "C2", "Значение", bold=True, fill=True)
        rows = [
            ("Код по ОКТМО объекта НВОС", "010", o.oktmo or ""),
            ("Сумма платы, всего (020 = 021 + 022 + 023 + 024), руб.", "020",
             fmt_money(c.total)),
            ("плата за выбросы ЗВ в атмосферу стационарными объектами", "021",
             fmt_money(c.total_air)),
            ("плата за выбросы при сжигании/рассеивании ПНГ", "022", fmt_money(0)),
            ("плата за сбросы ЗВ в водные объекты", "023", fmt_money(c.total_water)),
            ("плата за размещение отходов производства и потребления", "024",
             fmt_money(c.total_waste)),
            ("КБК платы за выбросы (стационарные)", "030", _KBK_AIR),
            ("Сумма платы за выбросы, всего", "040", fmt_money(c.total_air)),
            ("КБК платы за выбросы ПНГ", "050", _KBK_PNG),
            ("Сумма платы за выбросы ПНГ, всего", "060", fmt_money(0)),
            ("КБК платы за сбросы", "070", _KBK_WATER),
            ("Сумма платы за сбросы, всего", "080", fmt_money(c.total_water)),
            ("КБК платы за размещение отходов", "090", _KBK_WASTE),
            ("Сумма платы за размещение отходов, всего", "100", fmt_money(c.total_waste)),
        ]
        r = 3
        for label, code, value in rows:
            bold = code in ("020",)
            xlsx.cell(ws, f"A{r}", label, align="left", bold=bold)
            xlsx.cell(ws, f"B{r}", code, bold=bold)
            xlsx.cell(ws, f"C{r}", value, bold=bold)
            r += 1

    # ----- листы Excel -----
    def _sheet_lines(self, wb, title: str, medium: str):
        c = self.calc
        rows = [ln for ln in c.lines if ln.medium == medium]
        ws = wb.create_sheet(title)
        headers = ["Код", "Наименование", "Норматив", "Масса, т",
                   "Ставка, руб.", "Кинд", "Кнорм", "Кдоп", "Плата, руб."]
        xlsx.header_row(ws, 1, headers,
                        widths=[12, 34, 22, 12, 14, 8, 8, 8, 16])
        r = 2
        for ln in rows:
            xlsx.data_row(ws, r, [
                ln.code, ln.name, _BAND_RU.get(ln.band, ln.band),
                float(ln.mass), float(ln.rate), float(ln.k_ind),
                float(ln.k_band), float(ln.k_extra), fmt_money(ln.amount)])
            r += 1
        # итог по листу
        total = sum((ln.amount for ln in rows), start=type(rows[0].amount)(0)) if rows else 0
        tcell = ws.cell(row=r, column=8, value="ИТОГО:")
        tcell.font = xlsx.BOLD
        v = ws.cell(row=r, column=9, value=fmt_money(total))
        v.font = xlsx.BOLD
