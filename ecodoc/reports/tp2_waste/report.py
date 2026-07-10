"""Форма № 2-ТП (отходы) — сведения об образовании, обработке, утилизации,
обезвреживании, транспортировании и размещении отходов. Годовая, до 1 февраля
(за 2025 — до 02.02.2026), в ЛКПП РПН. Код формы по ОКУД 0609013.

ДЕЙСТВУЮЩАЯ редакция — Приказ Росстата от 06.11.2025 № 614 (за отчётный 2025);
Приказ № 627 от 09.10.2020 (ранее № 529) утратил силу.

ВНИМАНИЕ: действующая форма № 614 содержит 3 раздела (Раздел I — движение,
графы 1–29 с балансовой формулой графы 29; Раздел II — сведения регоператоров
ТКО; Раздел III — объекты размещения). Текущий генератор реализует только
Раздел I в объёме 18 граф — требуется расширение до 29 граф и добавление
Разделов II/III. Точность массы: I–III класс — 3 знака, IV–V — 1 знак.
XML — конверт «Модуля природопользователя» (DATA_PACKET_NI, DocType=3);
актуальный XSD Модуля за 2025 не сверялся.

Данные — из ctx.wastes (та же модель, что и учёт движения №1028).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ecodoc.core.models import Issue
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import data_packet_ni, el, write_tree
from ecodoc.reports.base import Report


def _n(v) -> float:
    return float(D(v))


def _f6(v) -> str:
    return f"{_n(v):.6f}"


@register
class TP2Waste(Report):
    code = "2tp-waste"
    title = "2-ТП (отходы)"

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not o.okpo:
            issues.append(Issue("warning", "ОКПО", "для 2-ТП обязателен код ОКПО"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.wastes:
            issues.append(Issue("error", "отходы", "нет позиций отходов"))
        return issues

    # ---------------- XML (Модуль природопользователя) ----------------
    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        exp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        root = data_packet_ni(self.ctx, doc_type=3, body_fn=self._body, exp_date=exp)
        write_tree(root, out_path)
        return out_path

    def _body(self, org, obj, exp_date):
        o = self.ctx.organization
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        ob, eo_id = obj if obj else (None, "")
        okato = (ob.oktmo if ob else "") or o.oktmo
        rpt = el(org, "RPT_2TP_WASTE")
        el(rpt, "DOC_YEAR", self.ctx.period.year)
        el(rpt, "RPN_CODE", "1")
        el(rpt, "ROSPRIR", e.get("rospr", ""))
        el(rpt, "FNAME", o.name)
        el(rpt, "SNAME", o.short_name or o.name)
        el(rpt, "ADDR_STR", o.address)
        el(rpt, "OGRN", o.ogrn)
        el(rpt, "INN", o.inn)
        el(rpt, "KPP", o.kpp)
        el(rpt, "OKPO", o.okpo)
        el(rpt, "OFFICIAL", o.director_position)
        el(rpt, "FIO_OFFICIAL", o.director_name)
        el(rpt, "CREATE_DATE", exp_date[:10])
        el(rpt, "OKATO", o.oktmo)
        el(rpt, "RPT_OKATO", okato)
        el(rpt, "ID_EO", eo_id)
        codes = [c.strip() for c in (o.okved or "").replace(";", ",").split(",") if c.strip()]
        if codes:
            okv = el(rpt, "OKVED")
            el(okv, "OKVED_CODE", codes[0])
        for w in self.ctx.wastes:
            fact = el(rpt, "RPT_2TP_WASTE_FACT")
            el(fact, "NONE_FKKO_NAME", w.name)
            el(fact, "WST_CODE", str(w.fkko_code).replace(" ", ""))
            el(fact, "WSTYPE", w.hazard_class)
            el(fact, "TP2_BP_ACCUM_WASTE", _f6(w.accumulated_start))
            el(fact, "TP2_FORMING", _f6(w.generated))
            el(fact, "TP2_ARRIVAL", _f6(w.received))
            el(fact, "TP2_TRANSF", _f6(w.transferred))
            el(fact, "TP2_TR_ISPOTX", _f6(w.used))
            el(fact, "TP2_TR_SOTX", _f6(w.neutralized))
            el(fact, "TP2_TR_DISP", _f6(w.transferred))
            el(fact, "TP2_RAZM", _f6(D(w.placed_norm) + D(w.placed_over)))
            el(fact, "TP2_RAZM_STOR", "0.000000")
            el(fact, "TP2_ACCUM_WASTE", _f6(w.accumulated_end))

    # ---------------- Печатная форма (3 страницы) ---------------------
    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        self._page1(wb)
        self._page2(wb)
        self._page3(wb)
        return xlsx.save(wb, out_path)

    def _page1(self, wb):
        ws = wb.create_sheet("стр.1")
        o = self.ctx.organization
        year = self.ctx.period.year or ""
        xlsx.widths(ws, {"A": 22, "B": 22, "C": 18, "D": 16, "E": 18, "F": 20})
        xlsx.merge(ws, "A1:F1", "ФЕДЕРАЛЬНОЕ СТАТИСТИЧЕСКОЕ НАБЛЮДЕНИЕ",
                   bold=True, border=False)
        xlsx.merge(ws, "A3:F4", "СВЕДЕНИЯ ОБ ОБРАЗОВАНИИ, ОБРАБОТКЕ, УТИЛИЗАЦИИ, "
                   "ОБЕЗВРЕЖИВАНИИ, ТРАНСПОРТИРОВАНИИ И РАЗМЕЩЕНИИ ОТХОДОВ "
                   "ПРОИЗВОДСТВА И ПОТРЕБЛЕНИЯ", bold=True, border=False)
        xlsx.merge(ws, "A5:F5", f"за {year} год", border=False, bold=True)
        xlsx.merge(ws, "E6:F6", "Форма № 2-ТП (отходы), годовая", border=False,
                   italic=True, align="right")
        xlsx.cell(ws, "A8", "Наименование отчитывающейся организации",
                  border=False, align="left")
        xlsx.merge(ws, "A9:F9", o.name, border=False, align="left")
        xlsx.cell(ws, "A11", "Почтовый адрес", border=False, align="left")
        xlsx.merge(ws, "A12:F12", o.address, border=False, align="left")
        head = ["Код формы по ОКУД", "Код отчитывающейся организации по ОКПО",
                "Код вида деятельности по ОКВЭД", "Код территории по ОКТМО",
                "ИНН", "ОГРН"]
        okved1 = next((c.strip() for c in (o.okved or "").replace(";", ",").split(",")
                       if c.strip()), "")
        vals = ["0609013", o.okpo, okved1, o.oktmo, o.inn, o.ogrn]
        for i, (h, v) in enumerate(zip(head, vals)):
            col = chr(65 + i)
            xlsx.cell(ws, f"{col}15", h, bold=True, fill=True, size=9)
            xlsx.cell(ws, f"{col}16", i + 1, italic=True, size=9)
            xlsx.cell(ws, f"{col}17", v or "")
        xlsx.heights(ws, {3: 46, 15: 46})

    def _page2(self, wb):
        ws = wb.create_sheet("стр.2")
        xlsx.cell(ws, "A1", "Код по ОКЕИ: тонна — 168", border=False, italic=True, align="left")
        # верхний ярус групп (row 2), подписи (row 3), номера граф (row 4)
        xlsx.merge(ws, "A2:A4", "№ строки", bold=True, fill=True, size=9)
        xlsx.merge(ws, "B2:B4", "Наименование видов отходов", bold=True, fill=True, size=9)
        xlsx.merge(ws, "C2:C4", "Код отхода по ФККО", bold=True, fill=True, size=9)
        xlsx.merge(ws, "D2:D4", "Класс опасности отхода", bold=True, fill=True, size=9)
        xlsx.merge(ws, "E2:E4", "Наличие отходов на начало отчетного года",
                   bold=True, fill=True, size=8)
        xlsx.merge(ws, "F2:F4", "Образование отходов за отчетный год",
                   bold=True, fill=True, size=8)
        xlsx.merge(ws, "G2:H2", "Поступление отходов из других хозяйствующих субъектов",
                   bold=True, fill=True, size=8)
        xlsx.merge(ws, "G3:G4", "всего", bold=True, fill=True, size=8)
        xlsx.merge(ws, "H3:H4", "в т.ч. по импорту", bold=True, fill=True, size=8)
        xlsx.merge(ws, "I2:I4", "Обработано отходов", bold=True, fill=True, size=8)
        xlsx.merge(ws, "J2:L2", "Утилизировано отходов", bold=True, fill=True, size=8)
        xlsx.merge(ws, "J3:J4", "всего", bold=True, fill=True, size=8)
        xlsx.merge(ws, "K3:K4", "для повторного применения (рециклинг)",
                   bold=True, fill=True, size=8)
        xlsx.merge(ws, "L3:L4", "предварительно прошедших обработку",
                   bold=True, fill=True, size=8)
        xlsx.merge(ws, "M2:N2", "Обезврежено отходов", bold=True, fill=True, size=8)
        xlsx.merge(ws, "M3:M4", "всего", bold=True, fill=True, size=8)
        xlsx.merge(ws, "N3:N4", "из них предварительно прошедших обработку",
                   bold=True, fill=True, size=8)
        xlsx.merge(ws, "O2:S2", "Передача отходов другим хозяйствующим субъектам",
                   bold=True, fill=True, size=8)
        for col, lbl in zip("OPQRS", ["для обработки", "для утилизации",
                                      "для обезвреживания", "для хранения",
                                      "для захоронения"]):
            xlsx.merge(ws, f"{col}3:{col}4", lbl, bold=True, fill=True, size=8)
        xlsx.merge(ws, "T2:U2", "Размещение отходов на эксплуатируемых объектах",
                   bold=True, fill=True, size=8)
        xlsx.merge(ws, "T3:T4", "хранение", bold=True, fill=True, size=8)
        xlsx.merge(ws, "U3:U4", "захоронение", bold=True, fill=True, size=8)
        xlsx.merge(ws, "V2:V4", "Наличие отходов на конец отчетного года",
                   bold=True, fill=True, size=8)
        graphs = ["А", "Б", "В", "Г"] + [str(i) for i in range(1, 19)]
        from openpyxl.utils import get_column_letter
        for i, g in enumerate(graphs):
            xlsx.cell(ws, f"{get_column_letter(i+1)}5", g, italic=True, size=8)
        # строки-агрегаты + позиции
        def gv(w):
            return {
                "E": _n(w.accumulated_start), "F": _n(w.generated),
                "G": _n(w.received), "H": 0.0, "I": _n(w.processed),
                "J": _n(w.used), "K": 0.0, "L": 0.0,
                "M": _n(w.neutralized), "N": 0.0,
                "O": 0.0, "P": 0.0, "Q": 0.0,
                "R": _n(w.transferred_storage), "S": _n(w.transferred),
                "T": 0.0, "U": _n(D(w.placed_norm) + D(w.placed_over)),
                "V": _n(w.accumulated_end),
            }
        cols = "EFGHIJKLMNOPQRSTUV"
        r = 6
        self._agg_row(ws, r, "1", "ВСЕГО", self.ctx.wastes, gv, cols); r += 1
        for cl in (1, 2, 3, 4, 5):
            group = [w for w in self.ctx.wastes if int(w.hazard_class) == cl]
            if group:
                self._agg_row(ws, r, str(r - 4), f"Всего по {cl} классу опасности",
                              group, gv, cols); r += 1
        for w in self.ctx.wastes:
            g = gv(w)
            xlsx.cell(ws, f"A{r}", r - 4)
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            xlsx.cell(ws, f"C{r}", str(w.fkko_code).replace(" ", ""))
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            for c in cols:
                xlsx.cell(ws, f"{c}{r}", g[c])
            r += 1
        xlsx.widths(ws, {"A": 6, "B": 30, "C": 14, "D": 8,
                         **{get_column_letter(i): 10 for i in range(5, 23)}})
        xlsx.heights(ws, {2: 40, 3: 46})

    def _agg_row(self, ws, r, num, label, group, gv, cols):
        xlsx.cell(ws, f"A{r}", num, bold=True)
        xlsx.cell(ws, f"B{r}", label, bold=True, align="left")
        for c in cols:
            total = sum(gv(w)[c] for w in group)
            xlsx.cell(ws, f"{c}{r}", round(total, 6), bold=True)

    def _page3(self, wb):
        ws = wb.create_sheet("стр.3")
        o = self.ctx.organization
        xlsx.widths(ws, {"A": 60, "B": 12, "C": 20})
        xlsx.cell(ws, "A1", "Справочно указывается:", border=False, bold=True, align="left")
        xlsx.cell(ws, "A2", "количество эксплуатируемых объектов захоронения отходов",
                  border=False, align="left")
        xlsx.cell(ws, "B2", 0, border=False)
        xlsx.cell(ws, "A3", "в том числе не отвечающих установленным требованиям",
                  border=False, align="left")
        xlsx.cell(ws, "B3", 0, border=False)
        xlsx.cell(ws, "A4", "площадь, занимаемая всеми объектами захоронения, га",
                  border=False, align="left")
        xlsx.cell(ws, "B4", 0, border=False)
        xlsx.cell(ws, "A7", "Должностное лицо, ответственное за предоставление "
                            "статистической информации:", border=False, align="left")
        xlsx.cell(ws, "A9", o.director_position, border=False, align="left")
        xlsx.cell(ws, "C9", o.director_name, border=False, align="left")
        xlsx.cell(ws, "A10", "(должность)", border=False, italic=True, size=8, align="left")
        xlsx.cell(ws, "C10", "(Ф.И.О.)", border=False, italic=True, size=8, align="left")
        xlsx.cell(ws, "A12", f"E-mail: {o.email}    тел.: {o.phone}",
                  border=False, align="left")
        xlsx.cell(ws, "A14", "«____» __________ 20___ г.", border=False, align="left")
        xlsx.cell(ws, "A15", "(дата составления документа)", border=False,
                  italic=True, size=8, align="left")
