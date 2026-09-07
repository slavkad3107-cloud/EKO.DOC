"""Инвентаризация отходов: отчёт по объекту (.docx) + перечень (.xlsx).

Первый документ контура «Разработка» по новой схеме: из него потом растут
ПНООЛР, журнал 1028, 2-ТП и кадастр — поэтому он идёт первым.

Официальной формы отчёта об инвентаризации отходов нет (это внутренний
документ природопользователя: ст. 11, 18 ФЗ-89; приказ Минприроды № 157 от
31.03.2025 касается инвентаризации ОБЪЕКТОВ РАЗМЕЩЕНИЯ, а не отходов).
Структура взята из практики (пример Profiz «Инвентаризация отходов
производства и потребления», 2020) и разделов ПНООЛР по приказу № 1021
от 07.12.2020 — там же графы таблиц «Сведения об отходах» (наименование,
код, класс, происхождение, агрегатное состояние, состав) и «Сведения о
хозяйственной деятельности» (сырьё → операция → продукция → отход →
обращение). Образцы и ссылки — Формы/Разработка/ИНВЕНТАРИЗАЦИЯ ОТХОДОВ/
ИСТОЧНИК.txt.

Данные берём из того, что уже собрано программой:
  * справки-акты (`ctx.waste_acts`) — что реально образуется и куда сдаётся,
    факт за отчётный год, объёмы и плотности;
  * движение (`ctx.wastes`) — массы за отчётный период, происхождение,
    агрегатное состояние (если заполнены);
  * паспорта (`ctx.extra['waste_passports']`) — класс опасности, состав,
    происхождение;
  * нормативы проекта (`ctx.extra['oos_wastes']`) — норматив образования
    т/год из ООС/ПНООЛР;
  * лабораторные протоколы (`ctx.extra['lab_results']`) — чем подтверждён класс.

Отсутствующее не выдумываем и плейсхолдеров в документ не ставим: там, где
данных нет, стоит нейтральная формулировка («—», «не указан», «принимается по
исходным данным предприятия»), а в gaps() — конкретно, чего не хватает и откуда
это взять. Агрегатное состояние — по 9–10 знакам кода ФККО
(waste_passport.aggregate_state), источник образования без данных — типовая
формулировка по группе ФККО (в gaps — «уточните процесс»).
"""
from __future__ import annotations

import datetime as _dt
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import ReportContext
from ecodoc.render import xlsx

TITLE = "Инвентаризация отходов"
DOC_TITLE = "ОТЧЁТ ОБ ИНВЕНТАРИЗАЦИИ ОТХОДОВ ПРОИЗВОДСТВА И ПОТРЕБЛЕНИЯ"
NA = "—"                      # пустая ячейка таблицы
NOT_SET = "не указан"         # пустое поле в тексте

# Типовое происхождение по группам ФККО (первые знаки кода). Это подсказка
# для эколога (в gaps — «уточните процесс»): реальный процесс знает только
# предприятие. Формулировки — как в принятых ПНООЛР/паспортах
# («использование по назначению с утратой потребительских свойств» и т.п.).
ORIGIN_BY_PREFIX: list[tuple[str, str]] = [
    ("471", "замена отработанных ртутьсодержащих ламп (освещение помещений)"),
    ("48", "списание оргтехники, электрооборудования, аккумуляторов"),
    ("402", "износ спецодежды и текстильных изделий"),
    ("404", "использование деревянной тары и изделий из древесины с утратой "
            "потребительских свойств"),
    ("405", "использование бумажной и картонной упаковки"),
    ("43", "использование изделий из полимеров и упаковки с утратой "
           "потребительских свойств"),
    ("451", "использование изделий из стекла с утратой потребительских свойств"),
    ("46", "ремонт и обслуживание оборудования, списание металлических изделий"),
    ("406", "замена масел при обслуживании техники"),
    ("723", "очистка сточных вод (осадок очистных сооружений)"),
    ("729", "очистка сточных вод (осадок очистных сооружений)"),
    ("731", "жизнедеятельность персонала (отходы из жилищ)"),
    ("732", "жизнедеятельность персонала (выгребные ямы)"),
    ("733", "жизнедеятельность персонала, уборка помещений и территории"),
    ("81", "земляные и подготовительные работы"),
    ("82", "строительные, ремонтные и демонтажные работы"),
    ("83", "ремонт и разборка дорожных покрытий"),
    ("89", "строительные и ремонтные работы"),
    ("343", "строительные и ремонтные работы (бой строительных материалов)"),
    ("919", "обслуживание техники, ликвидация проливов нефтепродуктов"),
    ("921", "замена автомобильных шин при эксплуатации транспорта"),
    ("92", "эксплуатация и обслуживание автотранспорта"),
    ("4", "использование продукции по назначению с утратой потребительских "
          "свойств"),
    ("7", "жизнедеятельность персонала и обслуживание объекта"),
    ("9", "обслуживание оборудования и транспорта"),
]


def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return None
    return float(d) if d else None


def fmt_num(value, digits: int = 3) -> str:
    """Число для документа: 1.9 → «1,900», None/0 → «—»."""
    v = _num(value)
    if v is None:
        return "—"
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    if not s or s == "-0":
        s = "0"
    if "." not in s and digits and v != int(v):
        s = f"{v:.{digits}f}"
    return s.replace(".", ",")


def _year(ctx: ReportContext) -> int:
    return int(ctx.period.year or 0)


def typical_origin(fkko: str) -> str:
    """Типовое происхождение по группе ФККО (пусто — если нет подсказки)."""
    code = (fkko or "").replace(" ", "")
    for prefix, text in ORIGIN_BY_PREFIX:
        if code.startswith(prefix):
            return text
    return ""


def main_object(ctx: ReportContext):
    """Объект НВОС: первый с кодом формата NN-NNNN-NNNNNN-Б, иначе первый."""
    from ecodoc.core import nvos
    for o in ctx.objects:
        if nvos.is_valid(o.code):
            return o
    return ctx.objects[0] if ctx.objects else None


def site_address(ctx: ReportContext) -> str:
    o = main_object(ctx)
    if o and o.address:
        return o.address
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    return str(extra.get("site_address") or ctx.organization.address or "")


def collect(ctx: ReportContext) -> list[dict]:
    """Свести перечень отходов объекта из всех источников.

    Ключи строки (старые сохранены — их читают ПЭК/ДВОС/ООС/таблички):
      fkko, name, hazard, generated, transferred, operations, receivers,
      composition, passport, protocols;
    новые: agg (агрегатное состояние), origin, origin_typical (True — из
      справочника, надо уточнить), norm_t (норматив из ООС/ПНООЛР),
      fact_year (т по актам за отчётный год), fact_years {год: т},
      volume_m3, density, licenses, has_biotest, has_kha.
    """
    from ecodoc.core.waste_agg import act_period, norm_fkko
    from ecodoc.development.waste_passport import aggregate_state

    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    rows: "OrderedDict[str, dict]" = OrderedDict()
    passports = {norm_fkko(p.get("fkko", "")): p
                 for p in extra.get("waste_passports", [])
                 if isinstance(p, dict)}
    year = _year(ctx)

    def slot(code: str, name: str) -> dict:
        key = code or (name or "").lower()
        return rows.setdefault(key, {
            "fkko": code, "name": name, "hazard": 0, "generated": 0.0,
            "transferred": 0.0, "operations": [], "receivers": [],
            "composition": "", "passport": False, "protocols": [],
            "agg": "", "origin": "", "origin_typical": False,
            "norm_t": None, "fact_year": 0.0, "fact_years": {},
            "volume_m3": 0.0, "density": None, "licenses": [],
            "has_biotest": False, "has_kha": False})

    for w in ctx.wastes:
        code = norm_fkko(w.fkko_code)
        r = slot(code, w.name or "")
        r["name"] = r["name"] or w.name or ""
        r["hazard"] = r["hazard"] or int(w.hazard_class or 0)
        r["generated"] += _num(w.generated) or 0.0
        r["transferred"] += _num(w.transferred) or 0.0
        r["origin"] = r["origin"] or (w.origin or "").strip()
        r["agg"] = r["agg"] or (w.aggregate_state or "").strip()
        if w.composition and not r["composition"]:
            r["composition"] = w.composition.strip()

    for a in ctx.waste_acts:
        code = norm_fkko(a.fkko_code)
        r = slot(code, a.name or "")
        r["name"] = r["name"] or a.name or ""
        r["hazard"] = r["hazard"] or int(a.hazard_class or 0)
        if a.operation and a.operation not in r["operations"]:
            r["operations"].append(a.operation)
        if a.receiver and a.receiver not in r["receivers"]:
            r["receivers"].append(a.receiver)
        if a.license and a.license not in r["licenses"]:
            r["licenses"].append(a.license)
        ay = act_period(a)[0]
        m = _num(a.mass) or 0.0
        if ay:
            r["fact_years"][ay] = r["fact_years"].get(ay, 0.0) + m
            if ay == year:
                r["fact_year"] += m
        r["volume_m3"] += _num(a.volume_m3) or 0.0
        if r["density"] is None and _num(a.density):
            r["density"] = _num(a.density)

    for code, p in passports.items():
        r = slot(code, p.get("name", ""))
        r["passport"] = True
        r["hazard"] = r["hazard"] or int(p.get("hazard_class") or 0)
        r["origin"] = r["origin"] or str(p.get("origin") or "").strip()
        r["agg"] = r["agg"] or str(p.get("aggregate_state") or "").strip()
        comps = [c for c in (p.get("components") or []) if isinstance(c, dict)]
        if comps and not r["composition"]:
            r["composition"] = "; ".join(
                f"{c.get('name', '')}{(' ' + str(c['percent']) + '%') if c.get('percent') else ''}"
                for c in comps)

    # ручные реквизиты отхода (вкладка ОТХОДЫ) — главнее ИИ-разбора
    details = extra.get("waste_details") or {}
    if isinstance(details, dict):
        for code, d in details.items():
            if not isinstance(d, dict):
                continue
            r = rows.get(norm_fkko(code))
            if r is None:
                continue
            if d.get("origin"):
                r["origin"] = str(d["origin"]).strip()
            if d.get("aggregate_state"):
                r["agg"] = str(d["aggregate_state"]).strip()

    # нормативы образования из таблиц ООС/ПНООЛР (строительные главнее)
    for ow in sorted([x for x in (extra.get("oos_wastes") or []) if isinstance(x, dict)],
                     key=lambda x: 0 if x.get("stage") == "строительство" else 1):
        code = norm_fkko(ow.get("fkko", ""))
        if not code:
            continue
        r = rows.get(code)
        if r is None:
            continue
        if r["norm_t"] is None and _num(ow.get("mass_t")) is not None:
            r["norm_t"] = _num(ow.get("mass_t"))
        if not r["volume_m3"] and _num(ow.get("volume_m3")):
            r["volume_m3"] = _num(ow.get("volume_m3")) or 0.0
        if r["density"] is None and _num(ow.get("density")):
            r["density"] = _num(ow.get("density"))

    for lab in extra.get("lab_results", []):
        if not isinstance(lab, dict):
            continue
        target = str(lab.get("object") or "").lower()
        kind = str(lab.get("kind") or "")
        for r in rows.values():
            if not target or target in (r["name"] or "").lower() or \
                    (r["fkko"] and r["fkko"] in target):
                if kind and kind not in r["protocols"]:
                    r["protocols"].append(kind)
                low = kind.lower()
                if "био" in low:
                    r["has_biotest"] = True
                if "кха" in low or "хим" in low:
                    r["has_kha"] = True

    for r in rows.values():
        # класс опасности из последней цифры кода, если иначе неизвестен
        if not r["hazard"] and len(r["fkko"]) == 11 and r["fkko"][-1].isdigit():
            r["hazard"] = int(r["fkko"][-1])
        if not r["agg"]:
            r["agg"] = aggregate_state(r["fkko"])
        if not r["origin"]:
            t = typical_origin(r["fkko"])
            if t:
                r["origin"], r["origin_typical"] = t, True
        # плотность из пары т + м³ актов, если не задана явно
        if r["density"] is None and r["volume_m3"] and r["transferred"]:
            d = r["transferred"] / r["volume_m3"]
            if 0.05 <= d <= 8:
                r["density"] = round(d, 3)
    return list(rows.values())


def gaps(ctx: ReportContext, rows: list[dict] | None = None) -> list[str]:
    """Чего не хватает для полноценной инвентаризации."""
    rows = rows if rows is not None else collect(ctx)
    out = []
    org = ctx.organization
    if not rows:
        out.append("перечень пуст: загрузите справки-акты или заполните отходы вручную")
    if not _year(ctx):
        out.append("не указан отчётный год (Отчётность → год) — факт образования "
                   "считается по актам за год")
    if not main_object(ctx):
        out.append("не задан объект НВОС (код формата NN-NNNN-NNNNNN-Б) — титул "
                   "и раздел 1 без объекта")
    if not (org.name or org.short_name):
        out.append("не указано наименование организации")
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    if not (extra.get("departments") or extra.get("waste_sources")):
        out.append("не описаны подразделения/процессы, где образуются отходы "
                   "(вкладка ОБЪЕКТ → подразделения, extra.departments) — "
                   "раздел 2 заполнен типовыми процессами по группам ФККО")
    if not any(isinstance(x, dict) and x.get("fkko")
               for x in (extra.get("oos_wastes") or [])):
        out.append("нет нормативов образования отходов из проектной документации "
                   "— загрузите раздел ООС или ПНООЛР (графа «норматив, т/год» "
                   "заполняется из их таблиц отходов)")
    for r in rows:
        label = r["name"] or r["fkko"] or "отход"
        if not r["fkko"]:
            out.append(f"{label}: не указан код ФККО")
        if not r["hazard"]:
            out.append(f"{label}: не определён класс опасности")
        if not r["passport"] and r["hazard"] in (1, 2, 3, 4):
            out.append(f"{label}: нет паспорта отхода (нужен для I–IV класса)")
        if r["hazard"] == 5 and not r["has_biotest"]:
            out.append(f"{label}: V класс не подтверждён протоколом биотестирования")
        if not r["composition"]:
            out.append(f"{label}: не указан состав (из паспорта или протокола КХА)")
        if r["origin_typical"]:
            out.append(f"{label}: источник образования взят типовой по группе "
                       f"ФККО — уточните процесс/подразделение")
        if r["norm_t"] is None and not r["generated"] and not r["fact_year"]:
            out.append(f"{label}: нет ни норматива образования (ООС/ПНООЛР), "
                       f"ни фактической массы по актам")
        if not r["receivers"]:
            out.append(f"{label}: не указан получатель отхода — нет справок-актов "
                       f"с приёмщиком (вкладка ОТХОДЫ → акты)")
        elif not r["licenses"]:
            out.append(f"{label}: нет реквизитов лицензии получателя "
                       f"({'; '.join(r['receivers'])[:60]}) — укажите в акте")
    # правила протоколов — та же логика, что при загрузке
    from ecodoc.intake.crosscheck import lab_gaps
    out += lab_gaps(ctx)
    return out


# ──────────────────────────────────────────────────────────────────────────
# общие помощники .docx для документов контура «Отходы» (инвентаризация,
# ПНООЛР, ТУ): один стиль — Times New Roman 12, «Table Grid», поля 2/3 см
# ──────────────────────────────────────────────────────────────────────────
def docx_new(landscape: bool = False):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm, Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    # кириллический шрифт — иначе Word подставляет Calibri для русского текста
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts")
    if rfonts is not None:
        rfonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia",
                   "Times New Roman")
    for s in doc.sections:
        if landscape:
            s.orientation = WD_ORIENT.LANDSCAPE
            s.page_width, s.page_height = s.page_height, s.page_width
        s.left_margin, s.right_margin = Cm(2.5), Cm(1.5)
        s.top_margin, s.bottom_margin = Cm(2), Cm(2)
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        h = doc.styles[name]
        h.font.name = "Times New Roman"
        h.font.color.rgb = None
        h.font.size = Pt({"Heading 1": 14, "Heading 2": 13, "Heading 3": 12}[name])
        h.font.bold = True
    return doc


def docx_heading(doc, text: str, level: int = 1):
    return doc.add_heading(text, level=level)


def docx_para(doc, text: str, bold: bool = False, italic: bool = False,
              align: str = "", size: int | None = None):
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.shared import Pt

    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold, run.italic = bold, italic
    if size:
        run.font.size = Pt(size)
    if align == "center":
        p.alignment = AL.CENTER
    elif align == "right":
        p.alignment = AL.RIGHT
    elif align == "justify":
        p.alignment = AL.JUSTIFY
    return p


def docx_table(doc, header: list[str], rows: list[list], widths_cm: list | None = None,
               font_size: int = 10, empty_text: str = "данные отсутствуют"):
    """Таблица «Table Grid» с жирной шапкой; пустая — одной строкой-пометкой."""
    from docx.shared import Cm, Pt

    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"

    def _fill(cell, text, bold=False):
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(text))
        run.bold = bold
        run.font.size = Pt(font_size)

    for i, text in enumerate(header):
        _fill(table.rows[0].cells[i], text, bold=True)
    for r in rows:
        cells = table.add_row().cells
        for i, text in enumerate(r):
            _fill(cells[i], "—" if text in (None, "") else text)
    if not rows:
        cells = table.add_row().cells
        merged = cells[0].merge(cells[-1]) if len(cells) > 1 else cells[0]
        _fill(merged, empty_text)
    if widths_cm:
        table.autofit = False
        for row in table.rows:
            for cell, w in zip(row.cells, widths_cm):
                cell.width = Cm(w)
    doc.add_paragraph()
    return table


def docx_bullets(doc, items: list[str]):
    for it in items:
        doc.add_paragraph(it, style="List Bullet")


def docx_approval(doc, ctx: ReportContext, year: int | None = None):
    """Гриф «УТВЕРЖДАЮ» справа: должность, организация, подпись, дата."""
    org = ctx.organization
    y = year or _dt.date.today().year
    who = org.official_title or "Руководитель"
    lines = ["УТВЕРЖДАЮ", who, org.short_name or org.name or "",
             f"__________ {org.director_name or '________________'}",
             f"«___» __________ {y} г.", "М.П."]
    for i, line in enumerate(lines):
        docx_para(doc, line, bold=(i == 0), align="right")


def _org_rows(ctx: ReportContext) -> list[list[str]]:
    org = ctx.organization
    o = main_object(ctx)
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    rows = [
        ["Полное наименование", org.name or org.short_name or NA],
        ["Сокращённое наименование", org.short_name or NA],
        ["ИНН / КПП", f"{org.inn or NA} / {org.kpp or NA}"],
        ["ОГРН / ОГРНИП", org.ogrn or NA],
        ["ОКПО", org.okpo or NA],
        ["ОКВЭД (основной)", org.okved or NA],
        ["Юридический адрес", org.address or NA],
        ["Руководитель", " ".join(x for x in (org.official_title, org.director_name) if x)
         or NA],
        ["Телефон / e-mail", ", ".join(x for x in (org.phone, org.email) if x) or NA],
        ["Объект НВОС (код)", o.code if o else NA],
        ["Наименование объекта", (o.name if o else "") or extra.get("site_name") or NA],
        ["Категория объекта", (o.category if o else "") or NA],
        ["Адрес объекта", site_address(ctx) or NA],
    ]
    return rows


def _by_class(rows: list[dict]) -> list[list[str]]:
    out = []
    for cls in (1, 2, 3, 4, 5):
        rs = [r for r in rows if r["hazard"] == cls]
        if not rs:
            continue
        out.append([f"{_roman(cls)} класс", str(len(rs)),
                    fmt_num(sum(r["norm_t"] or 0 for r in rs) or None),
                    fmt_num(sum(r["fact_year"] or 0 for r in rs) or None),
                    fmt_num(sum(r["generated"] or 0 for r in rs) or None)])
    unknown = [r for r in rows if r["hazard"] not in (1, 2, 3, 4, 5)]
    if unknown:
        out.append(["класс не определён", str(len(unknown)), "—", "—",
                    fmt_num(sum(r["generated"] or 0 for r in unknown) or None)])
    out.append(["ИТОГО", str(len(rows)),
                fmt_num(sum(r["norm_t"] or 0 for r in rows) or None),
                fmt_num(sum(r["fact_year"] or 0 for r in rows) or None),
                fmt_num(sum(r["generated"] or 0 for r in rows) or None)])
    return out


def _roman(cls) -> str:
    from ecodoc.core import fkko
    return fkko.roman(cls) or "—"


def _fmt_code(code: str) -> str:
    from ecodoc.core import fkko
    return fkko.fmt(code) if code else NA


_ACC = {"утилизация": "утилизацию", "обработка": "обработку",
        "обезвреживание": "обезвреживание", "размещение": "размещение",
        "хранение": "хранение", "захоронение": "захоронение"}


def op_accusative(op: str) -> str:
    """«утилизация» → «утилизацию» (для «передача на …»)."""
    return _ACC.get((op or "").strip().lower(), op)


def _origin_text(r: dict) -> str:
    """Источник образования для таблиц: типовой — с пометкой, пустой — «—»."""
    if not r.get("origin"):
        return NA
    return r["origin"] + (" (типовой процесс по группе ФККО)" if r.get("origin_typical") else "")


def _handling(r: dict) -> str:
    ops = ", ".join(op_accusative(o) for o in r["operations"]) if r["operations"] else ""
    rec = "; ".join(r["receivers"]) if r["receivers"] else ""
    if ops and rec:
        return f"передача на {ops}: {rec}"
    if ops:
        return f"передача на {ops} специализированной организации по договору"
    if rec:
        return f"передача по договору: {rec}"
    return "накопление, передача лицензированной организации по договору"


def _departments(ctx: ReportContext) -> list[dict]:
    """Подразделения/процессы из extra.departments: [{name, process, wastes:[fkko]}]."""
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    src = extra.get("departments") or extra.get("waste_sources") or []
    return [d for d in src if isinstance(d, dict) and d.get("name")]


def _sec_intro(doc, ctx: ReportContext, rows: list[dict]) -> None:
    year = _year(ctx)
    org = ctx.organization
    o = main_object(ctx)
    docx_heading(doc, "Введение", 1)
    docx_para(doc, (
        f"Инвентаризация отходов производства и потребления проведена "
        f"{org.short_name or org.name or 'организацией'} на объекте "
        f"{(o.name if o else '') or 'НВОС'} (код объекта "
        f"{o.code if o else 'не присвоен'}, "
        f"{o.category + ' категория, ' if o and o.category else ''}"
        f"адрес: {site_address(ctx) or NOT_SET}) по состоянию на "
        f"{str(year) + ' год' if year else 'текущий период'}."), align="justify")
    docx_para(doc, (
        "Цель инвентаризации — установить полный перечень видов отходов, "
        "образующихся в результате хозяйственной деятельности, их количество, "
        "источники (процессы) образования, классы опасности и способы "
        "обращения — как основу для учёта отходов, паспортизации, разработки "
        "нормативов образования и представления отчётности."), align="justify")
    docx_para(doc, "Основание и нормативная база:", bold=True)
    docx_bullets(doc, [
        "Федеральный закон от 24.06.1998 № 89-ФЗ «Об отходах производства и "
        "потребления» — ст. 11 (требования при эксплуатации объектов), ст. 14 "
        "(отнесение отходов к классам опасности, паспорта), ст. 18 (нормативы "
        "образования отходов и лимиты), ст. 19 (учёт отходов);",
        "Федеральный классификационный каталог отходов (приказ Росприроднадзора "
        "от 22.05.2017 № 242, с изменениями);",
        "Критерии отнесения отходов к I–V классам опасности (приказ Минприроды "
        "России от 31.03.2025 № 158);",
        "Порядок учёта в области обращения с отходами (приказ Минприроды России "
        "от 08.12.2020 № 1028, с изменениями);",
        "Методические указания по разработке проектов нормативов образования "
        "отходов и лимитов на их размещение (приказ Минприроды России от "
        "07.12.2020 № 1021) — структура сведений об отходах и о хозяйственной "
        "деятельности;",
        "Типовая форма паспорта отходов I–IV классов опасности (приказ Минприроды "
        "России от 15.05.2026 № 286, с 01.09.2026; ранее — № 1026 от 08.12.2020).",
    ])
    docx_para(doc, (
        f"Всего по результатам инвентаризации выявлено {len(rows)} видов отходов; "
        f"из них I–IV классов опасности — "
        f"{sum(1 for r in rows if r['hazard'] in (1, 2, 3, 4))}, V класса — "
        f"{sum(1 for r in rows if r['hazard'] == 5)}."), align="justify")


def _sec_general(doc, ctx: ReportContext) -> None:
    docx_heading(doc, "1. Общие сведения об организации и объекте", 1)
    docx_table(doc, ["Показатель", "Сведения"], _org_rows(ctx), widths_cm=[6, 11],
               font_size=11)
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    prof = extra.get("profile") or {}
    notes = []
    if prof.get("is_msp"):
        notes.append("Организация относится к субъектам малого и среднего "
                     "предпринимательства.")
    o = main_object(ctx)
    cat = (o.category if o else "") or ""
    if cat in ("I", "II"):
        notes.append(f"Объект {cat} категории: нормативы образования отходов и "
                     "лимиты на их размещение устанавливаются в составе "
                     "комплексного экологического разрешения (I) / декларации "
                     "о воздействии (II) — ст. 18 ФЗ-89.")
    elif cat in ("III", "IV"):
        notes.append(f"Объект {cat} категории: ПНООЛР не разрабатывается, "
                     "отчётность об образовании отходов представляется в "
                     "уведомительном порядке (ст. 18 ФЗ-89).")
    for n in notes:
        docx_para(doc, n, align="justify")


def _sec_sources(doc, ctx: ReportContext, rows: list[dict]) -> None:
    docx_heading(doc, "2. Источники образования отходов (характеристика "
                      "хозяйственной деятельности)", 1)
    org = ctx.organization
    o = main_object(ctx)
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    prof = extra.get("profile") or {}
    mode = []
    if prof.get("staff"):
        mode.append(f"численность персонала — {prof['staff']} чел.")
    if prof.get("work_mode"):
        mode.append(f"режим работы — {prof['work_mode']}")
    if prof.get("area_m2"):
        mode.append(f"площадь территории — {prof['area_m2']} м²")
    docx_para(doc, (
        f"Основной вид деятельности по ОКВЭД: {org.okved or NOT_SET}. "
        f"Объект: {(o.name if o else '') or extra.get('site_name') or NOT_SET}. "
        + ("; ".join(mode).capitalize() + "." if mode else
           "Режим работы, численность персонала, площадь территории и помещений "
           "принимаются по исходным данным предприятия.")), align="justify")
    deps = _departments(ctx)
    docx_para(doc, "Подразделения (участки) и технологические процессы, в "
                   "результате которых образуются отходы (таблица по образцу "
                   "приложения 2 к приказу № 1021):", align="justify")
    table_rows = []
    if deps:
        for d in deps:
            codes = {str(c).replace(" ", "") for c in (d.get("wastes") or [])}
            names = [r["name"] for r in rows if r["fkko"] in codes] or [NA]
            table_rows.append([d.get("name", ""), d.get("materials", "") or NA,
                               d.get("process", "") or NA,
                               d.get("product", "") or NA, "; ".join(names),
                               d.get("handling", "") or "накопление и передача "
                                                        "лицензированной организации"])
    else:
        # без описания подразделений — по одной строке на отход с типовым
        # процессом; сырьё/продукция неизвестны
        for r in rows:
            table_rows.append([NA, NA, _origin_text(r), NA,
                               r["name"] or r["fkko"], _handling(r)])
    docx_table(doc, ["Подразделение / участок", "Используемое сырьё, материалы",
                     "Производственная операция (процесс)",
                     "Производимая продукция (услуги, работы)",
                     "Образующиеся отходы", "Операции по обращению с отходами"],
               table_rows, widths_cm=[3, 3, 4, 3, 5, 5], font_size=9)


def _sec_list(doc, ctx: ReportContext, rows: list[dict]) -> None:
    year = _year(ctx)
    docx_heading(doc, "3. Перечень отходов, образующихся на объекте", 1)
    docx_para(doc, (
        "Наименования и коды — по ФККО; класс опасности — по паспорту отхода "
        "(I–IV) или по подтверждению V класса; агрегатное состояние и "
        "физическая форма — по 9–10 знакам кода ФККО; норматив образования — "
        "по проектной документации (ООС/ПНООЛР), фактическое образование — по "
        "справкам-актам за отчётный год."), align="justify")
    table_rows = []
    for i, r in enumerate(rows, start=1):
        table_rows.append([
            str(i), r["name"] or NA, _fmt_code(r["fkko"]), _roman(r["hazard"]),
            r["agg"] or NA, _origin_text(r),
            fmt_num(r["norm_t"]) if r["norm_t"] is not None else NA,
            fmt_num(r["fact_year"]) if r["fact_year"] else
            (fmt_num(r["generated"]) if r["generated"] else "—"),
            _handling(r)])
    docx_table(doc, ["№", "Наименование отхода по ФККО", "Код ФККО", "Класс",
                     "Агрегатное состояние и физическая форма",
                     "Источник образования (процесс)",
                     "Норматив образования, т/год",
                     f"Фактически образовано{(' за ' + str(year) + ' г.') if year else ''}, т",
                     "Способ обращения, получатель"],
               table_rows, widths_cm=[0.8, 4.5, 2.4, 1.1, 2.6, 3.4, 1.8, 1.8, 4.2],
               font_size=8)
    # факт по годам — если акты разнесены по годам, эколог видит динамику
    years = sorted({y for r in rows for y in r["fact_years"]})
    if years:
        docx_para(doc, "Фактическое образование отходов по годам (по "
                       "справкам-актам), т:", bold=True)
        yrows = []
        for r in rows:
            if not r["fact_years"]:
                continue
            yrows.append([r["name"] or r["fkko"], _fmt_code(r["fkko"])]
                         + [fmt_num(r["fact_years"].get(y)) if r["fact_years"].get(y) else "—"
                            for y in years])
        docx_table(doc, ["Отход", "Код ФККО"] + [str(y) for y in years], yrows,
                   font_size=9)


def _sec_summary(doc, ctx: ReportContext, rows: list[dict]) -> None:
    year = _year(ctx)
    docx_heading(doc, "4. Сводные данные по классам опасности", 1)
    docx_table(doc, ["Класс опасности", "Видов отходов",
                     "Норматив образования, т/год",
                     f"Факт{(' за ' + str(year) + ' г.') if year else ''}, т",
                     "Образовано за период (движение), т"],
               _by_class(rows), widths_cm=[4, 2.5, 3.5, 3.5, 3.5], font_size=10)


def _sec_documents(doc, ctx: ReportContext, rows: list[dict]) -> None:
    docx_heading(doc, "5. Подтверждающие документы по видам отходов", 1)
    docx_para(doc, (
        "Паспорт обязателен для отходов I–IV классов (ст. 14 ФЗ-89); для V "
        "класса — подтверждение отнесения (протокол биотестирования / "
        "расчёт по критериям приказа № 158). Состав — из паспорта или "
        "протокола КХА."), align="justify")
    table_rows = []
    for i, r in enumerate(rows, start=1):
        need_pass = r["hazard"] in (1, 2, 3, 4)
        if need_pass:
            pas = "есть" if r["passport"] else f"НЕТ — требуется"
        else:
            pas = "не требуется (V класс)" if r["hazard"] == 5 else "класс не определён"
        prot = ", ".join(r["protocols"]) or "нет"
        if r["hazard"] == 5 and not r["has_biotest"]:
            prot += "; биотестирование — требуется"
        lic = "; ".join(r["licenses"]) or NA
        table_rows.append([str(i), r["name"] or r["fkko"], _roman(r["hazard"]), pas,
                           prot, (r["composition"] or NA)[:160], lic])
    docx_table(doc, ["№", "Отход", "Класс", "Паспорт отхода", "Протоколы",
                     "Состав, %", "Лицензия получателя"],
               table_rows, widths_cm=[0.8, 4.5, 1.2, 2.5, 3, 5.5, 3.5], font_size=8)


def _sec_conclusions(doc, ctx: ReportContext, rows: list[dict]) -> None:
    docx_heading(doc, "6. Выводы и рекомендации", 1)
    year = _year(ctx)
    o = main_object(ctx)
    cat = (o.category if o else "") or ""
    no_pass = [r["name"] or r["fkko"] for r in rows
               if r["hazard"] in (1, 2, 3, 4) and not r["passport"]]
    no_bio = [r["name"] or r["fkko"] for r in rows
              if r["hazard"] == 5 and not r["has_biotest"]]
    no_norm = [r["name"] or r["fkko"] for r in rows if r["norm_t"] is None]
    items = [
        f"По результатам инвентаризации на объекте образуется {len(rows)} видов "
        f"отходов; фактическое образование{(' за ' + str(year) + ' г.') if year else ''} "
        f"— {fmt_num(sum(r['fact_year'] or 0 for r in rows) or None)} т "
        f"(по справкам-актам), всего по движению — "
        f"{fmt_num(sum(r['generated'] or 0 for r in rows) or None)} т.",
        "Перечень отходов подлежит внесению в журнал учёта отходов (приказ "
        "№ 1028) и использованию при заполнении формы 2-ТП (отходы), "
        "декларации о плате за НВОС и регионального кадастра отходов.",
    ]
    if no_pass:
        items.append("Оформить паспорта отходов I–IV классов (приказ № 286): "
                     + "; ".join(no_pass) + ".")
    if no_bio:
        items.append("Подтвердить V класс опасности протоколами биотестирования: "
                     + "; ".join(no_bio) + ".")
    if cat in ("I", "II"):
        items.append("Разработать (актуализировать) нормативы образования отходов и "
                     "лимиты на их размещение по приказу № 1021 (объект "
                     f"{cat} категории)." + (
                         " Нормативы отсутствуют для: " + "; ".join(no_norm) + "."
                         if no_norm else ""))
    elif cat in ("III", "IV"):
        items.append(f"Объект {cat} категории — ПНООЛР не требуется; сведения об "
                     "образовании отходов представляются в составе отчётности "
                     "(ст. 18 ФЗ-89).")
    else:
        items.append("Категория объекта НВОС не задана: для I–II категорий "
                     "нужны нормативы образования и лимиты (приказ № 1021), "
                     "для III–IV — отчётность в уведомительном порядке.")
    items.append("Обеспечить накопление отходов не более 11 месяцев (ст. 1 ФЗ-89) "
                 "в оборудованных местах, передачу — только лицензированным "
                 "организациям с оформлением актов.")
    items.append("Актуализировать инвентаризацию при изменении технологии, "
                 "появлении новых видов отходов и не реже одного раза в 5 лет "
                 "(рекомендуется — ежегодно при подготовке отчётности).")
    for it in items:
        docx_para(doc, "• " + it, align="justify")


def _sec_gaps(doc, ctx: ReportContext, rows: list[dict]) -> None:
    problems = gaps(ctx, rows)
    docx_heading(doc, "Приложение. Что дозаполнить (пометки программы)", 1)
    if not problems:
        docx_para(doc, "Замечаний нет — перечень заполнен.")
        return
    docx_para(doc, "Сведения, которых нет в базе программы, в тексте отмечены "
                   "«—» или нейтральной формулировкой; ниже — полный список, "
                   "что дозаполнить и откуда взять:", italic=True)
    for g in problems:
        docx_para(doc, "• " + g, size=10)


def generate_docx(ctx: ReportContext, out_path: str | Path) -> Path:
    """Отчёт об инвентаризации отходов (.docx)."""
    rows = collect(ctx)
    org = ctx.organization
    o = main_object(ctx)
    year = _year(ctx)
    doc = docx_new()

    docx_approval(doc, ctx, year=_dt.date.today().year)
    for _ in range(4):
        doc.add_paragraph()
    docx_para(doc, DOC_TITLE, bold=True, align="center", size=16)
    docx_para(doc, org.name or org.short_name or "", bold=True, align="center", size=14)
    docx_para(doc, f"Объект: {(o.name if o else '') or 'НВОС'}"
                   + (f" (код {o.code})" if o else ""), align="center")
    if site_address(ctx):
        docx_para(doc, f"Адрес: {site_address(ctx)}", align="center")
    docx_para(doc, f"по состоянию на {str(year) + ' год' if year else _dt.date.today().year}",
              align="center")
    for _ in range(8):
        doc.add_paragraph()
    docx_para(doc, f"{_dt.date.today().year} г.", align="center")
    doc.add_page_break()

    docx_heading(doc, "Содержание", 1)
    for line in ["Введение",
                 "1. Общие сведения об организации и объекте",
                 "2. Источники образования отходов",
                 "3. Перечень отходов, образующихся на объекте",
                 "4. Сводные данные по классам опасности",
                 "5. Подтверждающие документы по видам отходов",
                 "6. Выводы и рекомендации",
                 "Приложение. Что дозаполнить"]:
        docx_para(doc, line)
    doc.add_page_break()

    _sec_intro(doc, ctx, rows)
    _sec_general(doc, ctx)
    _sec_sources(doc, ctx, rows)
    _sec_list(doc, ctx, rows)
    _sec_summary(doc, ctx, rows)
    _sec_documents(doc, ctx, rows)
    _sec_conclusions(doc, ctx, rows)
    doc.add_paragraph()
    docx_para(doc, f"{org.official_title or 'Руководитель'}\t\t_____________\t"
                   f"{org.director_name or '________________'}")
    docx_para(doc, "Ответственный за обращение с отходами\t_____________\t"
                   f"{(ctx.extra or {}).get('waste_responsible') or '________________'}")
    _sec_gaps(doc, ctx, rows)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def generate_xlsx(ctx: ReportContext, out_path: str | Path) -> Path:
    """Перечень отходов (.xlsx): титул, перечень, чего не хватает."""
    rows = collect(ctx)
    org = ctx.organization
    wb = xlsx.new_workbook()

    ws = wb.create_sheet("Титул")
    xlsx.merge(ws, "A1:F1", TITLE.upper(), bold=True, align="center")
    xlsx.merge(ws, "A2:F2", f"по объекту НВОС за {ctx.period.year or '____'} год",
               align="center")
    o = main_object(ctx)
    info = [("Организация", org.name or org.short_name), ("ИНН", org.inn),
            ("ОГРН", org.ogrn), ("Адрес", org.address),
            ("Объект НВОС", (o.code if o else "") or "—"),
            ("Адрес объекта", site_address(ctx) or "—"),
            ("Ответственный", org.director_name or "—")]
    for i, (label, value) in enumerate(info, start=4):
        xlsx.cell(ws, f"A{i}", label, bold=True)
        xlsx.merge(ws, f"B{i}:F{i}", value or "—", align="left")
    xlsx.widths(ws, {"A": 28, "B": 24, "C": 18, "D": 18, "E": 18, "F": 18})

    ws2 = wb.create_sheet("Перечень отходов")
    head = ["№", "Наименование отхода", "Код ФККО", "Класс опасности",
            "Агрегатное состояние", "Источник образования",
            "Норматив образования, т/год", "Факт за год, т",
            "Образовано за период, т", "Передано, т", "Вид обращения",
            "Приёмщики / полигоны", "Состав (из паспорта/КХА)",
            "Паспорт", "Протоколы"]
    xlsx.header_row(ws2, 1, head)
    xlsx.widths(ws2, {"A": 5, "B": 42, "C": 16, "D": 8, "E": 22, "F": 30, "G": 12,
                      "H": 12, "I": 12, "J": 12, "K": 18, "L": 26, "M": 34,
                      "N": 9, "O": 16})
    for i, r in enumerate(rows, start=1):
        xlsx.data_row(ws2, i + 1, [
            i, r["name"] or "—", r["fkko"] or "—", r["hazard"] or "—",
            r["agg"] or "—",
            _origin_text(r),
            r["norm_t"], r["fact_year"] or None,
            r["generated"] or None, r["transferred"] or None,
            ", ".join(r["operations"]) or "—",
            ", ".join(r["receivers"]) or "—",
            r["composition"] or "нет данных",
            "есть" if r["passport"] else "нет",
            ", ".join(r["protocols"]) or "нет"])

    ws3 = wb.create_sheet("Чего не хватает")
    xlsx.header_row(ws3, 1, ["Замечание"])
    xlsx.widths(ws3, {"A": 110})
    problems = gaps(ctx, rows) or ["замечаний нет — перечень заполнен"]
    for i, text in enumerate(problems, start=2):
        xlsx.data_row(ws3, i, [text])

    return xlsx.save(wb, Path(out_path))


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    """Документ инвентаризации: .docx — отчёт, .xlsx — перечень (по расширению)."""
    out = Path(out_path)
    if out.suffix.lower() == ".xlsx":
        return generate_xlsx(ctx, out)
    return generate_docx(ctx, out)


def generate_all(ctx: ReportContext, out_dir: str | Path, stem: str = "") -> dict:
    """Отчёт .docx + перечень .xlsx; ответ API {path, files, gaps}."""
    out_dir = Path(out_dir)
    stem = stem or f"инвентаризация_отходов{('_' + str(ctx.period.year)) if ctx.period.year else ''}"
    docx_path = generate_docx(ctx, out_dir / f"{stem}.docx")
    xlsx_path = generate_xlsx(ctx, out_dir / f"{stem}.xlsx")
    return {"path": str(docx_path), "files": [str(docx_path), str(xlsx_path)],
            "gaps": gaps(ctx)}
