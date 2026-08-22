"""Данные учёта в области обращения с отходами — журнал по Порядку учёта,
утв. приказом Минприроды России от 08.12.2020 № 1028 (ред. № 825), а с
01.09.2026 — по Порядку, утв. приказом Минприроды от 16.04.2026 № 227.

Печатная форма повторяет официальный бланк: Титул + Приложение 1 (перечень
образующихся отходов) + Приложение 2 (обобщённые данные движения) +
Приложение 3 (переданные другим лицам) + лист «Приложение 4» (полученные от
других лиц). По № 1028 это Таблица 4 в составе Приложения N 3 (ред. № 825:
13 граф — без графы «для накопления и последующей передачи…»); по № 227 —
самостоятельное Приложение N 4. Имя листа «Приложение 4 (год)» сохраняем —
так привык пользователь.

Редакция выбирается в template.edition(): по extra["order_edition"], дате
составления или периоду (обобщение за 2026 год / 3–4 кв. 2026 делается уже
при действующем № 227). По № 227 в Таблице 2 две новые графы — 8
«Поступление отходов с собственных объектов» и 13 «Передача отходов (за
исключением ТКО) на собственные объекты»; массы < 0,001 т — с 4 знаками.

Журнал учёта — внутренний документ природопользователя (ведётся на объекте,
предъявляется при проверке), в ЛКПП не выгружается, поэтому XML у формы нет.
Баланс масс по каждому отходу проверяется.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ecodoc.core import fkko
from ecodoc.core.models import Issue, ReportContext
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.reports.base import Report
from ecodoc.reports.waste_movement import template as tmpl

_log = logging.getLogger(__name__)

# ссылка на приказ — печатается в правом верхнем углу каждого приложения
# (для тестов/обратной совместимости: действующая до 31.08.2026 редакция)
_REF = tmpl.REF_825


@register
class WasteMovement(Report):
    code = "waste-movement"
    title = "Данные учёта отходов (журнал, Приказ №1028; с 01.09.2026 — №227)"
    has_xml = False  # журнал учёта не выгружается в ЛКПП — только печатная форма

    # --- проверка данных ---
    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        if not self.ctx.organization.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not self.ctx.wastes:
            issues.append(Issue("error", "отходы", "нет ни одной позиции отходов"))
        for w in self.ctx.wastes:
            bal_in = (D(w.accumulated_start) + D(w.accumulated_start_nakopl)
                      + D(w.generated) + D(w.received))
            bal_out = (D(w.used) + D(w.neutralized) + D(w.transferred)
                       + D(w.placed_norm) + D(w.placed_over) + D(w.accumulated_end))
            if abs(bal_in - bal_out) > D("0.001"):
                issues.append(Issue(
                    "warning", f"баланс/{w.fkko_code}",
                    f"приход {bal_in} ≠ расход+остаток {bal_out}"))
        return issues

    def render_xml(self, out_path: Path) -> Path:  # pragma: no cover - формы нет
        raise NotImplementedError("Журнал учёта отходов (№1028) в XML не выгружается")

    # --- печатная форма ---
    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        # предупреждения, возникшие при самой генерации (validate() их знать
        # не может — бланк пробуется только здесь); GUI/CLI читают после рендера
        self.render_issues: list[Issue] = []
        self.ed = tmpl.edition(self.ctx)
        self.ref = tmpl.ref_text(self.ed)
        # если у пользователя есть свой бланк журнала (папка «Формы») — заполняем
        # ЕГО: там формулы и привычная вёрстка. Нет бланка — рисуем лист сами.
        try:
            from ecodoc.reports.waste_movement.template import fill
            filled = fill(self.ctx, out_path, issues=self.render_issues)
            if filled is not None:
                return filled
        except Exception as e:
            # бланк не подошёл — обычная генерация. Но сбой НЕ глотаем молча:
            # раньше `except: pass` скрывал, что бланк пользователя ни разу не
            # применился (MergedCell), и выгрузка тихо подменялась листом кода
            _log.warning("waste-movement: бланк из «Формы» не применён: %s", e)
            self.render_issues.append(Issue(
                "warning", "бланк", f"бланк из «Формы» не применён: {e}"))
        wb = xlsx.new_workbook()
        self._sheet_title(wb)
        self._sheet_app1(wb)
        self._sheet_app2(wb)
        self._sheet_app3(wb)
        self._sheet_app4(wb)
        return xlsx.save(wb, out_path)

    def _n(self, v):
        """Тоннаж печатной формы: 3 знака после запятой (№ 1028/№ 227 п. 12),
        по № 227 масса < 0,001 т — 4 знака; сырой float с двоичным хвостом
        (469.0220892119701) в журнал не идёт. Ноль печатаем как 0.0."""
        return tmpl._num(v, getattr(self, "ed", tmpl.ED_825)) or 0.0

    # Титул -----------------------------------------------------------
    def _sheet_title(self, wb):
        ws = wb.create_sheet("Титул")
        o = self.ctx.organization
        xlsx.widths(ws, {"A": 2, **{c: 11 for c in "BCDEFGHIJKL"}})
        xlsx.merge(ws, "B5:L5", "ДАННЫЕ УЧЕТА В ОБЛАСТИ ОБРАЩЕНИЯ С ОТХОДАМИ",
                   bold=True, border=False, size=13)
        # «ООО "…"\nПлощадка по адресу: "адрес"» — как в принятых журналах
        org_line = o.name or o.short_name
        site = tmpl.site_line(self.ctx)
        if site:
            org_line += "\n" + site
        xlsx.merge(ws, "B9:L9", org_line, bold=True, border=False, align="center")
        # ИНН/ОГРН: отдельных полей на титуле бланка нет — печатаем строкой
        xlsx.merge(ws, "B10:L10", tmpl.requisites_line(self.ctx), border=False,
                   align="center")
        xlsx.cell(ws, "E11", "период", border=False, align="right")
        xlsx.merge(ws, "F11:G11", f"за {tmpl.period_text(self.ctx)}", border=False,
                   bold=True)
        xlsx.cell(ws, "B15", "Ответственный исполнитель", border=False, align="left")
        xlsx.merge(ws, "G15:H15", o.director_name or "", border=False)
        xlsx.cell(ws, "J15", "дата", border=False, align="right")
        # «25.12.2025 г.» — как во всех принятых журналах
        xlsx.merge(ws, "K15:L15", tmpl.report_date_text(self.ctx), border=False)
        xlsx.cell(ws, "E16", "подпись", border=False, italic=True, size=9)
        xlsx.merge(ws, "G16:H16", "ФИО", border=False, italic=True, size=9)
        xlsx.heights(ws, {5: 22, 9: 34})

    # Приложение 1 — перечень образующихся отходов ---------------------
    def _sheet_app1(self, wb):
        ws = wb.create_sheet("Приложение 1")
        xlsx.widths(ws, {"A": 6, "B": 40, "C": 16, "D": 10, "E": 26, "F": 24, "G": 34})
        xlsx.cell(ws, "G1", f"Приложение N 1\n{self.ref}", border=False, align="left", size=9)
        # ред. № 825 переименовала Таблицу 1 из «Состав…» в «Перечень…»
        xlsx.merge(ws, "A2:G2", tmpl.APP1_TITLE, bold=True, border=False)
        heads = ["№ п/п", "Наименование отходов", "Код ФККО",
                 "Класс опасности вида отхода",
                 "Происхождение или условия образования вида отхода",
                 "Агрегатное состояние и физическая форма вида отхода",
                 "Химический и (или) компонентный состав вида отхода, %"]
        if self.ed == tmpl.ED_227:
            heads[1], heads[2] = "Наименование вида отхода", "Код по ФККО"
        for i, h in enumerate(heads):
            xlsx.cell(ws, f"{chr(65+i)}4", h, bold=True, fill=True)
        for i in range(7):
            xlsx.cell(ws, f"{chr(65+i)}5", i + 1, italic=True, size=9)
        r = 6
        for n, w in enumerate(self.ctx.wastes, 1):
            xlsx.cell(ws, f"A{r}", n)
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            xlsx.cell(ws, f"C{r}", fkko.fmt(w.fkko_code))
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            xlsx.cell(ws, f"E{r}", w.origin, align="left")
            xlsx.cell(ws, f"F{r}", w.aggregate_state, align="left")
            xlsx.cell(ws, f"G{r}", w.composition, align="left")
            r += 1
        xlsx.heights(ws, {1: 40, 4: 60})

    # Приложение 2 — обобщённые данные движения ------------------------
    def _sheet_app2(self, wb):
        """Два блока, как в бланке: графы 1–7 и «продолжение». По № 227 граф
        18: в первом блоке добавлена гр. 8 «Поступление отходов с собственных
        объектов», во втором — гр. 13 «Передача отходов … на собственные
        объекты» (заполняются при учёте отдельно по каждому объекту НВОС)."""
        ws = wb.create_sheet("Приложение 2 (год)")
        new = self.ed == tmpl.ED_227
        own = tmpl._own_objects(self.ctx)
        xlsx.widths(ws, {"A": 7, "B": 34, "C": 15, "D": 9,
                         **{c: 12 for c in "EFGHIJK"}})
        last = "I" if new else "H"
        xlsx.cell(ws, f"{last}1", f"Приложение N 2\n{self.ref}", border=False,
                  align="left", size=9)
        xlsx.merge(ws, f"A2:{last}2",
                   "Обобщенные данные учета в области обращения с отходами за",
                   bold=True, border=False, align="left")
        # период уже со словом «года» («2025 года», «1 кв 2025 года») —
        # отдельного «год» рядом нет (иначе «за 2025 года год»)
        xlsx.merge(ws, f"G3:{last}3", tmpl.period_text(self.ctx), border=False,
                   bold=True, align="right")
        # часть 1
        xlsx.merge(ws, "A5:A6", "№ п/п", bold=True, fill=True)
        xlsx.merge(ws, "B5:B6", "Наименование вида отхода" if new else
                   "Наименование отходов", bold=True, fill=True)
        xlsx.merge(ws, "C5:C6", "Код по ФККО" if new else "Код ФККО", bold=True, fill=True)
        xlsx.merge(ws, "D5:D6", "Класс опасности вида отхода", bold=True, fill=True)
        xlsx.merge(ws, "E5:F5", "Наличие отходов на начало отчетного периода, тонн",
                   bold=True, fill=True)
        xlsx.cell(ws, "E6", "хранение", bold=True, fill=True, size=9)
        xlsx.cell(ws, "F6", "накопление", bold=True, fill=True, size=9)
        xlsx.merge(ws, "G5:G6", "Образовано отходов в отчетном периоде, тонн",
                   bold=True, fill=True)
        xlsx.merge(ws, "H5:H6",
                   "Получено отходов от других лиц в отчетном периоде, тонн",
                   bold=True, fill=True)
        nums1 = ["А", 1, 2, 3, 4, 5, 6, 7]
        if new:
            xlsx.merge(ws, "I5:I6",
                       "Поступление отходов с собственных объектов (указывается в "
                       "случае ведения учета отходов отдельно по каждому объекту, "
                       "оказывающему негативное воздействие на окружающую среду, "
                       "I - IV категории)", bold=True, fill=True, size=8)
            nums1.append(8)
        for i, lbl in enumerate(nums1):
            xlsx.cell(ws, f"{chr(65+i)}7", lbl, italic=True, size=9)
        r = 8
        for n, w in enumerate(self.ctx.wastes, 1):
            xlsx.cell(ws, f"A{r}", n)
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            xlsx.cell(ws, f"C{r}", fkko.fmt(w.fkko_code))
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            xlsx.cell(ws, f"E{r}", self._n(w.accumulated_start))
            xlsx.cell(ws, f"F{r}", self._n(w.accumulated_start_nakopl))
            xlsx.cell(ws, f"G{r}", self._n(w.generated))
            xlsx.cell(ws, f"H{r}", self._n(w.received))
            if new:
                o = own.get(fkko.norm(w.fkko_code), {})
                xlsx.cell(ws, f"I{r}", self._n(o.get("received_own")))
            r += 1
        # часть 2 (продолжение)
        r += 3
        xlsx.cell(ws, f"J{r-1}", "продолжение", border=False, italic=True, align="right")
        h1, h2 = r, r + 1
        # графы второго блока: (заголовок, ширина-в-колонках)
        cols = [("№ строки", None), ("Обработано отходов в отчетном периоде, тонн", None),
                ("Утилизировано отходов в отчетном периоде, тонн", None),
                ("Обезврежено отходов в отчетном периоде, тонн", None),
                ("Передано отходов другим лицам за отчетный период, тонн" if new
                 else "Передано отходов за отчетный период, тонн", None)]
        if new:
            cols.append(("Передача отходов (за исключением ТКО) на собственные объекты "
                         "(указывается в случае ведения учета отходов отдельно по "
                         "каждому объекту, оказывающему негативное воздействие на "
                         "окружающую среду, I - IV категории)", None))
        c = 0
        for title, _ in cols:
            col = chr(65 + c)
            xlsx.merge(ws, f"{col}{h1}:{col}{h2}", title, bold=True, fill=True,
                       size=8 if len(title) > 60 else None)
            c += 1
        p1, p2, p3 = (chr(65 + c + i) for i in range(3))
        xlsx.merge(ws, f"{p1}{h1}:{p3}{h1}",
                   "Размещено отходов на эксплуатируемых объектах в отчетном периоде, тонн",
                   bold=True, fill=True)
        xlsx.cell(ws, f"{p1}{h2}", "Всего", bold=True, fill=True, size=9)
        xlsx.cell(ws, f"{p2}{h2}", "Хранение", bold=True, fill=True, size=9)
        xlsx.cell(ws, f"{p3}{h2}", "Захоронение", bold=True, fill=True, size=9)
        e1, e2 = chr(65 + c + 3), chr(65 + c + 4)
        xlsx.merge(ws, f"{e1}{h1}:{e2}{h1}",
                   "Наличие отходов на конец отчетного периода, тонн", bold=True, fill=True)
        xlsx.cell(ws, f"{e1}{h2}", "Хранение", bold=True, fill=True, size=9)
        xlsx.cell(ws, f"{e2}{h2}", "Накопление", bold=True, fill=True, size=9)
        num_r = h2 + 1
        first = 9 if new else 8
        width = c + 5
        for i, lbl in enumerate(["А"] + list(range(first, first + width - 1))):
            xlsx.cell(ws, f"{chr(65+i)}{num_r}", lbl, italic=True, size=9)
        dr = num_r + 1
        for n, w in enumerate(self.ctx.wastes, 1):
            placed = self._n(D(w.placed_norm) + D(w.placed_over))
            p_st, p_bu = self._n(w.placed_storage), self._n(w.placed_burial)
            if placed and not p_st and not p_bu:
                # модель не делит собственное размещение — относим к
                # захоронению (типовой случай размещения у полигона)
                p_bu = placed
            vals = [n, self._n(w.processed), self._n(w.used), self._n(w.neutralized),
                    self._n(w.transferred)]
            if new:
                o = own.get(fkko.norm(w.fkko_code), {})
                vals.append(self._n(o.get("transferred_own")))
            vals += [placed, p_st, p_bu, self._n(w.accumulated_end),
                     self._n(w.accumulated_end_nakopl)]
            for i, v in enumerate(vals):
                xlsx.cell(ws, f"{chr(65+i)}{dr}", v)
            dr += 1
        xlsx.heights(ws, {1: 40, h1: 70 if new else 40})

    # Приложение 3 — переданные отходы ---------------------------------
    def _sheet_app3(self, wb):
        ws = wb.create_sheet("Приложение 3 (год)")
        recv = self._receivers_by_fkko()
        xlsx.widths(ws, {"A": 6, "B": 30, "C": 15, "D": 8, **{c: 10 for c in "EFGHIJ"},
                         "K": 26, "L": 20, "M": 16, "N": 30})
        xlsx.cell(ws, "N1", f"Приложение N 3\n{self.ref}", border=False, align="left", size=9)
        xlsx.merge(ws, "A2:N2",
                   "Данные учета переданных другим лицам отходов за", bold=True,
                   border=False, align="left")
        xlsx.merge(ws, "L3:M3", tmpl.period_text(self.ctx), border=False, bold=True)
        xlsx.merge(ws, "A5:A6", "№ п/п", bold=True, fill=True)
        xlsx.merge(ws, "B5:B6", "Наименование отходов", bold=True, fill=True)
        xlsx.merge(ws, "C5:C6", "Код ФККО", bold=True, fill=True)
        xlsx.merge(ws, "D5:D6", "Класс опасности вида отхода", bold=True, fill=True)
        xlsx.merge(ws, "E5:J5", "Количество переданных отходов за отчетный период, тонн",
                   bold=True, fill=True)
        for col, lbl in zip("EFGHIJ", ["Всего", "Для обработки", "Для утилизации",
                                       "Для обезвреживания", "Для хранения",
                                       "Для захоронения"]):
            xlsx.cell(ws, f"{col}6", lbl, bold=True, fill=True, size=9)
        xlsx.merge(ws, "K5:K6", "Сведения о лицах, которым переданы отходы",
                   bold=True, fill=True)
        xlsx.merge(ws, "L5:L6", "Дата и номер договора на передачу отходов",
                   bold=True, fill=True)
        xlsx.merge(ws, "M5:M6", "Срок действия договора", bold=True, fill=True)
        xlsx.merge(ws, "N5:N6",
                   "Реквизиты лицензии на осуществление деятельности по сбору, "
                   "транспортированию, обработке, утилизации, обезвреживанию, "
                   "размещению отходов I-IV классов опасности", bold=True, fill=True, size=9)
        for i, n in enumerate(range(1, 15)):
            xlsx.cell(ws, f"{_col(i)}7", n, italic=True, size=9)
        r = 8
        for n, w in enumerate(self.ctx.wastes, 1):   # n — № отхода из Прил. 1
            if D(w.transferred) == 0:
                continue
            info = recv.get(fkko.norm(w.fkko_code), {})
            xlsx.cell(ws, f"A{r}", n)
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            xlsx.cell(ws, f"C{r}", fkko.fmt(w.fkko_code))
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            xlsx.cell(ws, f"E{r}", self._n(w.transferred))         # всего
            xlsx.cell(ws, f"F{r}", self._n(w.transferred_processing))  # для обработки
            xlsx.cell(ws, f"G{r}", self._n(w.transferred_util))    # для утилизации
            xlsx.cell(ws, f"H{r}", self._n(w.transferred_neutral))  # для обезвреживания
            xlsx.cell(ws, f"I{r}", self._n(w.transferred_storage))  # для хранения
            xlsx.cell(ws, f"J{r}", self._n(w.transferred_burial))   # для захоронения
            xlsx.cell(ws, f"K{r}", info.get("receiver", ""), align="left")
            xlsx.cell(ws, f"L{r}", info.get("contract", ""), align="left")
            xlsx.cell(ws, f"M{r}", info.get("contract_term", ""), align="left")
            xlsx.cell(ws, f"N{r}", info.get("license", ""), align="left")
            r += 1
        if r == 8:  # ничего не передавалось — пустая строка-заглушка
            for i in range(14):
                xlsx.cell(ws, f"{_col(i)}8", "-")
        xlsx.heights(ws, {1: 40, 5: 40})

    # Приложение 4 — полученные отходы ----------------------------------
    def _sheet_app4(self, wb):
        """Лист сохраняет привычную пользователю вёрстку («Приложение 4»),
        но подпись — по НПА: в № 1028 (ред. № 825) это Таблица 4 Приложения
        N 3, и в ней 13 граф (графа «для накопления и последующей передачи…»
        исключена с 01.09.2024); в № 227 — самостоятельное Приложение N 4
        с теми же 13 графами."""
        ws = wb.create_sheet("Приложение 4 (год)")
        sup = self._suppliers_by_fkko()
        xlsx.widths(ws, {"A": 6, "B": 30, "C": 15, "D": 8, **{c: 10 for c in "EFGHIJ"},
                         "K": 26, "L": 18, "M": 16})
        label = ("Приложение N 4" if self.ed == tmpl.ED_227
                 else "Приложение N 3 (Таблица 4)")
        xlsx.cell(ws, "M1", f"{label}\n{self.ref}", border=False, align="left", size=9)
        xlsx.merge(ws, "A2:M2", "Данные учета полученных от других лиц отходов за",
                   bold=True, border=False, align="left")
        xlsx.merge(ws, "K3:L3", tmpl.period_text(self.ctx), border=False, bold=True)
        xlsx.merge(ws, "A5:A7", "№ п/п", bold=True, fill=True)
        xlsx.merge(ws, "B5:B7", "Наименование отходов", bold=True, fill=True)
        xlsx.merge(ws, "C5:C7", "Код ФККО", bold=True, fill=True)
        xlsx.merge(ws, "D5:D7", "Класс опасности вида отхода", bold=True, fill=True)
        xlsx.merge(ws, "E5:J5", "Количество полученных отходов за отчетный период, тонн",
                   bold=True, fill=True)
        xlsx.merge(ws, "E6:E7", "Всего", bold=True, fill=True, size=9)
        xlsx.merge(ws, "F6:J6", "в том числе:", bold=True, fill=True, size=9)
        subs = ["для обработки", "для утилизации", "для обезвреживания",
                "для хранения", "для захоронения"]
        for col, lbl in zip("FGHIJ", subs):
            xlsx.cell(ws, f"{col}7", lbl, bold=True, fill=True, size=8)
        xlsx.merge(ws, "K5:K7", "Сведения о лицах, от которых получены отходы",
                   bold=True, fill=True)
        xlsx.merge(ws, "L5:L7", "Дата и номер договора на передачу отходов",
                   bold=True, fill=True)
        xlsx.merge(ws, "M5:M7", "Срок действия договора", bold=True, fill=True)
        for i, n in enumerate(range(1, 14)):
            xlsx.cell(ws, f"{_col(i)}8", n, italic=True, size=9)
        r = 9
        got = False
        for n, w in enumerate(self.ctx.wastes, 1):   # n — № отхода из Прил. 1
            if D(w.received) == 0:
                continue
            got = True
            info = sup.get(fkko.norm(w.fkko_code), {})
            xlsx.cell(ws, f"A{r}", n)
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            xlsx.cell(ws, f"C{r}", fkko.fmt(w.fkko_code))
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            xlsx.cell(ws, f"E{r}", self._n(w.received))
            for col in "FGHIJ":
                xlsx.cell(ws, f"{col}{r}", 0.0)
            # модель не хранит поставщиков — берём из ctx.extra["waste_suppliers"]
            # (по образцу waste_receivers), нет данных — пустая графа
            xlsx.cell(ws, f"K{r}", info.get("supplier", ""), align="left")
            xlsx.cell(ws, f"L{r}", info.get("contract", ""), align="left")
            xlsx.cell(ws, f"M{r}", info.get("contract_term", ""), align="left")
            r += 1
        if not got:
            for i in range(13):
                xlsx.cell(ws, f"{_col(i)}9", "-")
        xlsx.heights(ws, {1: 40, 5: 30, 7: 42})

    # --- вспомогательное ---
    def _receivers_by_fkko(self) -> dict[str, dict]:
        return tmpl._by_fkko(self.ctx, "waste_receivers")

    def _suppliers_by_fkko(self) -> dict[str, dict]:
        """От кого получены отходы (Таблица 4): ключи supplier/contract/
        contract_term — в модели WasteFlow этих сведений нет."""
        return tmpl._by_fkko(self.ctx, "waste_suppliers")


def year_from_months(month_ctxs: list[ReportContext]) -> ReportContext:
    """Собрать годовой журнал из месячных — как это делает пользователь в
    «1028 2025 с формулами.xlsx»: Прил. 2 гр. 6 «Образовано» =
    SUMIF по 12 месячным файлам, гр. 8–11 и графы 5–10 Прил. 3 — тоже суммы
    по месяцам; остаток на начало года — из первого месяца, на конец — из
    последнего; перечень Прил. 1 — объединение отходов всех месяцев (в
    годовом файле у отхода есть столбцы-флажки «январь … декабрь»).

    Контексты передавать в порядке месяцев. Организация/объекты/контрагенты
    — из последнего (самого свежего) месяца; период — год без месяца."""
    import copy
    from ecodoc.core.models import ReportPeriod, WasteFlow

    if not month_ctxs:
        raise ValueError("нет месячных журналов")
    flows = ("generated", "received", "processed", "used", "neutralized",
             "transferred", "transferred_processing", "transferred_util",
             "transferred_neutral", "transferred_storage", "transferred_burial",
             "placed_norm", "placed_over", "placed_storage", "placed_burial")
    acc: dict[str, WasteFlow] = {}
    for ctx in month_ctxs:
        for w in ctx.wastes:
            key = fkko.norm(w.fkko_code) or w.name
            if key not in acc:
                y = copy.deepcopy(w)
                for f in flows:
                    setattr(y, f, D(0))
                # остаток на начало года — из первого месяца, где отход встретился
                y.accumulated_start = D(w.accumulated_start)
                y.accumulated_start_nakopl = D(w.accumulated_start_nakopl)
                acc[key] = y
            y = acc[key]
            for f in flows:
                setattr(y, f, D(getattr(y, f)) + D(getattr(w, f)))
            # остаток на конец — из последнего месяца
            y.accumulated_end = D(w.accumulated_end)
            y.accumulated_end_nakopl = D(w.accumulated_end_nakopl)
            # Прил. 1 (состав/происхождение) — из самой свежей заполненной записи
            for f in ("name", "origin", "aggregate_state", "composition"):
                if getattr(w, f, ""):
                    setattr(y, f, getattr(w, f))
    last = month_ctxs[-1]
    year = copy.copy(last)
    year.extra = dict(last.extra if isinstance(last.extra, dict) else {})
    year.extra.pop("period_month", None)
    year.extra.pop("period_text", None)
    year.period = ReportPeriod(year=last.period.year)
    year.wastes = list(acc.values())
    return year


def _col(i: int) -> str:
    """Индекс 0-based → буква столбца (A..Z, поддержка до N=13 достаточна)."""
    return chr(65 + i)
