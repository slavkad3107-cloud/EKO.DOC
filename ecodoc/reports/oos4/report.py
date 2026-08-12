"""Форма № 4-ОС «Сведения о текущих затратах на охрану окружающей среды».

Статистическая форма Росстата (ОКУД 0609030, приказ Росстата от 22.07.2025
№ 346): годовая, сдаётся в территориальный орган Росстата. Данные здесь
**денежные** — программа берёт их из `ctx.extra['oos4']['costs']`, куда их
вносит эколог по данным бухгалтерии (вкладка «Отчётность» → «Общая»).

Структура бланка: одна таблица. Показатели — строки 01…10, где 01 —
контрольная сумма строк 02–10. Затраты разнесены по двум блокам граф:
«для собственных нужд» и «на оказание специализированных услуг
природоохранного назначения», в каждом — всего и в том числе по видам.

Платы за НВОС в действующей форме НЕТ: раздел о плате исключён, когда форма
была переименована из «4-ОС (затраты)» в нынешнюю редакцию. Поэтому здесь
плата не считается и не печатается — она в декларации.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import Issue
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.reports.base import Report

# Показатели формы: (код строки, наименование, ключ в extra.oos4.costs).
# Строка 01 — сумма строк 02–10, отдельного ключа не имеет.
LINES = [
    ("02", "охрана атмосферного воздуха и предотвращение изменения климата", "air"),
    ("03", "сбор и очистка сточных вод", "water"),
    ("04", "обращение с отходами", "waste"),
    ("05", "защита и реабилитация земель, поверхностных и подземных вод", "land"),
    ("06", "сохранение биоразнообразия и охрана природных территорий", "bio"),
    ("07", "борьба с шумом, вибрацией и другими видами физического воздействия",
     "noise"),
    ("08", "обеспечение радиационной безопасности окружающей среды", "radiation"),
    ("09", "научно-исследовательская деятельность и разработки по снижению "
           "негативного антропогенного воздействия", "science"),
    ("10", "другие направления деятельности в сфере охраны окружающей среды",
     "other"),
]

# Графы бланка: два блока — собственные нужды и специализированные услуги.
# В каждом блоке «всего» и расшифровка. Программа заполняет графы «всего»
# (гр. 3 и 11) из данных пользователя; остальные графы остаются пустыми —
# их эколог заполняет вручную, если ведёт такой учёт.
COLS_OWN = [
    ("3", "всего"),
    ("4", "в том числе на оплату услуг природоохранного назначения"),
    ("5", "из них сторонних организаций"),
    ("6", "затраты на капитальный ремонт основных фондов по охране "
          "окружающей среды"),
]
COLS_SERVICES = [
    ("11", "всего"),
    ("12", "в том числе оплата услуг сторонних организаций"),
]


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except Exception:
        return Decimal("0")


@register
class OOS4(Report):
    code = "4-oos"
    title = "4-ОС — сведения о текущих затратах на охрану окружающей среды"
    domain = "reporting"
    has_xml = False          # сдаётся через систему сбора Росстата (ЭВФ)

    # ── данные ────────────────────────────────────────────────────────
    @property
    def data(self) -> dict:
        return (self.ctx.extra or {}).get("oos4", {}) or {}

    def costs(self) -> list[tuple]:
        """(код строки, наименование, сумма) по направлениям затрат."""
        src = self.data.get("costs", {}) or {}
        return [(code, name, _dec(src.get(key))) for code, name, key in LINES]

    def total(self) -> Decimal:
        """Строка 01 — контрольная сумма строк 02–10."""
        return sum((v for _c, _n, v in self.costs()), Decimal("0"))

    def services(self) -> dict:
        """Затраты на оказание услуг природоохранного назначения (гр. 11)."""
        return self.data.get("services", {}) or {}

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
        if not self.total():
            issues.append(Issue(
                "warning", "затраты на ООС",
                "не заданы текущие затраты на охрану окружающей среды — "
                "заполните их во вкладке «Отчётность» → модуль «Общая» → "
                "«Программа ПЭК и затраты на ООС»"))
        return issues

    def render_xml(self, out_path: Path) -> Path:
        # 4-ОС сдаётся через систему сбора Росстата (электронная версия формы),
        # отдельного XML-конверта у неё нет — печатная форма и есть результат
        raise NotImplementedError(
            "4-ОС не выгружается в XML: форма сдаётся через систему сбора "
            "отчётности Росстата (websbor), используйте печатную форму")

    # ── печать ────────────────────────────────────────────────────────
    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        org, per = self.ctx.organization, self.ctx.period
        wb = xlsx.new_workbook()

        ws = wb.create_sheet("Титул")
        xlsx.merge(ws, "A1:E1", "Форма № 4-ОС", bold=True, align="center")
        xlsx.merge(ws, "A2:E2", "Сведения о текущих затратах на охрану "
                                "окружающей среды", align="center")
        xlsx.merge(ws, "A3:E3", f"за {per.year or '____'} год", align="center")
        xlsx.merge(ws, "A4:E4", "Код формы по ОКУД 0609030 · годовая · "
                                "предоставляется 25 января после отчётного года "
                                "в территориальный орган Росстата",
                   align="center")
        info = [("Наименование отчитывающейся организации",
                 org.name or org.short_name),
                ("Почтовый адрес", org.address),
                ("ИНН", org.inn), ("ОКПО", org.okpo), ("ОКТМО", org.oktmo),
                ("ОКВЭД2", org.okved),
                ("Должностное лицо", org.director_name),
                ("Телефон / e-mail", f"{org.phone or '—'} / {org.email or '—'}")]
        for i, (label, value) in enumerate(info, start=6):
            xlsx.cell(ws, f"A{i}", label, bold=True)
            xlsx.merge(ws, f"B{i}:E{i}", value or "—", align="left")
        xlsx.widths(ws, {"A": 44, "B": 26, "C": 18, "D": 18, "E": 18})

        # ── единая таблица бланка ────────────────────────────────────
        ws1 = wb.create_sheet("Форма")
        ncols = 2 + len(COLS_OWN) + len(COLS_SERVICES)

        def L(n: int) -> str:                        # 1→A, 2→B, …
            return chr(ord("A") + n - 1)

        xlsx.merge(ws1, f"A1:{L(ncols)}1",
                   "Текущие (эксплуатационные) затраты на охрану окружающей "
                   "среды, тыс. рублей", bold=True, align="left")
        # двухуровневая шапка: над графами — названия блоков бланка
        own_from, own_to = 3, 2 + len(COLS_OWN)
        svc_from, svc_to = own_to + 1, own_to + len(COLS_SERVICES)
        xlsx.merge(ws1, f"{L(own_from)}2:{L(own_to)}2",
                   "Затраты на природоохранную деятельность для собственных нужд",
                   bold=True)
        xlsx.merge(ws1, f"{L(svc_from)}2:{L(svc_to)}2",
                   "Затраты на оказание специализированных услуг "
                   "природоохранного назначения", bold=True)
        headers = ["Наименование показателя", "№ строки"] \
            + [n for _c, n in COLS_OWN] + [n for _c, n in COLS_SERVICES]
        xlsx.header_row(ws1, 3, headers)
        # строка нумерации граф — как в бланке
        xlsx.data_row(ws1, 4, ["1", "2"] + [c for c, _n in COLS_OWN]
                      + [c for c, _n in COLS_SERVICES])

        svc = self.services()
        blanks_own = [None] * (len(COLS_OWN) - 1)
        blanks_svc = [None] * (len(COLS_SERVICES) - 1)
        # строка 01 — всего (контрольная сумма строк 02–10)
        xlsx.data_row(ws1, 5, ["Текущие затраты на охрану окружающей среды — всего",
                               "01", float(self.total()) or None, *blanks_own,
                               float(_dec(svc.get("total"))) or None, *blanks_svc])
        row = 6
        for code, name, value in self.costs():
            xlsx.data_row(ws1, row, [f"в том числе: {name}", code,
                                     float(value) or None, *blanks_own,
                                     float(_dec(svc.get(code))) or None, *blanks_svc])
            row += 1
        xlsx.widths(ws1, {"A": 60, "B": 9, "C": 14, "D": 20, "E": 18, "F": 20,
                          "G": 14, "H": 20})
        row += 1
        xlsx.cell(ws1, f"A{row}", "Строка 01 = сумма строк 02–10 (контрольное "
                  "соотношение бланка)", border=False, align="left")
        row += 2
        xlsx.cell(ws1, f"A{row}", f"{org.director_position or 'Руководитель'}"
                  f"  ______________  {org.director_name or ''}",
                  border=False, align="left")
        xlsx.cell(ws1, f"A{row + 2}", "«____» __________ 20___ г.",
                  border=False, align="left")
        return xlsx.save(wb, out_path)
