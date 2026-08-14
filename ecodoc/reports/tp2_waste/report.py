"""Форма № 2-ТП (отходы) — сведения об образовании, обработке, утилизации,
обезвреживании, размещении отходов производства и потребления (слова
«транспортировании» в названии действующей формы нет). Годовая: ТО
Росприроднадзора — 1 февраля (за 2025 — до 02.02.2026), Росприроднадзору —
15 марта; подача через ЛКПП РПН. Код формы по ОКУД 0609013.

ДЕЙСТВУЮЩАЯ редакция — Приказ Росстата от 06.11.2025 № 614 (начиная с отчёта
за 2025); приказы № 627 от 09.10.2020 и № 698 от 13.11.2020 утратили силу.

Структура: стр.1 (титул с блоком «Предоставляют/Сроки/Приказ» + код-строка);
стр.2 — Раздел I (движение отходов, 29 граф); стр.3 — Раздел II (регоператоры
ТКО: собственные 29 граф тремя подтаблицами гр.1–9 / 10–17 / 18–29 с шапкой
А|Б|В|Г, данные из extra.tko_operators; если организация не регоператор —
шапка печатается целиком, как в принятых отчётах, с пояснением под ней) +
Раздел III (фиксированные строки 11–31, значения из
extra.disposal_objects_s3) + подпись. Код ФККО в графе В печатается в
каноническом виде с пробелами («7 33 100 01 72 4»), как в печати ЛКПП;
в XML (WST_CODE) — без пробелов. Точность массы — по классу опасности:
I–III = 3 знака, IV–V = 1 знак; баланс проверяется. XML — конверт «Модуля
природопользователя» (DATA_PACKET_NI, DocType=3); XSD Модуля за 2025 не
сверен — схем в открытом доступе нет.

Данные — из ctx.wastes (та же модель, что и учёт движения №1028).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ecodoc.core.models import Issue
from ecodoc.core.money import D
from ecodoc.core.registry import register
# единый формат кода ФККО с пробелами — тот же хелпер, что и в «табличке
# по отходам», чтобы один код в двух документах не печатался по-разному
from ecodoc.core.waste_table import _fkko_spaced
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import _is_nvos_code as _is_nvos, data_packet_ni, el, write_tree
from ecodoc.reports.base import Report


# Раздел III формы (приказ Росстата № 614): фиксированные строки 11–31.
# Значения подставляются из ctx.extra['disposal_objects_s3'] = {"11": 2, …};
# незаполненные печатаются прочерком, как в принятых отчётах. Формулировки —
# дословно по печатной форме ЛКПП (в бланке «из них ТКО», не расшифровка).
_S3_ROWS = [
    (11, "Количество эксплуатируемых респондентом объектов захоронения отходов, ед"),
    (12, "из них ТКО, ед"),
    (13, "Количество эксплуатируемых респондентом объектов хранения отходов, ед"),
    (14, "Количество эксплуатируемых респондентом объектов захоронения отходов, "
         "отвечающих установленным требованиям, ед"),
    (15, "из них ТКО, ед"),
    (16, "Количество эксплуатируемых респондентом объектов хранения отходов, "
         "отвечающих установленным требованиям, ед"),
    (17, "Вместимость эксплуатируемых респондентом объектов захоронения отходов "
         "согласно проектной документации, т"),
    (18, "из них ТКО, т"),
    (19, "Остаточная вместимость эксплуатируемых респондентом объектов "
         "захоронения отходов, т"),
    (20, "из них ТКО, т"),
    (21, "Вместимость эксплуатируемых респондентом объектов захоронения отходов "
         "согласно проектной документации, м3"),
    (22, "из них ТКО, м3"),
    (23, "Остаточная вместимость эксплуатируемых респондентом объектов "
         "захоронения отходов, м3"),
    (24, "из них ТКО, м3"),
    (25, "Вместимость эксплуатируемых респондентом объектов хранения отходов "
         "согласно проектной документации, т"),
    (26, "Остаточная вместимость эксплуатируемых респондентом объектов "
         "хранения отходов, т"),
    (27, "Вместимость эксплуатируемых респондентом объектов хранения отходов "
         "согласно проектной документации, м3"),
    (28, "Остаточная вместимость эксплуатируемых респондентом объектов "
         "хранения отходов, м3"),
    (29, "Площадь, занимаемая эксплуатируемыми респондентом объектами "
         "захоронения отходов, га"),
    (30, "из них ТКО, га"),
    (31, "Площадь, занимаемая эксплуатируемыми респондентом объектами "
         "хранения отходов, га"),
]

# Заголовок Раздела II — дословно по печатной форме ЛКПП (приказ № 614).
_S2_TITLE = ("Раздел II. Сведения об образовании, обработке, утилизации, "
             "обезвреживании, размещении отходов производства и потребления, "
             "представляемые региональными операторами, осуществляющими "
             "деятельность с твердыми коммунальными отходами, тонна")

# 29 граф Раздела II (краткие подписи, сверены с таблицами гр.1–9 / 10–17 /
# 18–29 печатной формы ЛКПП). У Раздела II графы СВОИ — ТКО-показатели
# регоператора, с графами Раздела I они не совпадают.
_G29_II = [
    (1, "Наличие ТКО на начало отчетного года"),
    (2, "Образование ТКО за отчетный год"),
    (3, "Поступление ТКО к региональному оператору от других хозяйствующих "
        "субъектов, населения и субъектов РФ: всего ТКО"),
    (4, "из гр.3: ТКО, образованных в жилых помещениях в субъекте РФ"),
    (5, "из гр.3: ТКО, образованных в других субъектах РФ (по соглашению)"),
    (6, "Образование ТКО после обработки за отчетный год: всего"),
    (7, "из гр.6: на объектах обработки регионального оператора"),
    (8, "из гр.6: на объектах оператора, передающего ТКО после обработки "
        "региональному оператору"),
    (9, "из гр.6: на объектах оператора, не передающего ТКО после обработки "
        "региональному оператору"),
    (10, "Обработано ТКО: всего"),
    (11, "из них ТКО, образованных в жилых помещениях"),
    (12, "Утилизировано ТКО: всего"),
    (13, "из гр.12: для повторного применения (рециклинг)"),
    (14, "из гр.12: энергетическая утилизация"),
    (15, "Обезврежено ТКО"),
    (16, "Передача ТКО другим операторам для обработки: всего"),
    (17, "из них в другие субъекты РФ"),
    (18, "Передача ТКО другим операторам для утилизации: всего"),
    (19, "из гр.18: в другие субъекты РФ"),
    (20, "из гр.18: на энергетическую утилизацию"),
    (21, "из гр.18: в другие субъекты РФ на энергетическую утилизацию"),
    (22, "Передача ТКО другим операторам для обезвреживания: всего"),
    (23, "из них в другие субъекты РФ"),
    (24, "Передача ТКО другим операторам для захоронения: всего"),
    (25, "из них в другие субъекты РФ"),
    (26, "Хранение отходов после обработки ТКО"),
    (27, "Захоронение ТКО на эксплуатируемых объектах: всего"),
    (28, "из них ТКО, образованных в жилых помещениях"),
    (29, "Наличие ТКО на конец отчетного года"),
]

# разбиение граф Раздела II на три подтаблицы — как в печатной форме
# (иначе 29 граф не помещаются на лист)
_S2_SPLITS = [(1, 9), (10, 17), (18, 29)]

# обратная совместимость: старые ключи extra['tko_operators'] → номер графы
_S2_LEGACY = {3: "received", 10: "processed", 27: "placed"}


def _s2_val(op: dict, num: int):
    """Значение графы Раздела II: op['gN'], иначе старый ключ, иначе «-».

    Ничего не выдумываем: для графы без источника печатается прочерк,
    как в принятых отчётах."""
    v = op.get(f"g{num}")
    if v in (None, ""):
        v = op.get(_S2_LEGACY.get(num, ""), "")
    return v if v not in (None, "") else "-"


def _n(v) -> float:
    return float(D(v))


def _f6(v) -> str:
    return f"{_n(v):.6f}"


def _prec(hazard_class) -> int:
    """Точность массы по Указаниям: I–III класс — 3 знака, IV–V — 1 знак."""
    try:
        return 3 if int(hazard_class) <= 3 else 1
    except (TypeError, ValueError):
        return 1


def _fmt_class(v, hazard_class) -> str:
    return f"{_n(v):.{_prec(hazard_class)}f}"


def _round_class(v, hazard_class) -> float:
    return round(_n(v), _prec(hazard_class))


def _is_tko(fkko) -> bool:
    """ТКО — блок ФККО «7 3…» (передаётся региональному оператору, графа 14).
    Единое определение для всех форм — core/waste_agg.is_tko."""
    from ecodoc.core.waste_agg import is_tko
    return is_tko(fkko)


@register
class TP2Waste(Report):
    code = "2tp-waste"
    title = "2-ТП (отходы)"

    def validate(self) -> list[Issue]:
        from ecodoc.core.validators import inn_valid, ogrn_valid
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        elif not inn_valid(o.inn):
            issues.append(Issue("error", "ИНН", f"ИНН {o.inn} не проходит проверку — опечатка"))
        if not o.okpo:
            issues.append(Issue("warning", "ОКПО", "для 2-ТП обязателен код ОКПО"))
        # --- preflight под загрузку в ЛКПП РПН ---
        if not o.ogrn:
            kind = "ОГРНИП" if o.is_individual else "ОГРН"
            issues.append(Issue("error", kind,
                                f"не указан {kind} — обязателен для сверки с ЕГРЮЛ/ЕГРИП "
                                "при загрузке в ЛКПП"))
        elif not ogrn_valid(o.ogrn):
            issues.append(Issue("warning", "ОГРН", f"ОГРН {o.ogrn} не проходит проверку — сверьте"))
        okt = (o.oktmo or "").strip()
        if not okt:
            issues.append(Issue("error", "ОКТМО", "не указан ОКТМО территории (Код по ОКТМО)"))
        elif len(okt) not in (8, 11) or not okt.isdigit():
            issues.append(Issue("warning", "ОКТМО",
                                f"ОКТМО «{okt}» — ожидается 8 или 11 цифр; проверьте, что это "
                                "именно ОКТМО, а не ОКАТО"))
        if not any(_is_nvos(ob.code) for ob in self.ctx.objects):
            issues.append(Issue("warning", "объект",
                                "нет кода объекта НВОС (напр. 41-0247-000123-П) — если объект "
                                "на учёте, укажите код, иначе РПН отклонит «объект не стоит на учёте»"))
        # баланс масс по каждому отходу (наличие на конец = приход − расход)
        for w in self.ctx.wastes:
            bal = (D(w.accumulated_start) + D(w.accumulated_start_nakopl)
                   + D(w.generated) + D(w.received)
                   - D(w.used) - D(w.neutralized) - D(w.transferred)
                   - D(w.placed_norm) - D(w.placed_over))
            if abs(bal - D(w.accumulated_end)) > D("0.001"):
                issues.append(Issue(
                    "warning", f"баланс/{w.fkko_code}",
                    f"наличие на конец {D(w.accumulated_end)} ≠ расчётный баланс "
                    f"{bal} (гр.29 = приход − расход)"))
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
        el(rpt, "RPN_CODE", str(e.get("rpn_to", "") or "1"))
        el(rpt, "ROSPRIR", e.get("rospr", ""))
        el(rpt, "FNAME", o.name)
        el(rpt, "SNAME", o.short_name or o.name)
        el(rpt, "ADDR_STR", o.address)
        el(rpt, "OGRN", o.ogrn)
        el(rpt, "INN", o.inn)
        el(rpt, "KPP", o.kpp)
        el(rpt, "OKPO", o.okpo)
        el(rpt, "OFFICIAL", o.official_title)
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
            hc = w.hazard_class
            fact = el(rpt, "RPT_2TP_WASTE_FACT")
            el(fact, "NONE_FKKO_NAME", w.name)
            el(fact, "WST_CODE", str(w.fkko_code).replace(" ", ""))
            el(fact, "WSTYPE", hc)
            # наличие на начало = хранение + накопление
            el(fact, "TP2_BP_ACCUM_WASTE",
               _fmt_class(D(w.accumulated_start) + D(w.accumulated_start_nakopl), hc))
            el(fact, "TP2_FORMING", _fmt_class(w.generated, hc))
            el(fact, "TP2_ARRIVAL", _fmt_class(w.received, hc))
            el(fact, "TP2_TRANSF", _fmt_class(w.transferred, hc))
            # TR_* = ПЕРЕДАНО другим (для утилизации/обезвреживания/захоронения),
            # а не собственные утилизация/обезвреживание
            el(fact, "TP2_TR_ISPOTX", _fmt_class(w.transferred_util, hc))
            el(fact, "TP2_TR_SOTX", _fmt_class(w.transferred_neutral, hc))
            el(fact, "TP2_TR_DISP", _fmt_class(w.transferred_burial, hc))
            el(fact, "TP2_RAZM", _fmt_class(D(w.placed_norm) + D(w.placed_over), hc))
            el(fact, "TP2_RAZM_STOR", "0.0")
            el(fact, "TP2_ACCUM_WASTE", _fmt_class(w.accumulated_end, hc))

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
        # название формы — по действующему приказу Росстата № 614: слова
        # «транспортировании» в нём нет (оно осталось от прежней редакции)
        xlsx.merge(ws, "A3:F4", "СВЕДЕНИЯ ОБ ОБРАЗОВАНИИ, ОБРАБОТКЕ, УТИЛИЗАЦИИ, "
                   "ОБЕЗВРЕЖИВАНИИ, РАЗМЕЩЕНИИ ОТХОДОВ "
                   "ПРОИЗВОДСТВА И ПОТРЕБЛЕНИЯ", bold=True, border=False)
        xlsx.merge(ws, "A5:F5", f"за {year} год", border=False, bold=True)
        xlsx.merge(ws, "E6:F6", "Форма № 2-ТП (отходы), годовая", border=False,
                   italic=True, align="right")
        # блок реквизитов приказа и сроков — обязателен на бланке
        xlsx.merge(ws, "A6:D7",
                   "Предоставляют: юридические лица и индивидуальные "
                   "предприниматели, осуществляющие деятельность в области "
                   "обращения с отходами, региональные операторы по обращению "
                   "с ТКО  ·  Сроки предоставления: территориальному органу "
                   "Росприроднадзора в субъекте РФ — 1 февраля, "
                   "Росприроднадзору — 15 марта после отчётного периода  ·  "
                   "Форма утверждена приказом Росстата "
                   "от 06.11.2025 № 614", border=False, align="left")
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

    # 29 граф Раздела I по форме Приказа Росстата № 614 (сверено с реальным
    # принятым отчётом). Кортеж: (номер, краткая подпись).
    _G29 = [
        (1, "Наличие на начало года"), (2, "Образование за год"),
        (3, "Поступление от других: всего"), (4, "из гр.3: из др. субъектов РФ"),
        (5, "из гр.3: по импорту"), (6, "Поступление с собств. объектов: всего"),
        (7, "из них из др. субъектов РФ"), (8, "Образование др. видов после обработки"),
        (9, "Обработано"), (10, "Утилизировано: всего"),
        (11, "рециклинг"), (12, "предв. прошедших обработку"), (13, "Обезврежено"),
        (14, "Передача ТКО региональному оператору"),
        (15, "Передача (кроме ТКО) для обработки: всего"), (16, "из них в др. субъекты"),
        (17, "для утилизации: всего"), (18, "из них в др. субъекты"),
        (19, "для обезвреживания: всего"), (20, "из них в др. субъекты"),
        (21, "для хранения: всего"), (22, "из них в др. субъекты"),
        (23, "для захоронения: всего"), (24, "из них в др. субъекты"),
        (25, "на собств. объекты: всего"), (26, "из них в др. субъекты"),
        (27, "Размещение: хранение"), (28, "Размещение: захоронение"),
        (29, "Наличие на конец года"),
    ]

    def _page2(self, wb):
        from openpyxl.utils import get_column_letter
        ws = wb.create_sheet("стр.2")
        # заголовок Раздела I — полная официальная формулировка по печатной
        # форме ЛКПП (приказ № 614), а не сокращённая; merge на всю ширину
        # таблицы (4 служебных + 29 граф), иначе длинный текст обрезается
        xlsx.merge(ws, "A1:AG1", "Раздел I. Сведения об образовании, обработке, "
                   "утилизации, обезвреживании, размещении отходов производства "
                   "и потребления; сведения об образовании и передаче твердых "
                   "коммунальных отходов региональному оператору, тонна",
                   bold=True, border=False)
        # шапка: А,Б,В,Г + графы 1-29 (подпись — строка 2, номер — строка 3)
        base = [("А", "№ строки"), ("Б", "Наименование видов отходов"),
                ("В", "Код по ФККО"), ("Г", "Класс опасности")]
        for i, (g, lbl) in enumerate(base):
            col = get_column_letter(i + 1)
            xlsx.cell(ws, f"{col}2", lbl, bold=True, fill=True, size=8)
            xlsx.cell(ws, f"{col}3", g, italic=True, size=8)
        for i, (num, lbl) in enumerate(self._G29):
            col = get_column_letter(5 + i)
            xlsx.cell(ws, f"{col}2", lbl, bold=True, fill=True, size=7)
            xlsx.cell(ws, f"{col}3", num, italic=True, size=8)
        cols = [get_column_letter(5 + i) for i in range(29)]

        def gv(w):
            hc = w.hazard_class
            rc = lambda v: _round_class(v, hc)  # noqa: E731
            tko = _is_tko(w.fkko_code)
            trans = rc(w.transferred)
            g = {c: 0.0 for c in cols}
            # 1 — наличие на начало (хранение + накопление)
            g[cols[0]] = rc(D(w.accumulated_start) + D(w.accumulated_start_nakopl))
            g[cols[1]] = rc(w.generated)           # 2
            g[cols[2]] = rc(w.received)            # 3
            g[cols[8]] = rc(w.processed)           # 9
            g[cols[9]] = rc(w.used)                # 10
            g[cols[12]] = rc(w.neutralized)        # 13
            if tko:
                g[cols[13]] = trans                # 14 — ТКО региональному оператору
            else:
                g[cols[14]] = rc(w.transferred_processing)  # 15 — для обработки
                g[cols[16]] = rc(w.transferred_util)     # 17 — для утилизации
                g[cols[18]] = rc(w.transferred_neutral)  # 19 — для обезвреживания
                g[cols[20]] = rc(w.transferred_storage)  # 21 — для хранения
                g[cols[22]] = rc(w.transferred_burial)   # 23 — для захоронения
            g[cols[27]] = rc(D(w.placed_norm) + D(w.placed_over))  # 28 — размещ. захоронение
            g[cols[28]] = rc(w.accumulated_end)    # 29
            return g

        r = 4
        row_no = 1
        self._agg_row(ws, r, str(row_no), "ВСЕГО", self.ctx.wastes, gv, cols)
        r += 1; row_no += 1
        for cl in (1, 2, 3, 4, 5):
            group = [w for w in self.ctx.wastes if int(w.hazard_class) == cl]
            if group:
                self._agg_row(ws, r, str(row_no), f"Всего по {cl} классу опасности",
                              group, gv, cols)
                r += 1; row_no += 1
        for w in self.ctx.wastes:
            g = gv(w)
            xlsx.cell(ws, f"A{r}", row_no); row_no += 1
            xlsx.cell(ws, f"B{r}", w.name, align="left")
            # графа В — канонический вид ФККО с пробелами, как печатает ЛКПП
            # («7 33 100 01 72 4»); в XML код остаётся без пробелов
            xlsx.cell(ws, f"C{r}", _fkko_spaced(w.fkko_code))
            xlsx.cell(ws, f"D{r}", w.hazard_class)
            for c in cols:
                xlsx.cell(ws, f"{c}{r}", g[c])
            r += 1
        xlsx.widths(ws, {"A": 5, "B": 28, "C": 13, "D": 7,
                         **{c: 9 for c in cols}})
        xlsx.heights(ws, {2: 70})

    def _agg_row(self, ws, r, num, label, group, gv, cols):
        xlsx.cell(ws, f"A{r}", num, bold=True)
        xlsx.cell(ws, f"B{r}", label, bold=True, align="left")
        for c in cols:
            total = sum(gv(w)[c] for w in group)
            xlsx.cell(ws, f"{c}{r}", round(total, 6), bold=True)

    def _page3(self, wb):
        """стр.3 — Раздел II (регоператоры ТКО) + Раздел III (объекты размещения)
        + подпись. Разделы II/III — из ctx.extra."""
        from openpyxl.utils import get_column_letter
        ws = wb.create_sheet("стр.3")
        o = self.ctx.organization
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        # A–D — служебные А|Б|В|Г, E..P — до 12 граф самой широкой подтаблицы;
        # столбец B широкий — в нём же длинные показатели Раздела III
        xlsx.widths(ws, {"A": 7, "B": 32, "C": 15, "D": 9,
                         **{get_column_letter(5 + i): 10 for i in range(12)}})
        # Раздел II — по бланку № 614: собственные 29 граф тремя подтаблицами
        # (гр.1–9 / 10–17 / 18–29) с шапкой А|Б|В|Г. В принятых отчётах шапка
        # печатается целиком даже у нерегоператоров, поэтому структуру не
        # подменяем текстом, а печатаем всегда.
        xlsx.merge(ws, "A1:P2", _S2_TITLE, bold=True, border=False)
        tko_ops = e.get("tko_operators", [])
        labels = dict(_G29_II)
        service = [("А", "N строки"), ("Б", "Наименование видов отходов"),
                   ("В", "Код отхода по федеральному классификационному "
                         "каталогу отходов"),
                   ("Г", "Класс опасности отхода")]
        r = 3
        for start, end in _S2_SPLITS:
            if start > 1:
                xlsx.merge(ws, f"A{r}:D{r}", "продолжение раздела II",
                           border=False, italic=True, align="left")
                r += 1
            # шапка подтаблицы: подпись графы (строка r) + буква/номер (r+1)
            for i, (g, lbl) in enumerate(service):
                col = get_column_letter(i + 1)
                xlsx.cell(ws, f"{col}{r}", lbl, bold=True, fill=True, size=8)
                xlsx.cell(ws, f"{col}{r + 1}", g, italic=True, size=8)
            for i, num in enumerate(range(start, end + 1)):
                col = get_column_letter(5 + i)
                xlsx.cell(ws, f"{col}{r}", labels[num], bold=True, fill=True,
                          size=7)
                xlsx.cell(ws, f"{col}{r + 1}", num, italic=True, size=8)
            xlsx.heights(ws, {r: 88})
            r += 2
            for idx, op in enumerate(tko_ops, start=1):
                xlsx.cell(ws, f"A{r}", idx)
                xlsx.cell(ws, f"B{r}", op.get("name", ""), align="left")
                xlsx.cell(ws, f"C{r}", _fkko_spaced(op.get("fkko", "")))
                xlsx.cell(ws, f"D{r}", op.get("hazard_class", ""))
                for i, num in enumerate(range(start, end + 1)):
                    xlsx.cell(ws, f"{get_column_letter(5 + i)}{r}",
                              _s2_val(op, num))
                r += 1
        if not tko_ops:
            xlsx.merge(ws, f"A{r}:F{r}", "— раздел не заполняется (респондент "
                       "не является региональным оператором по обращению с "
                       "твердыми коммунальными отходами)",
                       border=False, italic=True, align="left")
            r += 1
        # Раздел III — по бланку формы (приказ Росстата № 614): три графы и
        # 21 строка с фиксированными номерами 11–31. Раньше здесь печаталась
        # самодельная таблица объектов, которой в форме нет.
        r += 1
        xlsx.merge(ws, f"A{r}:C{r}", "Раздел III. Сведения об эксплуатируемых "
                   "объектах размещения отходов", bold=True, border=False)
        r += 1
        xlsx.header_row(ws, r, ["N строки", "Наименование показателя", "Фактически"])
        r += 1
        s3 = e.get("disposal_objects_s3", {}) or {}
        for num, label in _S3_ROWS:
            value = s3.get(str(num), s3.get(num, ""))
            xlsx.data_row(ws, r, [num, label, value if value not in (None, "") else "-"])
            r += 1
        # подпись
        r += 2
        xlsx.cell(ws, f"A{r}", "Должностное лицо, ответственное за предоставление "
                  "статистической информации:", border=False, align="left")
        xlsx.cell(ws, f"A{r+2}", f"{o.director_position}  ______________  {o.director_name}",
                  border=False, align="left")
        xlsx.cell(ws, f"A{r+4}", f"E-mail: {o.email}    тел.: {o.phone}    "
                  "«____» __________ 20___ г.", border=False, align="left")
