"""Форма 4-ООС «Сведения о текущих затратах на охрану окружающей среды».

Статистическая форма Росстата: годовая, сдают юрлица, у которых есть затраты
на охрану среды и экологические платежи. В отличие от остальных форм, данные
здесь **денежные** — программа берёт их из `ctx.extra['oos4']` (заполняется
экологом или извлекается из бухгалтерских справок) и **сама считает** плату
за НВОС по уже имеющемуся расчёту декларации.

Структура (по бланку): титул + раздел 1 «Затраты на охрану окружающей среды»
по направлениям + раздел 2 «Плата за негативное воздействие».
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import Issue
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.reports.base import Report

# направления затрат раздела 1 (строки бланка)
LINES = [
    ("101", "Затраты на охрану атмосферного воздуха и предотвращение "
            "изменения климата", "air"),
    ("102", "Затраты на сбор и очистку сточных вод", "water"),
    ("103", "Затраты на обращение с отходами", "waste"),
    ("104", "Затраты на защиту и реабилитацию земель, поверхностных и "
            "подземных вод", "land"),
    ("105", "Затраты на сохранение биоразнообразия и охрану природных "
            "территорий", "bio"),
    ("106", "Затраты на прочие направления деятельности", "other"),
]


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except Exception:
        return Decimal("0")


@register
class OOS4(Report):
    code = "4-oos"
    title = "4-ООС — текущие затраты на охрану окружающей среды"
    domain = "reporting"
    has_xml = False          # сдаётся через систему сбора Росстата (ЭВФ)

    # ── данные ────────────────────────────────────────────────────────
    @property
    def data(self) -> dict:
        return (self.ctx.extra or {}).get("oos4", {}) or {}

    def costs(self) -> list[tuple]:
        """(код строки, название, сумма) по направлениям затрат."""
        src = self.data.get("costs", {}) or {}
        return [(code, name, _dec(src.get(key))) for code, name, key in LINES]

    def payment(self) -> Decimal:
        """Плата за НВОС за год: из расчёта декларации, иначе из extra."""
        try:
            from ecodoc.reports.declaration_nvos.calc import calculate
            value = getattr(calculate(self.ctx), "total", None)
            if value:
                return Decimal(str(value))
        except Exception:
            pass
        return _dec(self.data.get("payment"))

    # ── проверки ──────────────────────────────────────────────────────
    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        org = self.ctx.organization
        if not org.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not org.okpo:
            issues.append(Issue("warning", "ОКПО",
                                "для статистической формы нужен код ОКПО"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "period.year", "не указан отчётный год"))
        total = sum(v for _c, _n, v in self.costs())
        if not total:
            issues.append(Issue(
                "warning", "extra.oos4.costs",
                "не заданы текущие затраты на охрану окружающей среды — "
                "заполните extra.oos4.costs (по направлениям: air, water, waste, "
                "land, bio, other) из данных бухгалтерии"))
        if not self.payment():
            issues.append(Issue("warning", "плата",
                                "плата за НВОС равна нулю — проверьте раздел "
                                "«Декларация» или задайте extra.oos4.payment"))
        return issues

    def render_xml(self, out_path: Path) -> Path:
        # 4-ООС сдаётся через систему сбора Росстата (электронная версия формы),
        # отдельного XML-конверта у неё нет — печатная форма и есть результат
        raise NotImplementedError(
            "4-ООС не выгружается в XML: форма сдаётся через систему сбора "
            "отчётности Росстата, используйте печатную форму")

    # ── печать ────────────────────────────────────────────────────────
    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        org, per = self.ctx.organization, self.ctx.period
        wb = xlsx.new_workbook()

        ws = wb.create_sheet("Титул")
        xlsx.merge(ws, "A1:E1", "ФОРМА 4-ООС", bold=True, align="center")
        xlsx.merge(ws, "A2:E2", "Сведения о текущих затратах на охрану "
                                "окружающей среды", align="center")
        xlsx.merge(ws, "A3:E3", f"за {per.year or '____'} год", align="center")
        info = [("Наименование отчитывающейся организации",
                 org.name or org.short_name),
                ("ИНН", org.inn), ("ОКПО", org.okpo), ("ОКТМО", org.oktmo),
                ("Почтовый адрес", org.address),
                ("Должностное лицо", org.director_name)]
        for i, (label, value) in enumerate(info, start=5):
            xlsx.cell(ws, f"A{i}", label, bold=True)
            xlsx.merge(ws, f"B{i}:E{i}", value or "—", align="left")
        xlsx.widths(ws, {"A": 44, "B": 26, "C": 18, "D": 18, "E": 18})

        ws1 = wb.create_sheet("Раздел 1")
        xlsx.merge(ws1, "A1:C1",
                   "Раздел 1. Текущие затраты на охрану окружающей среды, "
                   "тыс. рублей", bold=True, align="left")
        xlsx.header_row(ws1, 2, ["№ строки", "Направление затрат", "Сумма, тыс. руб."])
        xlsx.widths(ws1, {"A": 10, "B": 70, "C": 18})
        row = 3
        for code, name, value in self.costs():
            xlsx.data_row(ws1, row, [code, name, float(value) or None])
            row += 1
        xlsx.cell(ws1, f"B{row}", "ИТОГО (строка 100)", bold=True)
        xlsx.cell(ws1, f"C{row}",
                  float(sum(v for _c, _n, v in self.costs())) or None, bold=True)

        ws2 = wb.create_sheet("Раздел 2")
        xlsx.merge(ws2, "A1:C1", "Раздел 2. Плата за негативное воздействие на "
                                 "окружающую среду, тыс. рублей",
                   bold=True, align="left")
        xlsx.header_row(ws2, 2, ["№ строки", "Показатель", "Сумма, тыс. руб."])
        xlsx.widths(ws2, {"A": 10, "B": 70, "C": 18})
        payment = self.payment() / 1000          # плата считается в рублях
        xlsx.data_row(ws2, 3, ["201", "Плата за негативное воздействие на "
                                      "окружающую среду — всего",
                               float(round(payment, 3)) or None])
        xlsx.data_row(ws2, 4, ["202", "в том числе за размещение отходов",
                               float(_dec(self.data.get("payment_waste")) / 1000) or None])
        return xlsx.save(wb, out_path)
