"""Форма № 2-ТП (воздух) — сведения об охране атмосферного воздуха. Годовая,
за 2025 — до 22.01.2026, электронно с УКЭП через ЛКПП РПН. Код ОКУД 0609012.
Действующий НПА — Приказ Росстата от 08.11.2018 № 661 (не заменён).

Структура (по бланку): Титул (адресная часть, ОКУД 0609012) + Раздел 1
(выбросы, их очистка и утилизация — агрегация веществ в 9 строк 101-109 с
графами потока очистки 1-6: отходит / без очистки / на очистные / уловлено-
обезврежено / утилизировано / выброшено) + Раздел 2 (специфические вещества,
вне перечня — код 8888) + Раздел 3 (источники загрязнения).

Данные — из ctx.pollutants (medium=air): всего выброшено = норматив+лимит+сверх
(графа 6). Данные очистки (графы 1-5) — из ctx.extra['tp2_air']['cleaning'] =
{"104": {"g3": т, "g4": т, ...}}; источники — extra['tp2_air']['sources'] =
{"total": N, "organized": N, "allowed": т, "fact": т}. Без данных очистки:
отходит(1)=без очистки(2)=выброшено(6). Строки 101 и 103 считаются автоматически.
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


@register
class TP2Air(Report):
    code = "2tp-air"
    title = "2-ТП (воздух)"

    def _air(self):
        return [p for p in self.ctx.pollutants if p.medium == Medium.AIR]

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
        return issues

    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        root = etree.Element("Форма2ТПВоздух", version="0.2", ОКУД="0609012")
        org = el(root, "Респондент")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "ОКПО", o.okpo)
        el(org, "ОКВЭД", o.okved)
        el(org, "ОКТМО", o.oktmo)
        el(root, "ОтчётныйГод", self.ctx.period.year)
        # Раздел 1 — агрегация по строкам 101-109 (графы потока очистки 1-6)
        r1 = el(root, "Раздел1")
        for row, vals in sorted(self._section1().items()):
            x = el(r1, "Строка", код=str(row))
            el(x, "Отходит", _f(vals["g1"]))
            el(x, "БезОчистки", _f(vals["g2"]))
            el(x, "НаОчистные", _f(vals["g3"]))
            el(x, "УловленоОбезврежено", _f(vals["g4"]))
            el(x, "Утилизировано", _f(vals["g5"]))
            el(x, "Выброшено", _f(vals["g6"]))
        # Раздел 2 — специфические вещества
        r2 = el(root, "Раздел2")
        for p in self._air():
            x = el(r2, "Вещество", код=p.code or "8888")
            el(x, "Наименование", p.name)
            el(x, "Выброшено", _f(_tot(p)))
        write_tree(root, out_path)
        return out_path

    # агрегация выбросов в 9 строк 101-109 с графами потока очистки 1-6
    def _section1(self) -> dict:
        e = self.ctx.extra.get("tp2_air", {}) if isinstance(self.ctx.extra, dict) else {}
        rows = {n: {f"g{i}": Decimal("0") for i in range(1, 7)}
                for n in (101, 102, 103, 104, 105, 106, 107, 108, 109)}
        for p in self._air():
            emitted = _tot(p)          # графа 6 — всего выброшено
            row = _air_row(p)
            # без данных ГОУ: отходит(1)=выброшено, без очистки(2)=выброшено
            rows[row]["g1"] += emitted
            rows[row]["g2"] += emitted
            rows[row]["g6"] += emitted
        # применить фактические данные очистки, если заданы (по строке)
        for row, ov in (e.get("cleaning") or {}).items():
            try:
                rr = rows[int(row)]
            except (KeyError, ValueError):
                continue
            for i in range(1, 7):
                if f"g{i}" in ov:
                    rr[f"g{i}"] = D(ov[f"g{i}"])
        # 103 = сумма газообразных/жидких (104-109); 101 = 102 + 103
        for g in ("g1", "g2", "g3", "g4", "g5", "g6"):
            rows[103][g] = sum(rows[n][g] for n in (104, 105, 106, 107, 108, 109))
            rows[101][g] = rows[102][g] + rows[103][g]
        return rows

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        self._title(wb)
        self._sect1(wb)
        self._sect2(wb)
        self._sect3(wb)
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
        ws = wb.create_sheet("Раздел 1")
        xlsx.widths(ws, {"A": 9, "B": 40, **{c: 15 for c in "CDEFGH"}})
        xlsx.merge(ws, "A1:H1", "Раздел 1. Выбросы загрязняющих веществ в атмосферу, "
                   "их очистка и утилизация (тонн)", bold=True, border=False)
        heads = ["№ строки", "Загрязняющие вещества", "Отходит от источников",
                 "Выброшено без очистки", "Поступило на очистные",
                 "Уловлено и обезврежено", "Из них утилизировано",
                 "Всего выброшено за год"]
        for i, h in enumerate(heads):
            xlsx.cell(ws, f"{chr(65+i)}3", h, bold=True, fill=True, size=9)
        labels = {101: "Всего", 102: "в т.ч. твёрдые",
                  103: "газообразные и жидкие — всего", 104: "диоксид серы",
                  105: "оксид углерода", 106: "оксиды азота (в пересч. на NO2)",
                  107: "углеводороды (без ЛОС)", 108: "ЛОС",
                  109: "прочие газообразные и жидкие"}
        sec = self._section1()
        r = 4
        for row in (101, 102, 103, 104, 105, 106, 107, 108, 109):
            v = sec[row]
            xlsx.cell(ws, f"A{r}", row)
            xlsx.cell(ws, f"B{r}", labels[row], align="left")
            for i, g in enumerate(("g1", "g2", "g3", "g4", "g5", "g6")):
                xlsx.cell(ws, f"{chr(67+i)}{r}", float(v[g]))
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
            xlsx.data_row(ws, r, [p.code or "8888", p.name, float(_tot(p))])
            r += 1

    def _sect3(self, wb):
        ws = wb.create_sheet("Раздел 3 (источники)")
        e = self.ctx.extra.get("tp2_air", {}) if isinstance(self.ctx.extra, dict) else {}
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


def _f(v) -> str:
    return f"{float(v):.3f}"


def _tot(p) -> Decimal:
    return D(p.mass_norm) + D(p.mass_limit) + D(p.mass_over)


# классификация кода ЗВ в строку 102-109 Раздела 1
_AIR_ROW_BY_CODE = {
    "0330": 104,                       # диоксид серы
    "0337": 105,                       # оксид углерода
    "0301": 106, "0304": 106, "0304 ": 106,  # оксиды азота
    "2902": 102, "0328": 102, "2908": 102, "2907": 102,  # твёрдые
}


def _air_row(p) -> int:
    code = str(getattr(p, "code", "")).strip()
    if code in _AIR_ROW_BY_CODE:
        return _AIR_ROW_BY_CODE[code]
    name = (getattr(p, "name", "") or "").lower()
    if any(w in name for w in ("взвеш", "пыль", "сажа", "твёрд", "тверд", "зола")):
        return 102
    if any(w in name for w in ("углеводород", "метан", "пропан", "бутан", "бензин")):
        return 107
    if any(w in name for w in ("лос", "летуч", "ксилол", "толуол", "ацетон", "спирт")):
        return 108
    return 109  # прочие газообразные/жидкие
