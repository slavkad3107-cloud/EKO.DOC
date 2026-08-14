"""Форма № 2-ТП (воздух) — сведения об охране атмосферного воздуха. Годовая,
за 2025 — до 22.01.2026, электронно с УКЭП через ЛКПП РПН. Код ОКУД 0609012.
Действующий НПА — Приказ Росстата от 08.11.2018 № 661 (не заменён).

Структура (по бланку — ПЯТЬ разделов): Титул (адресная часть, ОКУД 0609012)
+ Раздел 1 «Выбросы ЗВ в атмосферу, их очистка и утилизация» — строки 101-109,
графы бланка: А номер строки / 1 код ЗВ / Б вещество / 2 выбрасывается без
очистки — всего / 3 в т.ч. от организованных источников / 4 поступило на
очистные / 5 уловлено и обезврежено / 6 из них утилизировано / 7 всего
выброшено за год / 8 ПДВ / 9 ВСВ (нормативы — только по строкам 104-106,
в остальных «X»)
+ Раздел 2 (специфические вещества, вне перечня — код 8888)
+ Раздел 3 (источники загрязнения, строки 301-303)
+ Раздел 4 (выполнение мероприятий по уменьшению выбросов, строки 401-405)
+ Раздел 5 (выбросы от отдельных групп источников — сжигание топлива для
выработки электро-/теплоэнергии и технологические процессы, строки 501-505).

Данные — из ctx.pollutants (medium=air): всего выброшено = норматив+лимит+
сверх (гр. 7). Внутренние ключи граф исторические и НЕ совпадают с номерами
граф бланка (переименование сломало бы сохранённые переопределения):
g1 отходит (только XML) / g2 без очистки = гр.2 / g7 от организованных = гр.3
/ g3 на очистные = гр.4 / g4 уловлено = гр.5 / g5 утилизировано = гр.6 /
g6 выброшено = гр.7. Переопределения — ctx.extra['tp2_air']['cleaning'] =
{"104": {"g3": т, ..., "g7": т}}. Гр.3 бланка (g7) программа НЕ выдумывает:
без ввода печатается прочерк, а validate() предупреждает. ПДВ/ВСВ (гр.8/9) —
extra['tp2_air']['limits'] = {"104": {"pdv": т, "vsv": т}}. Источники —
extra['tp2_air']['sources'] = {"total": N, "organized": N, "allowed": т,
"fact": т}. Мероприятия Раздела 4 — extra['tp2_air']['measures'] =
[{"production", "name", "group", "done", "spent_year", "spent_prev",
"cut_expected", "cut_fact"}, …] (в бланке 5 строк — 401-405). Разбивка
Раздела 5 — extra['tp2_air']['groups'] = {"502": {"fuel": т, "tech": т}};
по Указаниям сумма fuel+tech строк 501-504 равна гр.7 строк 102/104/105/106.
Классификация кода ЗВ в строку 102-109 — приближённая (по коду/названию),
проверьте отнесение веществ к группам."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from lxml import etree

from ecodoc.core.models import Issue, Medium
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report

# Строки Раздела 1 по бланку: номер строки → (код ЗВ графы 1, текст графы Б).
_SECT1_ROWS = {
    101: ("0001", "Всего (102 + 103)"),
    102: ("0002", "в том числе: твёрдые"),
    103: ("0004", "газообразные и жидкие (104-109)"),
    104: ("0330", "из них: диоксид серы"),
    105: ("0337", "оксид углерода"),
    106: ("0301", "оксиды азота (в пересчёте на NO2)"),
    107: ("0401", "углеводороды (без летучих органических соединений)"),
    108: ("0006", "летучие органические соединения"),
    109: ("0005", "прочие газообразные и жидкие"),
}
# В бланке нормативы ПДВ/ВСВ (гр. 8-9) предусмотрены только для строк
# 104-106; в остальных строках напечатан знак «X».
_SECT1_LIMIT_ROWS = (104, 105, 106)
# Детальные строки (итоговые 101 и 103 считаются из них автоматически).
_SECT1_DETAIL = (102, 104, 105, 106, 107, 108, 109)

# Строки Раздела 5 по бланку: номер строки → (код ЗВ, наименование).
_SECT5_ROWS = {
    501: ("0002", "Твёрдые вещества"),
    502: ("0330", "Диоксид серы"),
    503: ("0337", "Оксид углерода"),
    504: ("0301", "Оксиды азота (в пересчёте на NO2)"),
    505: ("0007", "Углеводороды с учётом ЛОС (исключая метан)"),
}


@register
class TP2Air(Report):
    code = "2tp-air"
    title = "2-ТП (воздух)"

    def _extra(self) -> dict:
        return self.ctx.extra.get("tp2_air", {}) if isinstance(self.ctx.extra, dict) else {}

    def _air(self):
        """Вещества воздуха БЕЗ групп суммации.

        Коды 6xxx — это группы суммации («азота диоксид + серы диоксид»), а не
        отдельные вещества: их массы уже учтены в составляющих, и включение
        группы в отчёт даёт двойной счёт."""
        from ecodoc.core import sanitize
        return [p for p in self.ctx.pollutants
                if p.medium == Medium.AIR and not sanitize.is_sum_group(p.code)]

    def _sum_groups(self):
        from ecodoc.core import sanitize
        return [p for p in self.ctx.pollutants
                if p.medium == Medium.AIR and sanitize.is_sum_group(p.code)]

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not o.okpo:
            issues.append(Issue("warning", "ОКПО", "для 2-ТП обязателен код ОКПО"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self._air():
            issues.append(Issue("error", "выбросы", "нет веществ с выбросами в воздух"))
        groups = self._sum_groups()
        if groups:
            names = ", ".join(f"{p.code} {p.name}"[:40] for p in groups[:3])
            issues.append(Issue(
                "warning", "выбросы",
                f"из отчёта исключены группы суммации ({len(groups)}): {names}"
                f"{' …' if len(groups) > 3 else ''} — их массы уже учтены в "
                f"веществах, входящих в группу"))
        sec = self._section1()
        # Гр.3 бланка («в т.ч. от организованных») в модели данных источника
        # не имеет — без ввода печатается прочерк; молчать об этом нельзя,
        # иначе пользователь узнает о пустой графе от инспектора.
        if self._air() and all(sec[n]["g7"] is None for n in _SECT1_DETAIL):
            issues.append(Issue(
                "warning", "раздел 1",
                "не заполнена графа 3 «в том числе от организованных источников "
                "загрязнения» — в форме будет прочерк; укажите тоннаж в "
                "extra['tp2_air']['cleaning'][<строка>]['g7']"))
        bad_org = [n for n in _SECT1_DETAIL
                   if sec[n]["g7"] is not None and sec[n]["g7"] > sec[n]["g2"]]
        if bad_org:
            issues.append(Issue(
                "error", "раздел 1",
                f"графа 3 больше графы 2 в строках {', '.join(map(str, bad_org))}"
                " — выброс от организованных источников не может превышать весь"
                " выброс без очистки"))
        # Контрольное соотношение п.8 Указаний: гр.7 = гр.4 − гр.5 + гр.2
        # (внутренние ключи: g6 = g3 − g4 + g2).
        bad_ctl = [n for n in _SECT1_DETAIL
                   if sec[n]["g6"] != sec[n]["g3"] - sec[n]["g4"] + sec[n]["g2"]]
        if bad_ctl:
            issues.append(Issue(
                "warning", "раздел 1",
                "нарушено контрольное соотношение Указаний гр.7 = гр.4 − гр.5 "
                f"+ гр.2 в строках {', '.join(map(str, bad_ctl))} — проверьте "
                "данные очистки в extra['tp2_air']['cleaning']"))
        if len(self._extra().get("measures") or []) > 5:
            issues.append(Issue(
                "warning", "раздел 4",
                "в бланке Раздела 4 пять строк (401-405) — в форму попадут "
                "только первые пять мероприятий"))
        return issues

    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        e = self._extra()
        root = etree.Element("Форма2ТПВоздух", version="0.3", ОКУД="0609012")
        org = el(root, "Респондент")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "ОКПО", o.okpo)
        el(org, "ОКВЭД", o.okved)
        el(org, "ОКТМО", o.oktmo)
        el(root, "ОтчётныйГод", self.ctx.period.year)
        # Раздел 1 — агрегация по строкам 101-109 (графы бланка 2-7 + гр.3)
        r1 = el(root, "Раздел1")
        for row, vals in sorted(self._section1().items()):
            x = el(r1, "Строка", код=str(row))
            el(x, "КодЗВ", _SECT1_ROWS[row][0])
            el(x, "Отходит", _f(vals["g1"]))
            el(x, "БезОчистки", _f(vals["g2"]))
            el(x, "ОтОрганизованных",
               "-" if vals["g7"] is None else _f(vals["g7"]))
            el(x, "НаОчистные", _f(vals["g3"]))
            el(x, "УловленоОбезврежено", _f(vals["g4"]))
            el(x, "Утилизировано", _f(vals["g5"]))
            el(x, "Выброшено", _f(vals["g6"]))
        # Раздел 2 — специфические вещества
        r2 = el(root, "Раздел2")
        for p in self._air():
            x = el(r2, "Вещество", код=_code(p.code) or "8888")
            el(x, "Наименование", p.name)
            el(x, "Выброшено", _f(_tot(p)))
        # Раздел 3 — источники загрязнения (строка 301; количества — единицы)
        src = e.get("sources", {})
        total = sum((_tot(p) for p in self._air()), Decimal("0"))
        r3 = el(root, "Раздел3")
        x = el(r3, "Строка", код="301")
        el(x, "ВсегоИсточников", src.get("total", "-"))
        el(x, "ИзНихОрганизованных", src.get("organized", "-"))
        el(x, "РазрешённыйВыброс", src.get("allowed", "-"))
        el(x, "ФактическиВыброшено", _num(src.get("fact", total)))
        # Раздел 4 — мероприятия по уменьшению выбросов (401-405)
        r4 = el(root, "Раздел4")
        for i, m in enumerate((e.get("measures") or [])[:5]):
            x = el(r4, "Мероприятие", код=str(401 + i))
            el(x, "Производство", m.get("production", ""))
            el(x, "Наименование", m.get("name", ""))
            el(x, "ГруппаМероприятий", m.get("group", ""))
            el(x, "Выполнено", m.get("done", ""))
            el(x, "СредстваОтчётныйГод", m.get("spent_year", ""))
            el(x, "СредстваПрошлыйГод", m.get("spent_prev", ""))
            el(x, "СнижениеОжидаемое", m.get("cut_expected", ""))
            el(x, "СнижениеФактически", m.get("cut_fact", ""))
        # Раздел 5 — выбросы от отдельных групп источников (501-505)
        grp = e.get("groups") or {}
        r5 = el(root, "Раздел5")
        for row, (code, _label) in _SECT5_ROWS.items():
            g = grp.get(str(row)) or grp.get(row) or {}
            x = el(r5, "Строка", код=str(row))
            el(x, "КодЗВ", code)
            el(x, "ОтСжиганияТоплива", _num(g.get("fuel", "-")))
            el(x, "ОтТехнологическихПроцессов", _num(g.get("tech", "-")))
        write_tree(root, out_path)
        return out_path

    # агрегация выбросов в 9 строк 101-109 с графами потока очистки
    def _section1(self) -> dict:
        e = self._extra()
        rows = {n: {f"g{i}": Decimal("0") for i in range(1, 7)}
                for n in _SECT1_ROWS}
        for n in rows:
            # гр.3 бланка: источника в модели нет — None означает прочерк,
            # ноль здесь был бы выдуманным «организованных источников нет»
            rows[n]["g7"] = None
        for p in self._air():
            emitted = _tot(p)          # гр.7 бланка — всего выброшено
            row = _air_row(p)
            # без данных ГОУ: отходит(g1)=без очистки(g2)=выброшено(g6)
            rows[row]["g1"] += emitted
            rows[row]["g2"] += emitted
            rows[row]["g6"] += emitted
        # применить фактические данные очистки, если заданы (по строке)
        for row, ov in (e.get("cleaning") or {}).items():
            try:
                rr = rows[int(row)]
            except (KeyError, ValueError):
                continue
            for i in range(1, 8):
                if f"g{i}" in ov:
                    rr[f"g{i}"] = D(ov[f"g{i}"])
        # 103 = сумма газообразных/жидких (104-109); 101 = 102 + 103
        for g in ("g1", "g2", "g3", "g4", "g5", "g6"):
            rows[103][g] = sum(rows[n][g] for n in (104, 105, 106, 107, 108, 109))
            rows[101][g] = rows[102][g] + rows[103][g]
        # гр.3 (g7) суммируется только по заполненным строкам; если её не
        # вводили нигде — в итогах тоже прочерк, а не выдуманный ноль
        v103 = [rows[n]["g7"] for n in (104, 105, 106, 107, 108, 109)
                if rows[n]["g7"] is not None]
        rows[103]["g7"] = sum(v103, Decimal("0")) if v103 else None
        v101 = [rows[n]["g7"] for n in (102, 103) if rows[n]["g7"] is not None]
        rows[101]["g7"] = sum(v101, Decimal("0")) if v101 else None
        return rows

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        self._title(wb)
        self._sect1(wb)
        self._sect2(wb)
        self._sect3(wb)
        self._sect4(wb)
        self._sect5(wb)
        return xlsx.save(wb, out_path)

    def _title(self, wb):
        o = self.ctx.organization
        ws = wb.create_sheet("Титул")
        xlsx.widths(ws, {"A": 34, "B": 52})
        rows = [
            ("СВЕДЕНИЯ ОБ ОХРАНЕ АТМОСФЕРНОГО ВОЗДУХА (2-ТП (воздух))", ""),
            ("Форма по ОКУД / приказ Росстата", "0609012 / № 661 от 08.11.2018"),
            ("Отчётный год", self.ctx.period.year),
            ("Организация", o.name),
            ("ОКПО / ОКВЭД / ОКТМО", f"{o.okpo} / {o.okved} / {o.oktmo}"),
            ("ИНН / ОГРН", f"{o.inn} / {o.ogrn}"),
            ("Срок (за 2025)", "до 22.01.2026, электронно с УКЭП через ЛКПП РПН"),
        ]
        for i, (k, v) in enumerate(rows, 1):
            a = ws.cell(row=i, column=1, value=k)
            ws.cell(row=i, column=2, value=v)
            if i == 1:
                a.font = xlsx.BOLD

    def _sect1(self, wb):
        """Раздел 1 по бланку: графы А, 1, Б, 2-9 (столбцы A-K).

        Состав и порядок граф — из официального бланка (шапка «А 1 Б 2 3 4» /
        «А 5 6 7 8 9»): код ЗВ, «в т.ч. от организованных», ПДВ/ВСВ; графы
        «отходит от источников» в бланке нет."""
        ws = wb.create_sheet("Раздел 1")
        e = self._extra()
        xlsx.widths(ws, {"A": 7, "B": 11, "C": 28, "D": 13, "E": 16, "F": 13,
                         "G": 14, "H": 13, "I": 14, "J": 12, "K": 12})
        xlsx.merge(ws, "A1:K1", "Раздел 1. Выбросы загрязняющих веществ в "
                   "атмосферу, их очистка и утилизация (код по ОКЕИ: "
                   "тонна — 168)", bold=True, border=False)
        heads = ["Номер строки", "Код загрязняющего вещества",
                 "Загрязняющие вещества",
                 "Выбрасывается без очистки — всего",
                 "в том числе от организованных источников загрязнения",
                 "Поступило на очистные сооружения — всего",
                 "Из поступивших на очистку — уловлено и обезврежено, всего",
                 "из них утилизировано",
                 "Всего выброшено в атмосферу за отчётный год",
                 "Установленный норматив на отчётный год: ПДВ, т/год",
                 "временно согласованный выброс (ВСВ), т/год"]
        for i, h in enumerate(heads):
            xlsx.cell(ws, f"{chr(65 + i)}3", h, bold=True, fill=True, size=9)
        # служебная строка номеров граф — по ней инспектор/ЛКПП сопоставляет
        # столбцы с бланком (в бланке буквально: «А 1 Б 2 3 4 5 6 7 8 9»)
        for i, num in enumerate(("А", "1", "Б", "2", "3", "4", "5", "6", "7",
                                 "8", "9")):
            xlsx.cell(ws, f"{chr(65 + i)}4", num, size=9)
        limits = e.get("limits") or {}
        sec = self._section1()
        r = 5
        for row, (zv_code, label) in _SECT1_ROWS.items():
            v = sec[row]
            xlsx.cell(ws, f"A{r}", row)
            xlsx.cell(ws, f"B{r}", zv_code)
            xlsx.cell(ws, f"C{r}", label, align="left")
            xlsx.cell(ws, f"D{r}", float(v["g2"]))
            xlsx.cell(ws, f"E{r}", "-" if v["g7"] is None else float(v["g7"]))
            xlsx.cell(ws, f"F{r}", float(v["g3"]))
            xlsx.cell(ws, f"G{r}", float(v["g4"]))
            xlsx.cell(ws, f"H{r}", float(v["g5"]))
            xlsx.cell(ws, f"I{r}", float(v["g6"]))
            lim = limits.get(str(row)) or limits.get(row) or {}
            if row in _SECT1_LIMIT_ROWS:
                xlsx.cell(ws, f"J{r}", lim.get("pdv", "-"))
                xlsx.cell(ws, f"K{r}", lim.get("vsv", "-"))
            else:
                # в бланке нормативы по этим строкам не предусмотрены
                xlsx.cell(ws, f"J{r}", "X")
                xlsx.cell(ws, f"K{r}", "X")
            r += 1

    def _sect2(self, wb):
        ws = wb.create_sheet("Раздел 2 (специфич.)")
        xlsx.widths(ws, {"A": 10, "B": 44, "C": 20})
        xlsx.merge(ws, "A1:C1", "Раздел 2. Выброс в атмосферу специфических "
                   "загрязняющих веществ (вне перечня — код 8888), тонн",
                   bold=True, border=False)
        xlsx.header_row(ws, 3, ["Код ЗВ", "Загрязняющее вещество", "Выброшено за год, т"])
        r = 4
        for p in self._air():
            xlsx.data_row(ws, r, [_code(p.code) or "8888", p.name, float(_tot(p))])
            r += 1

    def _sect3(self, wb):
        ws = wb.create_sheet("Раздел 3 (источники)")
        e = self._extra()
        xlsx.widths(ws, {"A": 40, "B": 18, "C": 18, "D": 18, "E": 18})
        xlsx.merge(ws, "A1:E1", "Раздел 3. Источники загрязнения атмосферы",
                   bold=True, border=False)
        xlsx.header_row(ws, 3, ["Показатель", "Всего источников",
                                "из них организованных", "Разрешённый выброс, т",
                                "Фактически выброшено, т"])
        src = e.get("sources", {})
        total = float(sum(_tot(p) for p in self._air()))
        xlsx.data_row(ws, 4, ["301 Всего стационарных источников",
                              src.get("total", ""), src.get("organized", ""),
                              src.get("allowed", ""), src.get("fact", total)])
        xlsx.data_row(ws, 5, ["302 с установленными нормативами ПДВ", "", "", "", ""])
        xlsx.data_row(ws, 6, ["303 с установленными ВСВ", "", "", "", ""])

    def _sect4(self, wb):
        """Раздел 4 по бланку: мероприятия по уменьшению выбросов.

        Графы бланка: А номер строки / Б производство и оборудование /
        В наименование мероприятия / 1 группа / 2 оценка выполнения («1»
        выполнено, «0» нет) / 3-4 освоено средств за отчётный и прошлый год,
        тыс. руб. / 5-6 уменьшение выброса ожидаемое и фактическое, т.
        В бланке ровно пять строк 401-405 — печатаем их всегда, пустыми при
        отсутствии мероприятий (данные программа не выдумывает)."""
        ws = wb.create_sheet("Раздел 4 (мероприятия)")
        xlsx.widths(ws, {"A": 7, "B": 24, "C": 26, "D": 11, "E": 14, "F": 14,
                         "G": 13, "H": 14, "I": 12})
        xlsx.merge(ws, "A1:I1", "Раздел 4. Выполнение мероприятий по "
                   "уменьшению выбросов загрязняющих веществ в атмосферу "
                   "(коды по ОКЕИ: единица — 642; тысяча рублей — 384; "
                   "тонна — 168)", bold=True, border=False)
        heads = ["Номер строки",
                 "Наименование промышленного производства и технологического "
                 "оборудования",
                 "Наименование мероприятия",
                 "Группа мероприятий",
                 "Оценка выполнения (начато в отчётном году и выполнено — «1», "
                 "по остальным — «0»)",
                 "Использовано (освоено) средств за отчётный год, тыс. руб.",
                 "за прошлый год, тыс. руб.",
                 "Уменьшение выбросов после проведения мероприятий — ожидаемое "
                 "(расчётное), т",
                 "фактически, т"]
        for i, h in enumerate(heads):
            xlsx.cell(ws, f"{chr(65 + i)}3", h, bold=True, fill=True, size=9)
        for i, num in enumerate(("А", "Б", "В", "1", "2", "3", "4", "5", "6")):
            xlsx.cell(ws, f"{chr(65 + i)}4", num, size=9)
        measures = self._extra().get("measures") or []
        r = 5
        for i, row in enumerate(range(401, 406)):
            m = measures[i] if i < len(measures) else {}
            xlsx.cell(ws, f"A{r}", row)
            xlsx.cell(ws, f"B{r}", m.get("production", ""), align="left")
            xlsx.cell(ws, f"C{r}", m.get("name", ""), align="left")
            xlsx.cell(ws, f"D{r}", m.get("group", ""))
            xlsx.cell(ws, f"E{r}", m.get("done", ""))
            xlsx.cell(ws, f"F{r}", m.get("spent_year", ""))
            xlsx.cell(ws, f"G{r}", m.get("spent_prev", ""))
            xlsx.cell(ws, f"H{r}", m.get("cut_expected", ""))
            xlsx.cell(ws, f"I{r}", m.get("cut_fact", ""))
            r += 1

    def _sect5(self, wb):
        """Раздел 5 по бланку: выбросы от отдельных групп источников.

        Фиксированные строки 501-505 (коды 0002/0330/0337/0301/0007), графы:
        3 — от сжигания топлива (для выработки электро- и теплоэнергии),
        4 — от технологических и других процессов. Разбивки по видам
        процессов в модели данных нет — без ввода печатается прочерк."""
        ws = wb.create_sheet("Раздел 5 (группы источн.)")
        xlsx.widths(ws, {"A": 7, "B": 11, "C": 42, "D": 20, "E": 20})
        xlsx.merge(ws, "A1:E1", "Раздел 5. Выбросы загрязняющих веществ в "
                   "атмосферный воздух от отдельных групп источников "
                   "загрязнения (тонн)", bold=True, border=False)
        heads = ["Номер строки", "Код загрязняющего вещества",
                 "Загрязняющие вещества",
                 "Выброс от сжигания топлива (для выработки электро- и "
                 "теплоэнергии)",
                 "Выброс от технологических и других процессов"]
        for i, h in enumerate(heads):
            xlsx.cell(ws, f"{chr(65 + i)}3", h, bold=True, fill=True, size=9)
        for i, num in enumerate(("А", "1", "2", "3", "4")):
            xlsx.cell(ws, f"{chr(65 + i)}4", num, size=9)
        grp = self._extra().get("groups") or {}
        r = 5
        for row, (code, label) in _SECT5_ROWS.items():
            g = grp.get(str(row)) or grp.get(row) or {}
            xlsx.cell(ws, f"A{r}", row)
            xlsx.cell(ws, f"B{r}", code)
            xlsx.cell(ws, f"C{r}", label, align="left")
            xlsx.cell(ws, f"D{r}", g.get("fuel", "-"))
            xlsx.cell(ws, f"E{r}", g.get("tech", "-"))
            r += 1


def _f(v) -> str:
    return f"{float(v):.3f}"


def _num(v) -> str:
    """Число — в формате формы (3 знака), всё остальное (прочерк) — как есть."""
    try:
        return _f(v)
    except (TypeError, ValueError):
        return str(v)


def _code(value) -> str:
    """Код ЗВ в официальном виде: четыре цифры с ведущим нулём."""
    from ecodoc.core import sanitize
    return sanitize.norm_code(value) or str(value or "")


def _tot(p) -> Decimal:
    return D(p.mass_norm) + D(p.mass_limit) + D(p.mass_over)


# Классификация кода ЗВ в строку 102-109 Раздела 1 (Указания к форме № 661).
# Коды нормализуются до четырёх цифр, иначе «301» из документа не находился
# и вещество молча уезжало в строку 109 «прочие».
_AIR_ROW_BY_CODE = {
    "0330": 104, "0333": 104,          # диоксид серы, сероводород → сернистые
    "3003": 104,                       # «диоксид серы» из старых томов ПДВ
    "0337": 105, "3332": 105,          # оксид углерода (3332 — старый код)
    "0301": 106, "0304": 106,          # оксиды азота (в пересчёте на NO2)
    "3004": 106,                       # «диоксид азота» из старых томов ПДВ
    # твёрдые: взвешенные вещества, сажа, пыли неорганические и абразивная
    "2902": 102, "0328": 102, "2907": 102, "2908": 102, "2909": 102,
    "2930": 102, "0123": 102, "0143": 102, "0203": 102, "0316": 102,
    # углеводороды (без ЛОС): предельные C1-C5, C6-C10, C12-C19, керосин
    "2704": 107, "2732": 107, "2754": 107, "0410": 107, "0415": 107,
    "0416": 107, "0417": 107,
    # летучие органические соединения
    "1210": 108, "1325": 108, "0616": 108, "0621": 108, "1401": 108,
    "1042": 108, "1052": 108, "1061": 108, "1119": 108, "1715": 108,
}


def _air_row(p) -> int:
    code = _code(getattr(p, "code", ""))
    if code in _AIR_ROW_BY_CODE:
        return _AIR_ROW_BY_CODE[code]
    name = (getattr(p, "name", "") or "").lower()
    if any(w in name for w in ("взвеш", "пыль", "сажа", "твёрд", "тверд", "зола")):
        return 102
    # SO2/CO/NOx обязаны попадать в строки 104-106 и при нестандартном коде:
    # в реальных базах встречаются «3003 диоксид серы», «3332 оксид углерода»
    # и т.п. — без этих веток они уезжали в 109 «прочие»
    if any(w in name for w in ("серы диоксид", "сера диоксид", "диоксид серы",
                               "сернист")):
        return 104
    if any(w in name for w in ("углерода оксид", "углерод оксид",
                               "оксид углерода", "угарный")):
        return 105
    if any(w in name for w in ("азота диоксид", "диоксид азота", "оксид азота",
                               "азот (ii) оксид", "оксиды азота")):
        return 106
    if any(w in name for w in ("углеводород", "метан", "пропан", "бутан",
                               "бензин", "керосин", "алкан", "уайт-спирит",
                               "дизельн")):
        return 107
    if any(w in name for w in ("лос", "летуч", "ксилол", "толуол", "ацетон", "спирт")):
        return 108
    return 109  # прочие газообразные/жидкие
