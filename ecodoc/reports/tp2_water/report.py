"""Форма 2-ТП (водхоз) — сведения об использовании воды. Годовая, с первого
рабочего дня по 22 января года, следующего за отчётным. Код ОКУД 0609060.

ДЕЙСТВУЮЩАЯ форма — Приказ Росстата от 02.10.2024 № 445 (заменил № 815 от
27.12.2019). Адресат — территориальный орган Росводресурсов в субъекте РФ
(БВУ); подача только электронно через Модуль респондента ИАС «2-ТП (водхоз)»
/ ГИС ЦП «Вода» (НЕ в Росстат).

Состав печатной формы сверен с реально ПРИНЯТЫМ отчётом (ПРОТЕЛЮКС, 2-ТП
водхоз за 2023: скан + нативный файл .tp2 Модуля респондента ИАС «2-ТП»):
титульный лист (кодовая часть гр.1-6 = ОКУД/ОКПО/ИНН/ОКВЭД2/ОКАТО/ГУИВ —
НЕ ОКТМО/ОГРН, как в 2-ТП отходы; блок подписи должностного лица),
Раздел 1 — 49 пронумерованных граф (включая помесячную разбивку гр.13-24),
Раздел 2 — 30 граф + пары «код ЗВ / масса» (гр. 31-78).

Данные — из ctx.extra['water'] (объёмы — тыс. м³/год, расстояния — км).
Графа без источника в данных печатается ПУСТОЙ — ничего не выдумываем.
  {
    "okato": "41221505",     # титульный лист, гр.5 — код территории ОКАТО
    "guiv": "412285",        # титульный лист, гр.6 — код водопользователя ГУИВ
    "intake": [{             # Раздел 1, словарь на источник/поставщика:
        "name": "...", "type": "...",       # справочно (в бланке граф нет)
        "doc_type": "Л",                    # гр.1 — Д(оговор)/Л(ицензия)/Р(ешение)
        "doc_no": "480082",                 # гр.2
        "doc_date": "25.02.2020",           # гр.3
        "source_code": "60",                # гр.4 — код типа источника (Прил. 1)
        "water_body_code": "БАЛ/НАРВА",     # гр.5 — код водного объекта
        "distance_km": 16.9,                # гр.6 — расстояние от устья, км
        "supplier_guiv": "",                # гр.7 — код поставщика по ГУИВ
        "quality": "ТН",                    # гр.8 — категория качества (Прил. 2)
        "okato": "41221505", "vhu": "01.03.00.004",   # гр.9-10
        "limit": 145.71,                    # гр.11 — допустимый объём забора
        "volume": 1.29,                     # гр.12 — забрано всего за год
        "months": [12 значений, янв..дек],  # гр.13-24 (Σ должна = гр.12)
        "measured": 1.29,                   # гр.25 — учтено средствами измерений
        "losses": 0.0,                      # гр.26 — потери при транспортировке
        "use_okato": "", "use_vhu": "",     # гр.27-28 — территория использования
        "recycled": 0.0, "reused": 0.0,     # гр.29-30 — оборотное/повторное
        "used_total": 1.29,                 # гр.31 — использовано всего за год
        "uses": [{"code": "102", "volume": 1.29}],      # гр.32-43 (до 6 пар)
        "transfers": [{"code": "", "volume": 0}]        # гр.44-49 (до 3 пар)
      }],
    "discharge": [{          # Раздел 2, словарь на выпуск:
        "receiver": "р. Нарва",             # справочно
        "doc_type": "Р", "doc_no": "...", "doc_date": "...",   # гр.1-3
        "receiver_code": "20",              # гр.4 — код типа приёмника (Прил. 1)
        "water_body_code": "...",           # гр.5
        "distance_km": 16.9,                # гр.6
        "quality": "НЧ",                    # гр.7 — категория качества КОДОМ
        "okato": "...", "vhu": "...",       # гр.8-9
        "limit": 145.71,                    # гр.10 — допустимый объём водоотведения
        "volume": 1.29,                     # гр.11 — отведено всего за год
        "measured": 1.29,                   # гр.12 — учтено средствами измерений
        "polluted_no_treat": 0,             # гр.13 — загрязнённых без очистки
        "insufficiently_treated": 0,        # гр.14 — недостаточно очищенных
        "normatively_clean": 0,             # гр.15 — нормативно чистых без очистки
        "treatment_code": "40",             # гр.16 — код сооружения очистки (Прил. 4)
        "normatively_treated": 1.29,        # гр.17 — нормативно очищенных
        "treatment_capacity": 2.5,          # гр.18 — мощность очистных сооружений
        "months": [12 значений],            # гр.19-30
        "pollutants": [{"code": "132", "name": "БПКполн", "mass": 0.05}]
                                            # гр.31-78 — пары «код ЗВ / масса»
      }],
    "recycled": 40.0, "reused": 0.0, "used_own": 10.0   # сводные показатели
  }
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree
from openpyxl.utils import get_column_letter

from ecodoc.core.models import Issue
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report

# текстовые категории оставлены для совместимости со старыми данными;
# по бланку № 445 категория качества задаётся КОДОМ (Прил. 2, напр. «НЧ», «ТН»)
_QUALITY = ("нормативно-чистые", "нормативно-очищенные",
            "недостаточно-очищенные", "загрязнённые без очистки")

_MONTH_NAMES = ("январь", "февраль", "март", "апрель", "май", "июнь",
                "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")


def _build_s1_cols() -> list[tuple[int, str]]:
    """49 граф Раздела 1 по реально принятому бланку (скан ПРОТЕЛЮКС, стр. 2)."""
    cols = [
        (1, "Тип разрешительного документа (Д, Л, Р)"),
        (2, "Номер документа"),
        (3, "Дата документа"),
        (4, "Код типа источника (Прил. 1)"),
        (5, "Код водного объекта"),
        (6, "Расстояние от устья, км"),
        (7, "Код поставщика по ГУИВ"),
        (8, "Категория качества воды (Прил. 2)"),
        (9, "Код территории по ОКАТО"),
        (10, "Код ВХУ"),
        (11, "Допустимый объём забора воды"),
        (12, "Забрано или получено — всего за год"),
    ]
    cols += [(13 + i, _MONTH_NAMES[i]) for i in range(12)]
    cols += [
        (25, "Учтено средствами измерений"),
        (26, "Потери при транспортировке"),
        (27, "Код территории использования по ОКАТО"),
        (28, "Код ВХУ территории использования"),
        (29, "Оборотное водоснабжение"),
        (30, "Повторно-последовательное водоснабжение"),
        (31, "Использовано воды — всего за год"),
    ]
    # гр.32-43 — использовано по кодам видов использования (Прил. 3), 6 пар;
    # гр.44-49 — передано для использования/отведения, 3 пары «код + объём»
    for i in range(6):
        cols += [(32 + 2 * i, "Код вида использования (Прил. 3)"),
                 (33 + 2 * i, "Использовано за год")]
    for i in range(3):
        cols += [(44 + 2 * i, "Код передачи (использование / отведение)"),
                 (45 + 2 * i, "Передано за год")]
    return cols


_S1_COLS = _build_s1_cols()
# суммируемые графы Раздела 1 (объёмы; коды и реквизиты не суммируются)
_S1_TOTALS = {11, 12, *range(13, 27), 29, 30, 31, 33, 35, 37, 39, 41, 43,
              45, 47, 49}

# 30 граф Раздела 2 по принятому бланку (скан ПРОТЕЛЮКС, стр. 3); пары
# «код ЗВ / масса» (гр.31-78) добавляются динамически по числу веществ
_S2_COLS = [
    (1, "Тип разрешительного документа (Р, Л)"),
    (2, "Номер документа"),
    (3, "Дата документа"),
    (4, "Код типа приёмника (Прил. 1)"),
    (5, "Код водного объекта"),
    (6, "Расстояние от устья, км"),
    (7, "Категория качества воды (Прил. 2)"),
    (8, "Код территории по ОКАТО"),
    (9, "Код ВХУ"),
    (10, "Допустимый объём водоотведения"),
    (11, "Отведено воды — всего за год"),
    (12, "Учтено средствами измерений"),
    (13, "Загрязнённых — без очистки"),
    (14, "Недостаточно очищенных"),
    (15, "Нормативно чистых (без очистки)"),
    (16, "Код сооружения очистки (Прил. 4)"),
    (17, "Нормативно очищенных"),
    (18, "Мощность очистных сооружений"),
] + [(19 + i, _MONTH_NAMES[i]) for i in range(12)]
_S2_TOTALS = {10, 11, 12, 13, 14, 15, 17, *range(19, 31)}


def _numv(v):
    """Число для печати или пустая графа: данных нет — ничего не выдумываем."""
    return float(D(v)) if v not in (None, "") else ""


def _months_row(rec) -> list:
    """12 помесячных значений; недостающие — пустые графы."""
    ms = list(rec.get("months") or [])
    return [_numv(ms[i]) if i < len(ms) else "" for i in range(12)]


def _pairs_row(items, n) -> list:
    """Пары «код + объём/масса» фиксированной ширины (пустые добиваются)."""
    out: list = []
    for i in range(n):
        if i < len(items):
            it = items[i]
            out += [str(it.get("code", "")),
                    _numv(it.get("volume", it.get("mass")))]
        else:
            out += ["", ""]
    return out


def _opt(parent, tag, val):
    """Необязательный текстовый элемент XML — только если значение задано."""
    if val not in (None, ""):
        el(parent, tag, val)


def _optn(parent, tag, val):
    """Необязательный числовой элемент XML — только если значение задано."""
    if val not in (None, ""):
        el(parent, tag, float(D(val)))


def _xml_months(parent, rec):
    """Помесячная разбивка (гр.13-24 / 19-30 бланка): <Месяцы><М н="1">…»."""
    ms = rec.get("months") or []
    if not ms:
        return
    box = el(parent, "Месяцы")
    for i in range(12):
        v = ms[i] if i < len(ms) else 0
        el(box, "М", float(D(v or 0)), н=str(i + 1))


def _xml_doc(parent, rec):
    """Разрешительный документ (гр.1-3): договор/лицензия/решение."""
    if any(rec.get(k) for k in ("doc_type", "doc_no", "doc_date")):
        el(parent, "Документ", тип=rec.get("doc_type", ""),
           номер=rec.get("doc_no", ""), дата=rec.get("doc_date", ""))


@register
class TP2Water(Report):
    code = "2tp-water"
    title = "2-ТП (водхоз)"

    def _water(self) -> dict:
        return self.ctx.extra.get("water", {}) or {}

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not o.okpo:
            issues.append(Issue("warning", "ОКПО", "для 2-ТП обязателен код ОКПО"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        w = self._water()
        if not w.get("intake") and not w.get("discharge"):
            issues.append(Issue("error", "водоучёт",
                                "нет данных водозабора/водоотведения "
                                "(заполните extra.water: intake/discharge)"))
        for d in w.get("discharge", []):
            q = d.get("quality", "")
            # короткие значения считаем кодами Прил. 2 (напр. «НЧ», «ТН») —
            # предупреждаем только про длинный текст не из старого перечня
            if q and q not in _QUALITY and len(q) > 5:
                issues.append(Issue("warning", "качество",
                                    f"категория качества «{q}» — не код Прил. 2 "
                                    f"и не из перечня: {', '.join(_QUALITY)}"))
        # помесячная разбивка: 12 значений, сумма = годовому объёму (гр.12/11);
        # без этого Модуль респондента отчёт не примет
        for part in ("intake", "discharge"):
            for rec in w.get(part, []):
                ms = rec.get("months")
                if not ms:
                    continue
                if len(ms) != 12:
                    issues.append(Issue(
                        "warning", "месяцы",
                        f"{part}: помесячная разбивка должна содержать 12 "
                        f"значений (январь-декабрь), получено {len(ms)}"))
                    continue
                diff = (sum((D(m or 0) for m in ms), D(0))
                        - D(rec.get("volume", 0))).copy_abs()
                if diff > D("0.01"):
                    issues.append(Issue(
                        "warning", "месяцы",
                        f"{part}: сумма помесячных объёмов не сходится с "
                        f"годовым (расхождение {diff} тыс. м³)"))
        return issues

    # ---------------- XML -------------------------------------------------
    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        w = self._water()
        # version 0.3 — добавлены реквизиты документов, коды-классификаторы,
        # лимиты и помесячная разбивка (<Месяцы><М н="1">…</М></Месяцы>)
        root = etree.Element("Форма2ТПВодхоз", version="0.3", ОКУД="0609060",
                             НПА="Приказ Росстата № 445 от 02.10.2024")
        org = el(root, "Респондент")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "ОКПО", o.okpo)
        el(org, "ОКТМО", o.oktmo)
        _opt(org, "ОКАТО", w.get("okato"))
        _opt(org, "ГУИВ", w.get("guiv"))
        el(org, "Адрес", o.address)
        el(org, "Адресат", "территориальное Бассейновое водное управление "
                           "(Модуль респондента ИАС «2-ТП (водхоз)» / ГИС ЦП «Вода»)")
        el(root, "ОтчётныйГод", self.ctx.period.year)

        intk = el(root, "ЗаборВоды")
        for s in w.get("intake", []):
            x = el(intk, "Источник")
            el(x, "Наименование", s.get("name", ""))
            el(x, "Тип", s.get("type", ""))
            _xml_doc(x, s)                                       # гр.1-3
            _opt(x, "КодТипаИсточника", s.get("source_code"))    # гр.4
            _opt(x, "КодВодногоОбъекта", s.get("water_body_code"))  # гр.5
            _optn(x, "РасстояниеОтУстья", s.get("distance_km"))  # гр.6
            _opt(x, "ПоставщикГУИВ", s.get("supplier_guiv"))     # гр.7
            _opt(x, "КатегорияКачества", s.get("quality"))       # гр.8
            _opt(x, "ОКАТО", s.get("okato"))                     # гр.9
            _opt(x, "ВХУ", s.get("vhu"))                         # гр.10
            _optn(x, "ДопустимыйОбъём", s.get("limit"))          # гр.11
            el(x, "Объём", float(D(s.get("volume", 0))))         # гр.12
            _xml_months(x, s)                                    # гр.13-24
            _optn(x, "УчтеноПриборами", s.get("measured"))       # гр.25
            _optn(x, "Потери", s.get("losses"))                  # гр.26
            _opt(x, "ОКАТОИспользования", s.get("use_okato"))    # гр.27
            _opt(x, "ВХУИспользования", s.get("use_vhu"))        # гр.28
            _optn(x, "Оборотная", s.get("recycled"))             # гр.29
            _optn(x, "Повторная", s.get("reused"))               # гр.30
            _optn(x, "ИспользованоВсего", s.get("used_total"))   # гр.31
            for u in s.get("uses", []):                          # гр.32-43
                el(x, "ВидИспользования", float(D(u.get("volume", 0))),
                   код=str(u.get("code", "")))
            for t in s.get("transfers", []):                     # гр.44-49
                el(x, "Передано", float(D(t.get("volume", 0))),
                   код=str(t.get("code", "")))
        disc = el(root, "Водоотведение")
        for d in w.get("discharge", []):
            x = el(disc, "Выпуск")
            el(x, "Приёмник", d.get("receiver", ""))
            el(x, "Качество", d.get("quality", ""))              # гр.7 (код)
            el(x, "Объём", float(D(d.get("volume", 0))))         # гр.11
            _xml_doc(x, d)                                       # гр.1-3
            _opt(x, "КодТипаПриёмника", d.get("receiver_code"))  # гр.4
            _opt(x, "КодВодногоОбъекта", d.get("water_body_code"))  # гр.5
            _optn(x, "РасстояниеОтУстья", d.get("distance_km"))  # гр.6
            _opt(x, "ОКАТО", d.get("okato"))                     # гр.8
            _opt(x, "ВХУ", d.get("vhu"))                         # гр.9
            _optn(x, "ДопустимыйОбъём", d.get("limit"))          # гр.10
            _optn(x, "УчтеноПриборами", d.get("measured"))       # гр.12
            # гр.13-18 — отведено по категориям очистки (структура бланка,
            # а не самодельные «в пределах/сверх норматива»)
            if any(d.get(k) not in (None, "") for k in
                   ("polluted_no_treat", "insufficiently_treated",
                    "normatively_clean", "treatment_code",
                    "normatively_treated", "treatment_capacity")):
                cat = el(x, "ОтведеноПоКатегориям")
                _optn(cat, "БезОчистки", d.get("polluted_no_treat"))
                _optn(cat, "НедостаточноОчищенные",
                      d.get("insufficiently_treated"))
                _optn(cat, "НормативноЧистые", d.get("normatively_clean"))
                if d.get("normatively_treated") not in (None, "") or \
                        d.get("treatment_code") not in (None, ""):
                    el(cat, "НормативноОчищенные",
                       float(D(d.get("normatively_treated", 0))),
                       код=str(d.get("treatment_code", "")))
                _optn(cat, "МощностьОчистных", d.get("treatment_capacity"))
            _xml_months(x, d)                                    # гр.19-30
            # сброшенные ЗВ по выпуску (гр.31-78, коды по Прил. 5 к № 445)
            for zv in d.get("pollutants", []):
                z = el(x, "ЗВ", код=str(zv.get("code", "")))
                el(z, "Наименование", zv.get("name", ""))
                el(z, "Масса", float(D(zv.get("mass", 0))))
        el(root, "ОборотнаяВода", float(D(w.get("recycled", 0))))
        el(root, "ПовторноПоследовательная", float(D(w.get("reused", 0))))
        el(root, "ИспользованоНаСобственныеНужды", float(D(w.get("used_own", 0))))
        write_tree(root, out_path)
        return out_path

    # ---------------- Печатная форма --------------------------------------
    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        w = self._water()
        wb = xlsx.new_workbook()
        self._title_page(wb, w)
        self._section1(wb, w)
        self._section2(wb, w)
        self._summary(wb, w)
        return xlsx.save(wb, out_path)

    def _title_page(self, wb, w):
        """Адресная часть бланка № 445: без неё форму нельзя распечатать
        и подписать. Кодовая часть гр.1-6 — по принятому отчёту:
        ОКУД / ОКПО / ИНН / ОКВЭД2 / ОКАТО / ГУИВ (не ОКТМО и не ОГРН)."""
        ws = wb.create_sheet("Титульный лист")
        o = self.ctx.organization
        year = self.ctx.period.year or ""
        xlsx.widths(ws, {"A": 22, "B": 24, "C": 18, "D": 18, "E": 18, "F": 20})
        xlsx.merge(ws, "A1:F1", "ФЕДЕРАЛЬНОЕ СТАТИСТИЧЕСКОЕ НАБЛЮДЕНИЕ",
                   bold=True, border=False)
        xlsx.merge(ws, "A3:F3", "СВЕДЕНИЯ ОБ ИСПОЛЬЗОВАНИИ ВОДЫ",
                   bold=True, border=False)
        xlsx.merge(ws, "A4:F4", f"за {year} г.", bold=True, border=False)
        xlsx.merge(ws, "E5:F5", "Форма № 2-ТП (водхоз), годовая",
                   border=False, italic=True, align="right")
        xlsx.merge(ws, "A5:D6",
                   "Предоставляют: юридические лица и индивидуальные "
                   "предприниматели, осуществляющие пользование водными "
                   "объектами, — территориальному органу Росводресурсов "
                   "в субъекте Российской Федерации  ·  Срок: с первого "
                   "рабочего дня по 22 января  ·  Форма утверждена приказом "
                   "Росстата от 02.10.2024 № 445", border=False, align="left")
        xlsx.cell(ws, "A8", "Наименование отчитывающейся организации",
                  border=False, align="left")
        xlsx.merge(ws, "A9:F9", o.name, border=False, align="left")
        xlsx.cell(ws, "A11", "Почтовый адрес", border=False, align="left")
        xlsx.merge(ws, "A12:F12", o.address, border=False, align="left")
        head = ["Код формы по ОКУД", "Код отчитывающейся организации по ОКПО",
                "ИНН", "Код вида деятельности по ОКВЭД2",
                "Код территории по ОКАТО", "Код водопользователя по ГУИВ"]
        okved1 = next((c.strip() for c in (o.okved or "").replace(";", ",").split(",")
                       if c.strip()), "")
        # ОКАТО и ГУИВ в модели организации отсутствуют — берём из
        # extra.water (okato/guiv); нет данных — графа остаётся пустой
        vals = ["0609060", o.okpo, o.inn, okved1,
                w.get("okato", ""), w.get("guiv", "")]
        for i, (h, v) in enumerate(zip(head, vals)):
            col = chr(65 + i)
            xlsx.cell(ws, f"{col}15", h, bold=True, fill=True, size=9)
            xlsx.cell(ws, f"{col}16", i + 1, italic=True, size=9)
            xlsx.cell(ws, f"{col}17", v or "")
        # блок подписи — стр. 4 бланка (должность, ФИО, телефон, e-mail, дата)
        xlsx.merge(ws, "A19:F19",
                   "Должностное лицо, ответственное за предоставление "
                   "первичных статистических данных:", border=False, align="left")
        xlsx.merge(ws, "A21:F21",
                   f"{o.official_title}  ______________  {o.director_name}",
                   border=False, align="left")
        xlsx.merge(ws, "A23:F23",
                   f"тел.: {o.phone}    E-mail: {o.email}    "
                   "«___» __________ 20___ г.", border=False, align="left")
        xlsx.heights(ws, {3: 30, 15: 46})

    def _numbered_sheet(self, wb, name, title, cols, lead_label, rows,
                        total_graphs):
        """Лист с пронумерованными графами бланка: строка подписей + строка
        номеров (как на официальной форме), колонка A — справочное имя
        строки (в бланке объект задаётся кодами, имя добавлено для людей)."""
        ws = wb.create_sheet(name)
        last = get_column_letter(1 + len(cols))
        xlsx.merge(ws, f"A1:{last}1", title, bold=True, border=False,
                   align="left")
        xlsx.merge(ws, f"A2:{last}2", "Коды по ОКЕИ: тысяча кубических "
                   "метров — 114; километр — 008", border=False, italic=True,
                   align="left")
        xlsx.cell(ws, "A3", lead_label, bold=True, fill=True, size=8)
        xlsx.cell(ws, "A4", "", italic=True, size=8)
        for i, (num, lbl) in enumerate(cols):
            c = get_column_letter(2 + i)
            xlsx.cell(ws, f"{c}3", lbl, bold=True, fill=True, size=8)
            xlsx.cell(ws, f"{c}4", num, italic=True, size=8)
        totals: dict[int, object] = {}
        r = 5
        for lead, vals in rows:
            xlsx.cell(ws, f"A{r}", lead, align="left")
            for i, v in enumerate(vals):
                xlsx.cell(ws, f"{get_column_letter(2 + i)}{r}", v)
                if (i + 1) in total_graphs and isinstance(v, (int, float)):
                    totals[i] = totals.get(i, D(0)) + D(v)
            r += 1
        xlsx.cell(ws, f"A{r}", "ИТОГО", bold=True, align="left")
        for i in sorted(totals):
            xlsx.cell(ws, f"{get_column_letter(2 + i)}{r}",
                      float(totals[i]), bold=True)
        xlsx.widths(ws, {"A": 26,
                         **{get_column_letter(2 + i): 9
                            for i in range(len(cols))}})
        xlsx.heights(ws, {3: 64})
        return ws, r

    def _section1(self, wb, w):
        """Раздел 1 — 49 граф (реквизиты документа, коды-классификаторы,
        лимит, год + помесячно, использование по кодам видов, передача)."""
        rows = []
        for s in w.get("intake", []):
            vals = [
                s.get("doc_type", ""), s.get("doc_no", ""),      # гр.1-2
                s.get("doc_date", ""),                           # гр.3
                str(s.get("source_code", "")),                   # гр.4
                s.get("water_body_code", ""),                    # гр.5
                _numv(s.get("distance_km")),                     # гр.6
                s.get("supplier_guiv", ""),                      # гр.7
                s.get("quality", ""),                            # гр.8
                s.get("okato", ""), s.get("vhu", ""),            # гр.9-10
                _numv(s.get("limit")),                           # гр.11
                float(D(s.get("volume", 0))),                    # гр.12
                *_months_row(s),                                 # гр.13-24
                _numv(s.get("measured")),                        # гр.25
                _numv(s.get("losses")),                          # гр.26
                s.get("use_okato", ""), s.get("use_vhu", ""),    # гр.27-28
                _numv(s.get("recycled")),                        # гр.29
                _numv(s.get("reused")),                          # гр.30
                _numv(s.get("used_total")),                      # гр.31
                *_pairs_row(s.get("uses", []), 6),               # гр.32-43
                *_pairs_row(s.get("transfers", []), 3),          # гр.44-49
            ]
            rows.append((s.get("name", "") or s.get("type", ""), vals))
        self._numbered_sheet(
            wb, "Раздел 1",
            "Раздел 1. Забрано из природных источников, получено от "
            "поставщиков, использовано, передано и потеряно воды",
            _S1_COLS, "Источник (справочно)", rows, _S1_TOTALS)

    def _section2(self, wb, w):
        """Раздел 2 «Водоотведение» — 30 граф + пары «код ЗВ / масса»
        (гр.31-78); отдельная самодельная таблица ЗВ бланку не соответствует
        и заменена штатными графами."""
        discharge = w.get("discharge", [])
        npairs = max((len(d.get("pollutants", [])) for d in discharge),
                     default=0)
        cols = list(_S2_COLS)
        for i in range(npairs):
            cols += [(31 + 2 * i, "Код ЗВ (Прил. 5)"),
                     (32 + 2 * i, "Масса ЗВ")]
        rows = []
        for d in discharge:
            zv = [{"code": p.get("code", ""), "volume": p.get("mass", 0)}
                  for p in d.get("pollutants", [])]
            vals = [
                d.get("doc_type", ""), d.get("doc_no", ""),      # гр.1-2
                d.get("doc_date", ""),                           # гр.3
                str(d.get("receiver_code", "")),                 # гр.4
                d.get("water_body_code", ""),                    # гр.5
                _numv(d.get("distance_km")),                     # гр.6
                d.get("quality", ""),                            # гр.7
                d.get("okato", ""), d.get("vhu", ""),            # гр.8-9
                _numv(d.get("limit")),                           # гр.10
                float(D(d.get("volume", 0))),                    # гр.11
                _numv(d.get("measured")),                        # гр.12
                _numv(d.get("polluted_no_treat")),               # гр.13
                _numv(d.get("insufficiently_treated")),          # гр.14
                _numv(d.get("normatively_clean")),               # гр.15
                str(d.get("treatment_code", "")),                # гр.16
                _numv(d.get("normatively_treated")),             # гр.17
                _numv(d.get("treatment_capacity")),              # гр.18
                *_months_row(d),                                 # гр.19-30
                *_pairs_row(zv, npairs),                         # гр.31+
            ]
            rows.append((d.get("receiver", ""), vals))
        ws, r = self._numbered_sheet(
            wb, "Раздел 2", "Раздел 2. Водоотведение", cols,
            "Выпуск / приёмник (справочно)", rows, _S2_TOTALS)
        # сноска бланка про единицы измерения масс ЗВ
        xlsx.merge(ws, f"A{r + 2}:P{r + 2}",
                   "Массы ЗВ: БПК, нефтепродукты, сульфаты, сухой остаток, "
                   "хлориды, фосфаты, аммоний-ион — в тоннах; прочие — в кг "
                   "(сноска к бланку № 445).", border=False, italic=True,
                   align="left")

    def _summary(self, wb, w):
        """Сводка — служебный лист (не бланк): итоги и реквизиты формы."""
        total_in = sum((D(s.get("volume", 0)) for s in w.get("intake", [])),
                       D(0))
        total_out = sum((D(d.get("volume", 0)) for d in w.get("discharge", [])),
                        D(0))
        ws = wb.create_sheet("Сводка")
        xlsx.header_row(ws, 1, ["Показатель", "Значение, тыс. м³/год"],
                        widths=[40, 20])
        xlsx.data_row(ws, 2, ["Забрано воды, всего", float(total_in)])
        xlsx.data_row(ws, 3, ["Отведено (сброшено), всего", float(total_out)])
        xlsx.data_row(ws, 4, ["Оборотное водоснабжение",
                              float(D(w.get("recycled", 0)))])
        xlsx.data_row(ws, 5, ["Повторно-последовательное водоснабжение",
                              float(D(w.get("reused", 0)))])
        xlsx.data_row(ws, 6, ["Использовано на собственные нужды",
                              float(D(w.get("used_own", 0)))])
        xlsx.data_row(ws, 8, ["Форма / ОКУД", "2-ТП (водхоз) / 0609060"])
        xlsx.data_row(ws, 9, ["Основание", "Приказ Росстата № 445 от 02.10.2024"])
        xlsx.data_row(ws, 10, ["Адресат", "территориальное Бассейновое водное "
                               "управление (Модуль респондента / ГИС ЦП «Вода»)"])
        xlsx.data_row(ws, 11, ["Срок (за 2025)",
                               "с первого рабочего дня по 22.01.2026"])
