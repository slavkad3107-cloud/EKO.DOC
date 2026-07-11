"""Данные учёта в области обращения с отходами — журнал по Порядку учёта,
утв. приказом Минприроды России от 08.12.2020 № 1028.

Печатная форма повторяет официальный бланк: Титул + Приложение 1 (состав
образующихся отходов) + Приложение 2 (обобщённые данные движения за год) +
Приложение 3 (переданные другим лицам) + Приложение 4 (полученные).

Журнал учёта — внутренний документ природопользователя (ведётся на объекте,
предъявляется при проверке), в ЛКПП не выгружается, поэтому XML у формы нет.
Баланс масс по каждому отходу проверяется.
"""
from __future__ import annotations

from pathlib import Path

from ecodoc.core.models import Issue, ReportContext
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.reports.base import Report

# ссылка на приказ — печатается в правом верхнем углу каждого приложения.
# Действует ред. приказа Минприроды № 825 от 13.12.2023 (с 01.09.2024); с
# 01.09.2026 № 1028 заменяется приказом Минприроды № 227 от 16.04.2026.
_REF = ("к Порядку учета в области обращения с отходами, утвержденному "
        "приказом Министерства природных ресурсов и экологии Российской "
        "Федерации от 8 декабря 2020 г. N 1028 (в ред. приказа от 13.12.2023 N 825)")


def _num(v) -> float:
    return float(D(v))


@register
class WasteMovement(Report):
    code = "waste-movement"
    title = "Данные учёта отходов (журнал, Приказ №1028)"
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
        wb = xlsx.new_workbook()
        self._sheet_title(wb)
        self._sheet_app1(wb)
        self._sheet_app2(wb)
        self._sheet_app3(wb)
        self._sheet_app4(wb)
        return xlsx.save(wb, out_path)

    # Титул -----------------------------------------------------------
    def _sheet_title(self, wb):
        ws = wb.create_sheet("Титул")
        o = self.ctx.organization
        year = self.ctx.period.year or ""
        site = self._site_line()
        xlsx.widths(ws, {"A": 2, **{c: 11 for c in "BCDEFGHIJKL"}})
        xlsx.merge(ws, "B5:L5", "ДАННЫЕ УЧЕТА В ОБЛАСТИ ОБРАЩЕНИЯ С ОТХОДАМИ",
                   bold=True, border=False, size=13)
        org_line = o.name or o.short_name
        if site:
            org_line += "\n" + site
        xlsx.merge(ws, "B9:L9", org_line, bold=True, border=False, align="center")
        xlsx.cell(ws, "E11", "период", border=False, align="right")
        xlsx.merge(ws, "F11:G11", f"за {year} год", border=False, bold=True)
        xlsx.cell(ws, "B15", "Ответственный исполнитель", border=False, align="left")
        xlsx.merge(ws, "G15:H15", o.director_name or "", border=False)
        xlsx.cell(ws, "J15", "дата", border=False, align="right")
        xlsx.merge(ws, "K15:L15", "", border=False)
        xlsx.cell(ws, "E16", "подпись", border=False, italic=True, size=9)
        xlsx.merge(ws, "G16:H16", "ФИО", border=False, italic=True, size=9)
        xlsx.heights(ws, {5: 22, 9: 34})

    # Приложение 1 — состав образующихся отходов -----------------------
    def _sheet_app1(self, wb):
        ws = wb.create_sheet("Приложение 1")
        xlsx.widths(ws, {"A": 6, "B": 40, "C": 16, "D": 10, "E": 26, "F": 24, "G": 34})
        xlsx.cell(ws, "G1", f"Приложение N 1\n{_REF}", border=False, align="left", size=9)
        xlsx.merge(ws, "A2:G2", "Состав образующихся видов отходов, подлежащих учету",
                   bold=True, border=False)
        heads = ["№ п/п", "Наименование отходов", "Код ФККО",
                 "Класс опасности вида отхода",
                 "Происхождение или условия образования вида отхода",
                 "Агрегатное состояние и физическая форма вида отхода",
                 "Химический и (или) компонентный состав вида отхода, %"]
        for i, h in enumerate(heads):
            xlsx.cell(ws, f"{chr(65+i)}4", h, bold=True, fill=True)
        for i in range(7):
            xlsx.cell(ws, f"{chr(65+i)}5", i + 1, italic=True, size=9)
        r = 6
        for n, w in enumerate(self.ctx.wastes, 1):
            xlsx.cell(ws, f"A{r}", n)
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            xlsx.cell(ws, f"C{r}", w.fkko_code)
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            xlsx.cell(ws, f"E{r}", w.origin, align="left")
            xlsx.cell(ws, f"F{r}", w.aggregate_state, align="left")
            xlsx.cell(ws, f"G{r}", w.composition, align="left")
            r += 1
        xlsx.heights(ws, {1: 40, 4: 60})

    # Приложение 2 — обобщённые данные движения ------------------------
    def _sheet_app2(self, wb):
        ws = wb.create_sheet("Приложение 2 (год)")
        year = self.ctx.period.year or ""
        xlsx.widths(ws, {"A": 7, "B": 34, "C": 15, "D": 9,
                         **{c: 12 for c in "EFGHIJ"}})
        xlsx.cell(ws, "H1", f"Приложение N 2\n{_REF}", border=False, align="left", size=9)
        xlsx.merge(ws, "A2:H2",
                   "Обобщенные данные учета в области обращения с отходами за",
                   bold=True, border=False, align="left")
        xlsx.cell(ws, "G3", year, border=False, bold=True, align="right")
        xlsx.cell(ws, "H3", "год", border=False, align="left")
        # часть 1
        xlsx.merge(ws, "A5:A6", "№ п/п", bold=True, fill=True)
        xlsx.merge(ws, "B5:B6", "Наименование отходов", bold=True, fill=True)
        xlsx.merge(ws, "C5:C6", "Код ФККО", bold=True, fill=True)
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
        for i, lbl in enumerate(["А", 1, 2, 3, 4, 5, 6, 7]):
            xlsx.cell(ws, f"{chr(65+i)}7", lbl, italic=True, size=9)
        r = 8
        for n, w in enumerate(self.ctx.wastes, 1):
            xlsx.cell(ws, f"A{r}", n)
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            xlsx.cell(ws, f"C{r}", w.fkko_code)
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            xlsx.cell(ws, f"E{r}", _num(w.accumulated_start))
            xlsx.cell(ws, f"F{r}", _num(w.accumulated_start_nakopl))
            xlsx.cell(ws, f"G{r}", _num(w.generated))
            xlsx.cell(ws, f"H{r}", _num(w.received))
            r += 1
        # часть 2 (продолжение)
        r += 3
        xlsx.cell(ws, f"J{r-1}", "продолжение", border=False, italic=True, align="right")
        h1, h2 = r, r + 1
        xlsx.merge(ws, f"A{h1}:A{h2}", "№ строки", bold=True, fill=True)
        xlsx.merge(ws, f"B{h1}:B{h2}", "Обработано отходов в отчетном периоде, тонн",
                   bold=True, fill=True)
        xlsx.merge(ws, f"C{h1}:C{h2}", "Утилизировано отходов в отчетном периоде, тонн",
                   bold=True, fill=True)
        xlsx.merge(ws, f"D{h1}:D{h2}", "Обезврежено отходов в отчетном периоде, тонн",
                   bold=True, fill=True)
        xlsx.merge(ws, f"E{h1}:E{h2}", "Передано отходов за отчетный период, тонн",
                   bold=True, fill=True)
        xlsx.merge(ws, f"F{h1}:H{h1}",
                   "Размещено отходов на эксплуатируемых объектах в отчетном периоде, тонн",
                   bold=True, fill=True)
        xlsx.cell(ws, f"F{h2}", "Всего", bold=True, fill=True, size=9)
        xlsx.cell(ws, f"G{h2}", "Хранение", bold=True, fill=True, size=9)
        xlsx.cell(ws, f"H{h2}", "Захоронение", bold=True, fill=True, size=9)
        xlsx.merge(ws, f"I{h1}:J{h1}",
                   "Наличие отходов на конец отчетного периода, тонн", bold=True, fill=True)
        xlsx.cell(ws, f"I{h2}", "Хранение", bold=True, fill=True, size=9)
        xlsx.cell(ws, f"J{h2}", "Накопление", bold=True, fill=True, size=9)
        num_r = h2 + 1
        for i, lbl in enumerate(["А", 8, 9, 10, 11, 12, 13, 14, 15, 16]):
            xlsx.cell(ws, f"{chr(65+i)}{num_r}", lbl, italic=True, size=9)
        dr = num_r + 1
        for n, w in enumerate(self.ctx.wastes, 1):
            placed = _num(D(w.placed_norm) + D(w.placed_over))
            xlsx.cell(ws, f"A{dr}", n)
            xlsx.cell(ws, f"B{dr}", _num(w.processed))
            xlsx.cell(ws, f"C{dr}", _num(w.used))
            xlsx.cell(ws, f"D{dr}", _num(w.neutralized))
            xlsx.cell(ws, f"E{dr}", _num(w.transferred))
            xlsx.cell(ws, f"F{dr}", placed)
            xlsx.cell(ws, f"G{dr}", _num(w.placed_norm))
            xlsx.cell(ws, f"H{dr}", 0.0)
            xlsx.cell(ws, f"I{dr}", _num(w.accumulated_end))
            xlsx.cell(ws, f"J{dr}", 0.0)
            dr += 1
        xlsx.heights(ws, {1: 40})

    # Приложение 3 — переданные отходы ---------------------------------
    def _sheet_app3(self, wb):
        ws = wb.create_sheet("Приложение 3 (год)")
        year = self.ctx.period.year or ""
        recv = self._receivers_by_fkko()
        xlsx.widths(ws, {"A": 6, "B": 30, "C": 15, "D": 8, **{c: 10 for c in "EFGHIJ"},
                         "K": 26, "L": 20, "M": 16, "N": 30})
        xlsx.cell(ws, "N1", f"Приложение N 3\n{_REF}", border=False, align="left", size=9)
        xlsx.merge(ws, "A2:N2",
                   "Данные учета переданных другим лицам отходов за", bold=True,
                   border=False, align="left")
        xlsx.merge(ws, "L3:M3", f"{year} год", border=False, bold=True)
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
        for n, w in enumerate(self.ctx.wastes, 1):
            if D(w.transferred) == 0:
                continue
            info = recv.get(w.fkko_code, {})
            xlsx.cell(ws, f"A{r}", n)
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            xlsx.cell(ws, f"C{r}", w.fkko_code)
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            xlsx.cell(ws, f"E{r}", _num(w.transferred))         # всего
            xlsx.cell(ws, f"F{r}", 0.0)                          # для обработки
            xlsx.cell(ws, f"G{r}", _num(w.transferred_util))    # для утилизации
            xlsx.cell(ws, f"H{r}", _num(w.transferred_neutral))  # для обезвреживания
            xlsx.cell(ws, f"I{r}", _num(w.transferred_storage))  # для хранения
            xlsx.cell(ws, f"J{r}", _num(w.transferred_burial))   # для захоронения
            xlsx.cell(ws, f"K{r}", info.get("receiver", ""), align="left")
            xlsx.cell(ws, f"L{r}", info.get("contract", ""), align="left")
            xlsx.cell(ws, f"M{r}", info.get("contract_term", ""), align="left")
            xlsx.cell(ws, f"N{r}", info.get("license", ""), align="left")
            r += 1
        if r == 8:  # ничего не передавалось — пустая строка-заглушка
            for i in range(14):
                xlsx.cell(ws, f"{_col(i)}8", "-")
        xlsx.heights(ws, {1: 40, 5: 40})

    # Приложение 4 — полученные отходы ---------------------------------
    def _sheet_app4(self, wb):
        ws = wb.create_sheet("Приложение 4 (год)")
        year = self.ctx.period.year or ""
        xlsx.widths(ws, {"A": 6, "B": 30, "C": 15, "D": 8, **{c: 10 for c in "EFGHIJK"},
                         "L": 26, "M": 18, "N": 16})
        xlsx.cell(ws, "M1", f"Приложение N 4\n{_REF}", border=False, align="left", size=9)
        xlsx.merge(ws, "A2:N2", "Данные учета полученных от других лиц отходов за",
                   bold=True, border=False, align="left")
        xlsx.merge(ws, "L3:M3", f"{year} год", border=False, bold=True)
        xlsx.merge(ws, "A5:A7", "№ п/п", bold=True, fill=True)
        xlsx.merge(ws, "B5:B7", "Наименование отходов", bold=True, fill=True)
        xlsx.merge(ws, "C5:C7", "Код ФККО", bold=True, fill=True)
        xlsx.merge(ws, "D5:D7", "Класс опасности вида отхода", bold=True, fill=True)
        xlsx.merge(ws, "E5:K5", "Количество полученных отходов за отчетный период, тонн",
                   bold=True, fill=True)
        xlsx.merge(ws, "E6:E7", "Всего", bold=True, fill=True, size=9)
        xlsx.merge(ws, "F6:K6", "в том числе:", bold=True, fill=True, size=9)
        subs = ["для накопления и последующей передачи другим индивидуальным "
                "предпринимателям и юридическим лицам", "для обработки",
                "для утилизации", "для обезвреживания", "для хранения",
                "для захоронения"]
        for col, lbl in zip("FGHIJK", subs):
            xlsx.cell(ws, f"{col}7", lbl, bold=True, fill=True, size=8)
        xlsx.merge(ws, "L5:L7", "Сведения о лицах, от которых получены отходы",
                   bold=True, fill=True)
        xlsx.merge(ws, "M5:M7", "Дата и номер договора на передачу отходов",
                   bold=True, fill=True)
        xlsx.merge(ws, "N5:N7", "Срок действия договора", bold=True, fill=True)
        for i, n in enumerate(range(1, 15)):
            xlsx.cell(ws, f"{_col(i)}8", n, italic=True, size=9)
        r = 9
        got = False
        for n, w in enumerate(self.ctx.wastes, 1):
            if D(w.received) == 0:
                continue
            got = True
            xlsx.cell(ws, f"A{r}", n)
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            xlsx.cell(ws, f"C{r}", w.fkko_code)
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            xlsx.cell(ws, f"E{r}", _num(w.received))
            for col in "FGHIJK":
                xlsx.cell(ws, f"{col}{r}", 0.0)
            xlsx.cell(ws, f"L{r}", "", align="left")
            xlsx.cell(ws, f"M{r}", "", align="left")
            xlsx.cell(ws, f"N{r}", "", align="left")
            r += 1
        if not got:
            for i in range(14):
                xlsx.cell(ws, f"{_col(i)}9", "-")
        xlsx.heights(ws, {1: 40, 5: 30, 7: 42})

    # --- вспомогательное ---
    def _site_line(self) -> str:
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        if e.get("site_line"):
            return str(e["site_line"])
        if self.ctx.objects:
            ob = self.ctx.objects[0]
            return f"Площадка: {ob.name or ''} {ob.address or ''}".strip()
        return ""

    def _receivers_by_fkko(self) -> dict[str, dict]:
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        out: dict[str, dict] = {}
        for r in e.get("waste_receivers", []):
            if isinstance(r, dict) and r.get("fkko"):
                out[str(r["fkko"])] = r
        return out


def _col(i: int) -> str:
    """Индекс 0-based → буква столбца (A..Z, поддержка до N=13 достаточна)."""
    return chr(65 + i)
