"""Декларация о воздействии на окружающую среду (ДВОС) — объекты II категории.

Правовая основа (проверено по состоянию на август 2026):

* ст. 31.2 Федерального закона от 10.01.2002 № 7-ФЗ «Об охране окружающей
  среды» — обязанность лиц, ведущих деятельность на объектах II категории
  (кроме имеющих КЭР), представлять декларацию; состав сведений — п. 3;
  одновременно с декларацией представляются РАСЧЁТЫ нормативов допустимых
  выбросов и сбросов (п. 4); подаётся один раз в СЕМЬ лет при условии
  неизменности технологических процессов основных производств, качественных
  и количественных характеристик выбросов, сбросов и стационарных
  источников (п. 6);
* форма и порядок заполнения — приказ Минприроды России от 19.03.2025 № 117
  (зарегистрирован Минюстом России 14.04.2025, рег. № 81831; вступил в силу
  01.09.2025, действует шесть лет — до 01.09.2031). Он ЗАМЕНИЛ приказ
  от 11.10.2018 № 509 (в ред. приказа от 23.06.2020 № 383), который с
  01.09.2025 утратил силу — реквизиты № 509 в новых декларациях не указывать.

Состав формы по приказу № 117: титульный лист (код объекта НВОС,
наименование/ОПФ/адрес, код и вид основной деятельности) и разделы:
  I   — виды и объём производимой продукции (товара);
  II  — информация о реализации природоохранных мероприятий;
  III — данные об авариях и инцидентах, повлекших негативное воздействие
        на окружающую среду, за предыдущие семь лет;
  IV  — масса выбросов загрязняющих веществ в атмосферный воздух;
  V   — масса сбросов загрязняющих веществ в водные объекты;
  VI  — сведения об образовании и размещении отходов производства и
        потребления (за отчётный год + декларируемые на следующие 7 лет);
  VII — информация о программе производственного экологического контроля.

Что берётся из базы: организация и объект — из карточек; выбросы —
ctx.pollutants (среда «воздух»); сбросы — ctx.pollutants (среда «вода») +
выпуски из ctx.extra['water']['discharge']; отходы — ctx.wastes /
ctx.waste_acts (через инвентаризацию отходов); ПЭК — ctx.extra['pek'].
Продукция, мероприятия и аварии машиной не выдумываются: они читаются из
ctx.extra['dvos'] ({"products": [...], "measures": [...], "accidents": [...]}),
а при их отсутствии в документе остаётся пометка «[требуется: …]», и та же
строка возвращается из gaps(ctx) — пользователь видит список до генерации.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import Medium, ReportContext

TITLE = "Декларация о воздействии на окружающую среду"

NPA = ("приказом Минприроды России от 19.03.2025 № 117 (зарегистрирован "
       "Минюстом России 14.04.2025, рег. № 81831; действует с 01.09.2025, "
       "взамен приказа от 11.10.2018 № 509) в соответствии со статьёй 31.2 "
       "Федерального закона от 10.01.2002 № 7-ФЗ «Об охране окружающей среды»")

# Разделы формы приказа № 117 — названия из формы, не из головы.
SECTIONS: list[tuple[str, str]] = [
    ("products", "Раздел I. Виды и объём производимой продукции (товара)"),
    ("measures", "Раздел II. Информация о реализации природоохранных "
                 "мероприятий"),
    ("accidents", "Раздел III. Данные об авариях и инцидентах, повлекших "
                  "за собой негативное воздействие на окружающую среду"),
    ("air", "Раздел IV. Масса выбросов загрязняющих веществ в атмосферный "
            "воздух"),
    ("water", "Раздел V. Масса сбросов загрязняющих веществ в водные объекты"),
    ("waste", "Раздел VI. Сведения об образовании и размещении отходов "
              "производства и потребления"),
    ("pek", "Раздел VII. Информация о программе производственного "
            "экологического контроля"),
]

# чего машина взять не может — единые формулировки для текста и gaps()
EXTERNAL = {
    "products": "виды и объём производимой продукции (товара) — заполните "
                "extra['dvos']['products'] или внесите вручную (данные "
                "бухгалтерского учёта, максимальные значения)",
    "measures": "перечень реализованных природоохранных мероприятий "
                "(extra['dvos']['measures'])",
    "accidents": "данные об авариях и инцидентах за предыдущие 7 лет "
                 "(extra['dvos']['accidents']; если их не было — укажите "
                 "пустой список)",
    "gs": "максимальные разовые выбросы (г/с) по веществам — из "
          "инвентаризации источников или проекта НДВ",
    "ndv": "расчёты нормативов допустимых выбросов (и сбросов — при их "
           "наличии), прилагаемые к декларации (п. 4 ст. 31.2 ФЗ-7)",
    "groro": "номера объектов размещения отходов в ГРОРО (для размещаемых "
             "отходов)",
    "pek": "программа производственного экологического контроля: дата "
           "утверждения и ответственное лицо (extra['pek'])",
}

# ОПФ по префиксу наименования — только очевидные случаи, иначе [требуется]
_OPF = {
    "ООО": "Общество с ограниченной ответственностью",
    "АО": "Акционерное общество",
    "ПАО": "Публичное акционерное общество",
    "ЗАО": "Закрытое акционерное общество",
    "МУП": "Муниципальное унитарное предприятие",
    "ГУП": "Государственное унитарное предприятие",
    "ИП": "Индивидуальный предприниматель",
}


def _num(value) -> str:
    if value in (None, ""):
        return "—"
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return str(value)
    return f"{d.normalize():f}" if d else "0"


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value or 0).replace(",", "."))
    except Exception:
        return Decimal("0")


def opf(ctx: ReportContext) -> str:
    """Организационно-правовая форма — поле титульного листа."""
    org = ctx.organization
    if org.is_individual:
        return "Индивидуальный предприниматель"
    name = (org.name or org.short_name or "").strip()
    for prefix, full in _OPF.items():
        if name.startswith(prefix + " ") or name.startswith(prefix + "«"):
            return full
        if full.lower() in name.lower():
            return full
    return "[требуется: организационно-правовая форма]"


def _dvos_extra(ctx: ReportContext) -> dict:
    d = (ctx.extra or {}).get("dvos", {})
    return d if isinstance(d, dict) else {}


def products(ctx: ReportContext) -> list[dict]:
    """Раздел I: продукция из extra['dvos']['products'] — не выдумывается."""
    out = []
    for p in _dvos_extra(ctx).get("products", []) or []:
        if isinstance(p, dict):
            out.append({"name": str(p.get("name") or ""),
                        "volume": p.get("volume"),
                        "unit": str(p.get("unit") or "")})
        elif isinstance(p, str) and p.strip():
            out.append({"name": p.strip(), "volume": None, "unit": ""})
    return out


def measures(ctx: ReportContext) -> list[dict]:
    """Раздел II: реализованные природоохранные мероприятия."""
    out = []
    for m in _dvos_extra(ctx).get("measures", []) or []:
        if isinstance(m, dict):
            out.append({"name": str(m.get("name") or ""),
                        "start": str(m.get("start") or ""),
                        "end": str(m.get("end") or ""),
                        "cost": m.get("cost"),
                        "result": str(m.get("result") or "")})
        elif isinstance(m, str) and m.strip():
            out.append({"name": m.strip(), "start": "", "end": "",
                        "cost": None, "result": ""})
    return out


def accidents(ctx: ReportContext) -> list[dict] | None:
    """Раздел III: аварии/инциденты за 7 лет.

    None — сведения не заводились (пометка «[требуется]»); пустой список —
    пользователь подтвердил, что аварий и инцидентов не было.
    """
    d = _dvos_extra(ctx)
    if "accidents" not in d:
        return None
    out = []
    for a in d.get("accidents") or []:
        if isinstance(a, dict):
            out.append({"kind": str(a.get("kind") or "авария"),
                        "date": str(a.get("date") or ""),
                        "end_date": str(a.get("end_date") or ""),
                        "description": str(a.get("description") or ""),
                        "impact": str(a.get("impact") or ""),
                        "damage": a.get("damage"),
                        "measures": str(a.get("measures") or "")})
        elif isinstance(a, str) and a.strip():
            out.append({"kind": "авария", "date": "", "end_date": "",
                        "description": a.strip(), "impact": "", "damage": None,
                        "measures": ""})
    return out


def rows_air(ctx: ReportContext) -> list[dict]:
    """Раздел IV: выбросы по веществам, т/год (нормативные и сверх)."""
    out = []
    for p in ctx.pollutants:
        if p.medium != Medium.AIR:
            continue
        norm = _dec(p.mass_norm)
        over = _dec(p.mass_limit) + _dec(p.mass_over)
        out.append({"code": p.code or "", "name": p.name or "",
                    "norm": norm, "over": over, "total": norm + over})
    return out


def rows_water(ctx: ReportContext) -> list[dict]:
    """Раздел V: сбросы по веществам, т/год."""
    out = []
    for p in ctx.pollutants:
        if p.medium != Medium.WATER:
            continue
        norm = _dec(p.mass_norm)
        over = _dec(p.mass_limit) + _dec(p.mass_over)
        out.append({"code": p.code or "", "name": p.name or "",
                    "norm": norm, "over": over, "total": norm + over})
    return out


def water_bodies(ctx: ReportContext) -> list[str]:
    """Приёмники сточных вод — из выпусков 2-ТП (водхоз), если заведены."""
    water = (ctx.extra or {}).get("water", {}) or {}
    out = []
    for d in water.get("discharge", []) or []:
        if isinstance(d, dict) and d.get("receiver"):
            name = str(d["receiver"])
            if name not in out:
                out.append(name)
    return out


def rows_waste(ctx: ReportContext) -> list[dict]:
    """Раздел VI: образование и размещение отходов по видам (классам)."""
    from ecodoc.core.waste_agg import norm_fkko
    from ecodoc.development.waste_inventory import collect

    placed: dict[str, Decimal] = {}
    for w in ctx.wastes:
        code = norm_fkko(w.fkko_code)
        placed[code] = placed.get(code, Decimal("0")) + \
            _dec(w.placed_norm) + _dec(w.placed_over)

    out = []
    for r in collect(ctx):
        out.append({"fkko": r["fkko"], "name": r["name"],
                    "hazard": r["hazard"] or 0,
                    "generated": _dec(r["generated"]),
                    "placed": placed.get(r["fkko"], Decimal("0")),
                    "transferred": _dec(r["transferred"])})
    return out


def pek_info(ctx: ReportContext) -> dict:
    """Раздел VII: сведения о программе ПЭК из extra['pek']."""
    pek = (ctx.extra or {}).get("pek", {}) or {}
    if not isinstance(pek, dict):
        pek = {}
    return {"approved_date": str(pek.get("approved_date") or ""),
            "responsible": str(pek.get("responsible") or ""),
            "points": [p for p in (pek.get("points") or [])
                       if isinstance(p, dict)]}


def declared_period(ctx: ReportContext) -> tuple[int, int]:
    """Период действия декларации: 7 лет с года подачи (п. 6 ст. 31.2)."""
    year = ctx.period.year or date.today().year
    return year, year + 6


def gaps(ctx: ReportContext) -> list[str]:
    """Чего не хватает для декларации — тот же список, что и пометки в тексте."""
    out: list[str] = []
    org = ctx.organization
    if not (org.name or org.short_name):
        out.append("не заполнено наименование организации")
    if not org.okved:
        out.append("не указан код основного вида деятельности (ОКВЭД) — "
                   "поле титульного листа")
    if not ctx.objects:
        out.append("не заведён объект НВОС: декларация подаётся по коду объекта")
    else:
        for o in ctx.objects:
            if not o.code:
                out.append(f"объект «{o.name or '?'}»: не указан код объекта НВОС")
            if o.category and o.category.strip().upper() not in ("II", "2"):
                out.append(f"объект {o.code or o.name}: категория "
                           f"«{o.category}» — декларация о воздействии "
                           f"представляется для объектов II категории "
                           f"(п. 1 ст. 31.2 ФЗ-7)")
    if not products(ctx):
        out.append(f"требуется: {EXTERNAL['products']}")
    if not measures(ctx):
        out.append(f"требуется: {EXTERNAL['measures']}")
    if accidents(ctx) is None:
        out.append(f"требуется: {EXTERNAL['accidents']}")
    air = rows_air(ctx)
    if air:
        out.append(f"требуется: {EXTERNAL['gs']}")
    water = rows_water(ctx)
    wastes = rows_waste(ctx)
    if not (air or water or wastes):
        out.append("нет ни выбросов, ни сбросов, ни отходов — разделы IV–VI "
                   "нечем наполнять: загрузите исходные данные")
    if any(r["placed"] for r in wastes):
        out.append(f"требуется: {EXTERNAL['groro']}")
    out.append(f"требуется: {EXTERNAL['ndv']}")
    if not pek_info(ctx)["approved_date"]:
        out.append(f"требуется: {EXTERNAL['pek']}")
    return out


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    """Собрать декларацию (.docx) по разделам формы приказа № 117."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.shared import Cm, Pt

    org = ctx.organization
    obj = ctx.objects[0] if ctx.objects else None
    y1, y2 = declared_period(ctx)

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    for s in doc.sections:
        s.left_margin, s.right_margin = Cm(3), Cm(1.5)
        s.top_margin, s.bottom_margin = Cm(2), Cm(2)

    # ── титульный лист (состав полей — по форме приказа № 117) ───────────
    h = doc.add_paragraph()
    h.alignment = AL.CENTER
    run = h.add_run(TITLE.upper())
    run.bold = True
    run.font.size = Pt(14)
    sub = doc.add_paragraph()
    sub.alignment = AL.CENTER
    sub.add_run(f"Форма утверждена {NPA}.").italic = True

    doc.add_paragraph()
    _table(doc, ["Показатель титульного листа", "Значение"], [
        ["Код объекта, оказывающего негативное воздействие "
         "на окружающую среду",
         obj.code if obj and obj.code else "[требуется: код объекта НВОС]"],
        ["Наименование юридического лица / Ф.И.О. индивидуального "
         "предпринимателя",
         org.name or org.short_name or "[требуется: наименование организации]"],
        ["Организационно-правовая форма", opf(ctx)],
        ["Адрес (место нахождения)",
         org.address or "[требуется: адрес организации]"],
        ["Адрес объекта", obj.address if obj and obj.address
         else "[требуется: адрес объекта]"],
        ["Категория объекта",
         (obj.category if obj and obj.category else "II")],
        ["Код и наименование основного вида деятельности (ОКВЭД)",
         org.okved or "[требуется: код ОКВЭД]"],
        ["ИНН / ОГРН", f"{org.inn or '—'} / {org.ogrn or '—'}"],
        ["Период действия декларации", f"{y1}–{y2} гг."],
    ])
    doc.add_paragraph(
        "Декларация представляется один раз в семь лет при условии "
        "неизменности технологических процессов основных производств, "
        "качественных и количественных характеристик выбросов, сбросов "
        "загрязняющих веществ и стационарных источников (п. 6 ст. 31.2 "
        "Федерального закона № 7-ФЗ).")
    doc.add_page_break()

    for key, title in SECTIONS:
        head = doc.add_paragraph()
        head.add_run(title).bold = True

        if key == "products":
            rows = products(ctx)
            if rows:
                _table(doc, ["№", "Наименование продукции (товара)",
                             "Единица измерения", "Объём производства"],
                       [[str(i), r["name"] or "—", r["unit"] or "—",
                         _num(r["volume"])]
                        for i, r in enumerate(rows, start=1)])
            else:
                doc.add_paragraph(f"[требуется: {EXTERNAL['products']}]")

        elif key == "measures":
            rows = measures(ctx)
            if rows:
                _table(doc, ["№", "Наименование мероприятия", "Срок начала",
                             "Срок завершения", "Затраты, тыс. руб.",
                             "Результат"],
                       [[str(i), r["name"] or "—", r["start"] or "—",
                         r["end"] or "—", _num(r["cost"]), r["result"] or "—"]
                        for i, r in enumerate(rows, start=1)])
            else:
                doc.add_paragraph(f"[требуется: {EXTERNAL['measures']}]")

        elif key == "accidents":
            rows = accidents(ctx)
            doc.add_paragraph(
                "Сведения приводятся за семь лет, предшествующих подаче "
                "декларации (п. 3 ст. 31.2 ФЗ-7).")
            if rows is None:
                doc.add_paragraph(f"[требуется: {EXTERNAL['accidents']}]")
            elif not rows:
                doc.add_paragraph(
                    "Аварий и инцидентов, повлекших негативное воздействие "
                    "на окружающую среду, за предыдущие семь лет "
                    "не зафиксировано.")
            else:
                _table(doc, ["№", "Вид (авария/инцидент)", "Дата",
                             "Дата ликвидации последствий",
                             "Характеристика и причины",
                             "Негативное воздействие",
                             "Вред, тыс. руб.", "Меры по ликвидации"],
                       [[str(i), r["kind"], r["date"] or "—",
                         r["end_date"] or "—", r["description"] or "—",
                         r["impact"] or "—", _num(r["damage"]),
                         r["measures"] or "—"]
                        for i, r in enumerate(rows, start=1)])

        elif key == "air":
            rows = rows_air(ctx)
            if rows:
                doc.add_paragraph(
                    f"Декларируемая масса выбросов по {len(rows)} "
                    f"загрязняющим веществам, т/год:")
                _table(doc, ["№", "Загрязняющее вещество", "Код",
                             "Всего, т/год", "В пределах нормативов, т/год",
                             "Временно разрешённые / сверх нормативов, т/год"],
                       [[str(i), r["name"] or "—", r["code"] or "—",
                         _num(r["total"]), _num(r["norm"]), _num(r["over"])]
                        for i, r in enumerate(rows, start=1)])
                doc.add_paragraph(f"[требуется: {EXTERNAL['gs']}]")
            else:
                doc.add_paragraph(
                    "Выбросы загрязняющих веществ в атмосферный воздух "
                    "отсутствуют (данные не заведены).")
            doc.add_paragraph(f"[требуется: {EXTERNAL['ndv']}]")

        elif key == "water":
            rows = rows_water(ctx)
            bodies = water_bodies(ctx)
            if bodies:
                doc.add_paragraph("Приёмники сточных вод: "
                                  + "; ".join(bodies) + ".")
            if rows:
                _table(doc, ["№", "Загрязняющее вещество", "Код",
                             "Всего, т/год", "В пределах нормативов, т/год",
                             "Сверх нормативов, т/год"],
                       [[str(i), r["name"] or "—", r["code"] or "—",
                         _num(r["total"]), _num(r["norm"]), _num(r["over"])]
                        for i, r in enumerate(rows, start=1)])
            else:
                doc.add_paragraph(
                    "Сбросы загрязняющих веществ в водные объекты "
                    "отсутствуют (данные не заведены).")

        elif key == "waste":
            rows = rows_waste(ctx)
            if rows:
                total = sum(r["generated"] for r in rows)
                doc.add_paragraph(
                    f"Таблица 1. Образование и размещение отходов за "
                    f"отчётный год — {len(rows)} вид(ов), всего "
                    f"{_num(total)} т:")
                _table(doc, ["№", "Код по ФККО", "Наименование отхода",
                             "Класс опасности", "Образовано, т/год",
                             "Размещено на собственных объектах, т/год",
                             "Передано другим лицам, т/год"],
                       [[str(i), r["fkko"] or "—", r["name"] or "—",
                         str(r["hazard"] or "—"), _num(r["generated"]),
                         _num(r["placed"]), _num(r["transferred"])]
                        for i, r in enumerate(rows, start=1)])
                doc.add_paragraph(
                    "Таблица 2. Декларируемые масса и объём образования и "
                    "размещения отходов на период действия декларации "
                    f"({y1}–{y2} гг.) — приняты равными показателям "
                    "отчётного года (при неизменности технологических "
                    "процессов):")
                _table(doc, ["№", "Код по ФККО", "Наименование отхода",
                             "Класс опасности",
                             "Образование, т/год (ежегодно)",
                             "Размещение, т/год (ежегодно)"],
                       [[str(i), r["fkko"] or "—", r["name"] or "—",
                         str(r["hazard"] or "—"), _num(r["generated"]),
                         _num(r["placed"])]
                        for i, r in enumerate(rows, start=1)])
                if any(r["placed"] for r in rows):
                    doc.add_paragraph(f"[требуется: {EXTERNAL['groro']}]")
            else:
                doc.add_paragraph(
                    "Отходы производства и потребления: данные не заведены "
                    "(загрузите справки-акты или заполните вкладку ОТХОДЫ).")

        elif key == "pek":
            info = pek_info(ctx)
            if info["approved_date"]:
                doc.add_paragraph(
                    f"Программа производственного экологического контроля "
                    f"разработана в соответствии со ст. 67 ФЗ-7 и приказом "
                    f"Минприроды России от 18.02.2022 № 109, утверждена "
                    f"{info['approved_date']}."
                    + (f" Ответственный: {info['responsible']}."
                       if info["responsible"] else ""))
            else:
                doc.add_paragraph(f"[требуется: {EXTERNAL['pek']}]")
            if info["points"]:
                doc.add_paragraph("Точки и показатели контроля по программе:")
                _table(doc, ["Среда", "Точка контроля", "Показатели",
                             "Периодичность"],
                       [[str(p.get("medium", "")), str(p.get("point", "")),
                         str(p.get("indicators", "")),
                         str(p.get("frequency", ""))]
                        for p in info["points"]])
        doc.add_paragraph()

    sign = doc.add_paragraph()
    sign.add_run(f"{org.official_title or 'Руководитель'}\t\t"
                 f"_____________\t{org.director_name or ''}\t"
                 f"«___» __________ {y1} г.")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def _table(doc, header: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for i, text in enumerate(header):
        table.rows[0].cells[i].text = text
    for r in rows:
        cells = table.add_row().cells
        for i, text in enumerate(r):
            cells[i].text = text
    if not rows:
        cells = table.add_row().cells
        cells[0].text = "[требуется: данные не заведены]"
