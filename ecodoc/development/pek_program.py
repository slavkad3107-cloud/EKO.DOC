"""Программа производственного экологического контроля (ПЭК).

Кто обязан: юридические лица и ИП, эксплуатирующие объекты I–III категорий,
разрабатывают и утверждают программу ПЭК (п. 2 ст. 67 Федерального закона
от 10.01.2002 № 7-ФЗ «Об охране окружающей среды»). Для IV категории
программа не требуется.

Состав программы задаёт НПА, а не привычка: приказ Минприроды России от
18.02.2022 № 109 «Об утверждении требований к содержанию программы
производственного экологического контроля, порядка и сроков представления
отчёта об организации и о результатах осуществления производственного
экологического контроля» (зарег. Минюстом 25.02.2022 № 67461, действует
с 01.09.2022 до 01.09.2028). Действующая редакция — с изменениями,
внесёнными приказами Минприроды России от 24.03.2023 № 150 (побочные
продукты производства), от 13.11.2024 № 659, от 07.05.2025 № 255 и от
12.05.2025 № 262 (искусственные грунты из органической части ТКО;
изменения действуют с 01.09.2025).

Разделы программы — дословно по п. 2 Требований (приложение 1 к приказу),
см. SECTIONS. Раздел 9 состоит из подразделов по средам (п. 9–9.5).

Откуда берутся данные (ничего не выдумывается):
  * организация и объекты НВОС      — ctx.organization / ctx.objects;
  * источники выбросов              — ctx.extra['emission_sources']
                                      (те же, что в инвентаризации № 871);
  * вещества (воздух и вода)        — ctx.pollutants (medium=air/water);
  * отходы                          — ctx.wastes / ctx.waste_acts
                                      (через waste_inventory.collect);
  * забор воды и выпуски            — ctx.extra['water'] (intake/discharge);
  * лаборатории, ответственные,
    маркерные вещества, даты        — ctx.extra['pek']:
        lab / labs, responsible, unit, program_date, markers,
        air_frequency, air_inventory_date, water_permit, surface_water,
        oro, points (совместимость со старым вводом);
  * побочные продукты, искусственные
    грунты                          — ctx.extra['ppp'] / ['artificial_soil'].

Периодичности, прямо установленные Требованиями (значения по умолчанию):
  * сточные воды (п. 9.2.2): объекты I и II категорий — не менее 1 раза
    в месяц, по показателю токсичности — не менее 1 раза в квартал;
    объекты III категории — не менее 1 раза в квартал;
  * проверки работы очистных сооружений (п. 9.2.4) — не реже 2 раз в год;
  * периодичность контроля ВЫБРОСОВ приказом № 109 не фиксируется —
    её определяет владелец объекта в плане-графике (п. 9.1.1); по
    умолчанию ставим «1 раз в год» и честно говорим об этом в gaps().

Чего машина не делает: не считает рассеивание (какие источники дают
< 0,1 ПДКмр на границе участка и могут не включаться в план-график,
п. 9.1.2), не выбирает створы наблюдений за водным объектом (п. 9.2.3),
не назначает маркерные вещества. Там, где нужны эти данные, в документе
остаётся пометка «[требуется: …]», и та же строка попадает в gaps().
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date
from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import Medium, ReportContext

TITLE = "Программа производственного экологического контроля"

NPA = ("приказ Минприроды России от 18.02.2022 № 109 (в редакции приказов "
       "от 24.03.2023 № 150, от 13.11.2024 № 659, от 07.05.2025 № 255, "
       "от 12.05.2025 № 262)")

# Разделы программы — дословно по п. 2 Требований (приложение 1 к № 109).
SECTIONS: list[tuple[str, str]] = [
    ("general", "Общие положения"),
    ("air_inv", "Сведения об инвентаризации выбросов загрязняющих веществ "
                "в атмосферный воздух и их источников"),
    ("water_inv", "Сведения об инвентаризации сбросов загрязняющих веществ "
                  "в окружающую среду и их источников"),
    ("waste_inv", "Сведения об инвентаризации отходов производства и "
                  "потребления и объектов их размещения"),
    ("ppp", "Сведения о побочных продуктах производства"),
    ("soil", "Сведения о произведённых из органической части твёрдых "
             "коммунальных отходов искусственных грунтах"),
    ("staff", "Сведения о подразделениях и (или) должностных лицах, "
              "отвечающих за осуществление производственного "
              "экологического контроля"),
    ("lab", "Сведения о собственных и (или) привлекаемых испытательных "
            "лабораториях (центрах), аккредитованных в соответствии с "
            "законодательством Российской Федерации об аккредитации в "
            "национальной системе аккредитации"),
    ("plan", "Сведения о периодичности и методах осуществления "
             "производственного экологического контроля, местах отбора "
             "проб и методиках (методах) измерений"),
]

DEFAULT_AIR_FREQ = "1 раз в год"          # НПА не фиксирует — типовая практика
FREQ_WATER_I_II = "не менее 1 раза в месяц"        # п. 9.2.2
FREQ_WATER_III = "не менее 1 раза в квартал"       # п. 9.2.2
FREQ_TOXICITY = "не менее 1 раза в квартал"        # п. 9.2.2
FREQ_TREATMENT = "не реже 2 раз в год"             # п. 9.2.4


# ────────────────────────────────────────────────────────────────────────
# доступ к данным
# ────────────────────────────────────────────────────────────────────────
def _pek(ctx: ReportContext) -> dict:
    pek = (ctx.extra or {}).get("pek", {}) if isinstance(ctx.extra, dict) else {}
    return pek if isinstance(pek, dict) else {}


def _water_extra(ctx: ReportContext) -> dict:
    w = (ctx.extra or {}).get("water", {}) if isinstance(ctx.extra, dict) else {}
    return w if isinstance(w, dict) else {}


def worst_category(ctx: ReportContext) -> str:
    """Самая строгая категория среди объектов — по ней дефолтные периодичности."""
    from ecodoc.calendar.engine import category_of
    cats = {category_of(o) for o in ctx.objects}
    for c in ("I", "II", "III", "IV"):
        if c in cats:
            return c
    return ""


def air_pollutants(ctx: ReportContext) -> list:
    return [p for p in ctx.pollutants if p.medium == Medium.AIR]


def water_pollutants(ctx: ReportContext) -> list:
    return [p for p in ctx.pollutants if p.medium == Medium.WATER]


def _legacy_points(ctx: ReportContext, medium: str) -> list[dict]:
    """Старый ручной ввод точек контроля (extra.pek.points) — не теряем его.

    medium — подстрока для поля medium точки: «возд», «вод», «отход».
    """
    out = []
    for p in _pek(ctx).get("points", []) or []:
        if isinstance(p, dict) and medium in str(p.get("medium", "")).lower():
            out.append(p)
    return out


# ────────────────────────────────────────────────────────────────────────
# план-графики (то, что становится таблицами)
# ────────────────────────────────────────────────────────────────────────
def plan_air(ctx: ReportContext) -> list[dict]:
    """План-график контроля стационарных источников выбросов (п. 9.1.1).

    Графы по НПА: подразделение/источник, загрязняющее вещество (в т.ч.
    маркерное), метод контроля (инструментальный/расчётный), периодичность,
    место отбора проб, методика измерений. Источник данных — инвентаризация
    (extra.emission_sources); если источников нет, а вещества есть — строки
    по веществам с пометкой, что нужен номер источника.
    """
    from ecodoc.development.air_inventory import sources
    pek = _pek(ctx)
    markers = {str(m).strip().lower() for m in pek.get("markers", []) or []}
    freq = str(pek.get("air_frequency") or "") or DEFAULT_AIR_FREQ

    def marker(code: str, name: str) -> str:
        return "да" if (code.lower() in markers or name.lower() in markers) else "—"

    rows: list[dict] = []
    srcs = sources(ctx)
    for s in srcs:
        label = " ".join(x for x in (s["number"], s["name"]) if x).strip()
        # неорганизованный источник — классический случай расчётного метода
        # (п. 9.1.3: нет практической возможности инструментальных измерений)
        method = ("расчётный" if "неорг" in s["kind"].lower()
                  else "инструментальный")
        subs = s["pollutants"] or [{}]
        for p in subs:
            code, name = str(p.get("code") or ""), str(p.get("name") or "")
            rows.append({
                "source": label or "[требуется: номер источника выбросов]",
                "code": code or "—",
                "name": name or "[требуется: вещества источника]",
                "marker": marker(code, name),
                "method": method,
                "frequency": freq,
                "place": "устье источника" if method == "инструментальный"
                         else "по данным инвентаризации",
            })
    if not srcs:
        for p in air_pollutants(ctx):
            rows.append({
                "source": "[требуется: номер источника выбросов]",
                "code": p.code or "—", "name": p.name or "—",
                "marker": marker(p.code or "", p.name or ""),
                "method": "инструментальный", "frequency": freq,
                "place": "устье источника",
            })
    for p in _legacy_points(ctx, "возд"):
        rows.append({"source": str(p.get("point", "")), "code": "—",
                     "name": str(p.get("indicators", "")), "marker": "—",
                     "method": str(p.get("method", "инструментальный")),
                     "frequency": str(p.get("frequency", freq)),
                     "place": str(p.get("point", ""))})
    return rows


def plan_water(ctx: ReportContext) -> list[dict]:
    """План-график контроля сточных вод (п. 9.2.1–9.2.2).

    Периодичность по умолчанию — из НПА по категории объекта; показатель
    токсичности добавляется отдельной строкой (п. 9.2.2).
    """
    pek = _pek(ctx)
    cat = worst_category(ctx)
    if pek.get("water_frequency"):
        freq = str(pek["water_frequency"])
    elif cat in ("I", "II"):
        freq = FREQ_WATER_I_II
    elif cat == "III":
        freq = FREQ_WATER_III
    else:
        freq = "[требуется: категория объекта — от неё зависит периодичность]"

    outlets = [str(d.get("receiver") or "") for d in
               _water_extra(ctx).get("discharge", []) or [] if isinstance(d, dict)]
    outlet = "; ".join(x for x in outlets if x) or \
        "[требуется: выпуск / место отбора проб сточных вод]"

    rows = [{"outlet": outlet, "code": p.code or "—", "name": p.name or "—",
             "frequency": freq}
            for p in water_pollutants(ctx)]
    if rows:
        rows.append({"outlet": outlet, "code": "—",
                     "name": "Токсичность (биотестирование)",
                     "frequency": FREQ_TOXICITY})
    for p in _legacy_points(ctx, "вод"):
        rows.append({"outlet": str(p.get("point", "")), "code": "—",
                     "name": str(p.get("indicators", "")),
                     "frequency": str(p.get("frequency", freq))})
    return rows


def rows_waste(ctx: ReportContext) -> list[dict]:
    """Перечень отходов — общий с инвентаризацией отходов (один источник правды)."""
    from ecodoc.development.waste_inventory import collect
    return collect(ctx)


# ────────────────────────────────────────────────────────────────────────
# пробелы в данных
# ────────────────────────────────────────────────────────────────────────
def _gap_map(ctx: ReportContext) -> "OrderedDict[str, list[str]]":
    """Пробелы по разделам. gaps() — это же списком; generate() печатает
    каждую строку в своём разделе как «[…]», поэтому текст и список всегда
    совпадают (никакого второго источника правды)."""
    m: "OrderedDict[str, list[str]]" = OrderedDict(
        (k, []) for k, _ in SECTIONS)
    org, pek = ctx.organization, _pek(ctx)
    have_air = bool(air_pollutants(ctx)) or bool(
        (ctx.extra or {}).get("emission_sources"))
    have_water = bool(water_pollutants(ctx)) or bool(
        _water_extra(ctx).get("discharge"))
    have_waste = bool(ctx.wastes or ctx.waste_acts)

    if not (org.name or org.short_name):
        m["general"].append("требуется: наименование организации (п. 3 Требований)")
    if not org.inn:
        m["general"].append("требуется: ИНН организации (п. 3 Требований)")
    if not ctx.objects:
        m["general"].append("требуется: объект НВОС — код, категория и адрес "
                            "по свидетельству о постановке на учёт")
    else:
        for o in ctx.objects:
            if not worst_category(ctx):
                m["general"].append(
                    f"требуется: категория объекта {o.code or o.name} "
                    "(программа ПЭК — для I–III категорий)")
                break
    if worst_category(ctx) == "IV":
        m["general"].append("объект IV категории — программа ПЭК для него "
                            "не разрабатывается (ст. 67 ФЗ-7)")
    if not (pek.get("program_date") or pek.get("approved_date")):
        m["general"].append("требуется: дата утверждения Программы "
                            "(п. 3 Требований)")
    if not (have_air or have_water or have_waste):
        m["general"].append("нет ни выбросов, ни сбросов, ни отходов — "
                            "программу нечем наполнять: загрузите исходные "
                            "данные")

    if have_air:
        if not pek.get("air_inventory_date"):
            m["air_inv"].append("требуется: дата и реквизиты инвентаризации "
                                "выбросов и её последней корректировки "
                                "(п. 4 Требований)")
        if not (ctx.extra or {}).get("emission_sources"):
            m["air_inv"].append("требуется: перечень стационарных источников "
                                "выбросов — загрузите инвентаризацию по "
                                "приказу № 871 или проект НДВ")
        if not pek.get("markers"):
            m["plan"].append("требуется: перечень маркерных веществ для "
                             "плана-графика контроля выбросов (п. 9.1.1)")
        if not pek.get("air_frequency"):
            m["plan"].append("периодичность контроля выбросов принята типовой "
                             f"({DEFAULT_AIR_FREQ}) — НПА её не фиксирует; "
                             "уточните в плане-графике при утверждении")
        m["plan"].append("требуется: результаты расчёта рассеивания — источники "
                         "с вкладом менее 0,1 ПДКмр на границе участка можно "
                         "не включать в план-график (п. 9.1.2)")

    if have_water:
        if not pek.get("water_permit"):
            m["water_inv"].append("требуется: реквизиты договора водопользования "
                                  "или решения о предоставлении водного объекта "
                                  "в пользование (п. 5 Требований)")
        if not pek.get("surface_water"):
            m["plan"].append("требуется: программа наблюдений за водным объектом "
                             "и его водоохранной зоной — фоновый и контрольный "
                             "створы (п. 9.2.3)")

    if have_waste:
        if not pek.get("oro"):
            m["waste_inv"].append("требуется: сведения об эксплуатируемых "
                                  "объектах размещения отходов по ГРОРО либо "
                                  "подтверждение их отсутствия (п. 6 Требований)")

    if not (pek.get("responsible") or pek.get("unit") or org.director_name):
        m["staff"].append("требуется: подразделение и (или) должностное лицо, "
                          "отвечающее за ПЭК (п. 7 Требований)")
    if not (pek.get("lab") or pek.get("labs")):
        m["lab"].append("требуется: наименование, адрес и реквизиты аттестата "
                        "аккредитации испытательной лаборатории "
                        "(п. 8 Требований)")
    return m


def gaps(ctx: ReportContext) -> list[str]:
    """Чего не хватает для программы — тот же список, что и пометки в тексте."""
    return [g for lst in _gap_map(ctx).values() for g in lst]


# ────────────────────────────────────────────────────────────────────────
# документ
# ────────────────────────────────────────────────────────────────────────
def _num(value) -> str:
    if value in (None, "", 0):
        return "—"
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return str(value)
    return f"{d.normalize():f}" if d else "—"


def _table(doc, header: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for i, text in enumerate(header):
        table.rows[0].cells[i].text = text
    for r in rows:
        cells = table.add_row().cells
        for i, text in enumerate(r):
            cells[i].text = str(text)
    if not rows:
        table.add_row().cells[0].text = "[требуется: данные не заведены]"


def _marks(doc, items: list[str]) -> None:
    """Пометки раздела: та же строка, что в gaps(), в квадратных скобках."""
    for g in items:
        p = doc.add_paragraph()
        p.add_run(f"[{g}]").italic = True


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    """Собрать программу ПЭК (.docx) по составу приказа № 109."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.shared import Cm, Pt

    org, pek = ctx.organization, _pek(ctx)
    gap = _gap_map(ctx)
    year = ctx.period.year or date.today().year
    have_air = bool(air_pollutants(ctx)) or bool(
        (ctx.extra or {}).get("emission_sources"))
    have_water = bool(water_pollutants(ctx)) or bool(
        _water_extra(ctx).get("discharge"))

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    for s in doc.sections:
        s.left_margin, s.right_margin = Cm(3), Cm(1.5)
        s.top_margin, s.bottom_margin = Cm(2), Cm(2)

    # ── титул: гриф утверждения обязателен — дату требует п. 3 ───────────
    ap = doc.add_paragraph()
    ap.alignment = AL.RIGHT
    ap.add_run("УТВЕРЖДАЮ\n"
               f"{org.official_title or 'Руководитель'}\n"
               f"_____________ {org.director_name or '[Ф.И.О.]'}\n"
               f"«___» __________ {year} г.")
    doc.add_paragraph()
    t = doc.add_paragraph()
    t.alignment = AL.CENTER
    run = t.add_run(TITLE.upper())
    run.bold = True
    run.font.size = Pt(14)
    sub = doc.add_paragraph()
    sub.alignment = AL.CENTER
    sub.add_run(org.name or org.short_name or "[требуется: наименование "
                "организации (п. 3 Требований)]")
    basis = doc.add_paragraph()
    basis.alignment = AL.CENTER
    basis.add_run(
        "Разработана в соответствии со ст. 67 Федерального закона от "
        f"10.01.2002 № 7-ФЗ и требованиями к содержанию программы "
        f"производственного экологического контроля, утверждёнными "
        f"приказом Минприроды России от 18.02.2022 № 109 (в редакции "
        f"приказов от 24.03.2023 № 150, от 13.11.2024 № 659, "
        f"от 07.05.2025 № 255, от 12.05.2025 № 262)").italic = True
    doc.add_page_break()

    # ── содержание ───────────────────────────────────────────────────────
    doc.add_paragraph().add_run("СОДЕРЖАНИЕ").bold = True
    for i, (_, title) in enumerate(SECTIONS, start=1):
        doc.add_paragraph(f"{i}. {title}")
    doc.add_page_break()

    for i, (key, title) in enumerate(SECTIONS, start=1):
        head = doc.add_paragraph()
        head.add_run(f"{i}. {title}").bold = True

        if key == "general":
            doc.add_paragraph(
                f"Организация: {org.name or '[требуется]'}"
                + (f" ({org.short_name})" if org.short_name else "")
                + f", ИНН {org.inn or '[требуется]'}, "
                  f"ОГРН {org.ogrn or '—'}, адрес: {org.address or '—'}.")
            for o in ctx.objects:
                doc.add_paragraph(
                    f"Объект НВОС: {o.name or '—'}, код "
                    f"{o.code or '[требуется: код объекта]'}, категория "
                    f"{o.category or '[требуется]'}, адрес: {o.address or '—'} "
                    "(по свидетельству о постановке на государственный учёт).")
            doc.add_paragraph(
                "Отчёт об организации и о результатах осуществления ПЭК "
                "представляется ежегодно до 25 марта года, следующего за "
                "отчётным, в уполномоченный орган (Росприроднадзор либо "
                "орган субъекта РФ — по уровню надзора объекта).")
            resp = pek.get("responsible") or org.director_name
            if resp:
                doc.add_paragraph(f"Ответственный за подготовку отчёта: {resp}.")
            d = pek.get("program_date") or pek.get("approved_date")
            if d:
                doc.add_paragraph(f"Дата утверждения Программы: {d}.")

        elif key == "air_inv":
            subs = air_pollutants(ctx)
            if not have_air:
                doc.add_paragraph(
                    "Стационарные источники выбросов на объекте отсутствуют / "
                    "данные о выбросах не заведены — раздел не заполняется.")
            else:
                if pek.get("air_inventory_date"):
                    doc.add_paragraph("Инвентаризация выбросов проведена: "
                                     f"{pek['air_inventory_date']}.")
                doc.add_paragraph(
                    f"Суммарные выбросы по данным инвентаризации — "
                    f"{len(subs)} загрязняющих веществ:")
                _table(doc,
                       ["№", "Код", "Загрязняющее вещество", "Выброс, т/год"],
                       [[str(n), p.code or "—", p.name or "—",
                         _num(p.mass_norm + p.mass_limit + p.mass_over)]
                        for n, p in enumerate(subs, start=1)])

        elif key == "water_inv":
            subs = water_pollutants(ctx)
            w = _water_extra(ctx)
            if not have_water:
                doc.add_paragraph(
                    "Сбросы загрязняющих веществ в окружающую среду "
                    "отсутствуют / данные не заведены — раздел не заполняется.")
            else:
                if pek.get("water_permit"):
                    doc.add_paragraph("Право пользования водным объектом: "
                                     f"{pek['water_permit']}.")
                outs = [d for d in w.get("discharge", []) or []
                        if isinstance(d, dict)]
                if outs:
                    _table(doc, ["№", "Выпуск (приёмник)",
                                 "Объём водоотведения, тыс. м³/год"],
                           [[str(n), d.get("receiver") or "—",
                             _num(d.get("volume"))]
                            for n, d in enumerate(outs, start=1)])
                doc.add_paragraph("Суммарный сброс по веществам:")
                _table(doc, ["№", "Код", "Загрязняющее вещество", "Сброс, т/год"],
                       [[str(n), p.code or "—", p.name or "—",
                         _num(p.mass_norm + p.mass_limit + p.mass_over)]
                        for n, p in enumerate(subs, start=1)])

        elif key == "waste_inv":
            rows = rows_waste(ctx)
            if not rows:
                doc.add_paragraph("Отходы производства и потребления не "
                                  "заведены — раздел не заполняется.")
            else:
                doc.add_paragraph(
                    f"Отходы, образующиеся в процессе деятельности (по ФККО) — "
                    f"{len(rows)} вид(ов):")
                _table(doc, ["№", "Наименование отхода", "Код ФККО",
                             "Класс опасности", "Образование, т/год"],
                       [[str(n), r["name"] or "—", r["fkko"] or "—",
                         str(r["hazard"] or "—"), _num(r["generated"])]
                        for n, r in enumerate(rows, start=1)])
            if pek.get("oro"):
                _table(doc, ["№", "Объект размещения отходов", "№ в ГРОРО"],
                       [[str(n), str(o.get("name", "—")), str(o.get("groro", "—"))]
                        for n, o in enumerate(pek["oro"], start=1)
                        if isinstance(o, dict)])

        elif key == "ppp":
            ppp = [p for p in ((ctx.extra or {}).get("ppp") or [])
                   if isinstance(p, dict)]
            if ppp:
                _table(doc, ["№", "Побочный продукт производства",
                             "Образование, т/год"],
                       [[str(n), p.get("name") or "—", _num(p.get("formed"))]
                        for n, p in enumerate(ppp, start=1)])
            else:
                doc.add_paragraph("Побочные продукты производства не "
                                  "образуются (сведений в базе нет).")

        elif key == "soil":
            soil = [s for s in ((ctx.extra or {}).get("artificial_soil") or [])
                    if isinstance(s, dict)]
            if soil:
                _table(doc, ["№", "Искусственный грунт", "Производство, т/год"],
                       [[str(n), s.get("name") or "—", _num(s.get("formed"))]
                        for n, s in enumerate(soil, start=1)])
            else:
                doc.add_paragraph("Искусственные грунты из органической части "
                                  "ТКО не производятся (сведений в базе нет).")

        elif key == "staff":
            unit = pek.get("unit") or ""
            resp = pek.get("responsible") or org.director_name or ""
            if unit or resp:
                _table(doc, ["Подразделение", "Должностное лицо", "Полномочия"],
                       [[unit or "—", resp or "—",
                         pek.get("duties") or "организация и осуществление "
                         "ПЭК, подготовка отчёта о результатах ПЭК"]])
            # пробел печатается ниже из gap-карты

        elif key == "lab":
            labs = pek.get("labs") or (
                [{"name": pek["lab"]}] if pek.get("lab") else [])
            _table(doc, ["№", "Лаборатория (центр)", "Адрес",
                         "Аттестат аккредитации"],
                   [[str(n), l.get("name") or "—", l.get("address") or "—",
                     l.get("certificate") or "[требуется: аттестат]"]
                    for n, l in enumerate(labs, start=1) if isinstance(l, dict)])

        elif key == "plan":
            # 9.1 воздух
            p91 = doc.add_paragraph()
            p91.add_run(f"{i}.1. Производственный контроль в области охраны "
                        "атмосферного воздуха").bold = True
            if have_air:
                doc.add_paragraph(
                    "План-график контроля стационарных источников выбросов "
                    "(п. 9.1.1 Требований). В план-график не включаются "
                    "источники, выброс от которых по результатам рассеивания "
                    "не превышает 0,1 ПДКмр на границе земельного участка "
                    "(п. 9.1.2); расчётные методы применяются при отсутствии "
                    "аттестованных методик или практической возможности "
                    "инструментальных измерений (п. 9.1.3).")
                _table(doc, ["Источник выбросов", "Код", "Загрязняющее вещество",
                             "Маркерное", "Метод контроля", "Периодичность",
                             "Место отбора проб"],
                       [[r["source"], r["code"], r["name"], r["marker"],
                         r["method"], r["frequency"], r["place"]]
                        for r in plan_air(ctx)])
                mon = [x for x in (pek.get("air_monitoring") or [])
                       if isinstance(x, dict)]
                if mon:
                    doc.add_paragraph("План-график наблюдений за загрязнением "
                                      "атмосферного воздуха:")
                    _table(doc, ["Точка", "Вещество", "Периодичность"],
                           [[x.get("point_no") or x.get("address") or "—",
                             x.get("substance") or "—", x.get("period") or "—"]
                            for x in mon])
                else:
                    doc.add_paragraph(
                        "Наблюдения за загрязнением атмосферного воздуха "
                        "проводятся, если объект включён в перечень, "
                        "предусмотренный п. 3 ст. 23 Федерального закона "
                        "от 04.05.1999 № 96-ФЗ (сведений о включении нет).")
            else:
                doc.add_paragraph("Выбросы отсутствуют — контроль в области "
                                  "охраны атмосферного воздуха не ведётся.")

            # 9.2 вода
            p92 = doc.add_paragraph()
            p92.add_run(f"{i}.2. Производственный контроль в области охраны "
                        "и использования водных объектов").bold = True
            if have_water:
                doc.add_paragraph(
                    "План-график контроля состава и свойств сточных вод. "
                    "Периодичность по п. 9.2.2 Требований: объекты I и II "
                    f"категорий — {FREQ_WATER_I_II}, объекты III категории — "
                    f"{FREQ_WATER_III}; по показателю токсичности — "
                    f"{FREQ_TOXICITY}.")
                _table(doc, ["Выпуск / место отбора проб", "Код",
                             "Показатель", "Периодичность"],
                       [[r["outlet"], r["code"], r["name"], r["frequency"]]
                        for r in plan_water(ctx)])
                doc.add_paragraph(
                    "Проверки работы очистных сооружений проводятся с "
                    f"периодичностью {FREQ_TREATMENT} (п. 9.2.4 Требований).")
                sw = [x for x in (pek.get("surface_water") or [])
                      if isinstance(x, dict)]
                if sw:
                    doc.add_paragraph("Программа наблюдений за водным объектом "
                                      "(фоновый и контрольный створы):")
                    _table(doc, ["Водный объект", "Створ / место",
                                 "Показатель", "Периодичность"],
                           [[x.get("water_body") or "—", x.get("location") or "—",
                             x.get("substance") or "—", x.get("period") or "—"]
                            for x in sw])
            else:
                doc.add_paragraph("Сбросы отсутствуют — контроль в области "
                                  "охраны водных объектов не ведётся.")

            # 9.3 отходы
            p93 = doc.add_paragraph()
            p93.add_run(f"{i}.3. Производственный контроль в области "
                        "обращения с отходами").bold = True
            if ctx.wastes or ctx.waste_acts:
                doc.add_paragraph(
                    "Учёт отходов ведётся по приказу Минприроды России от "
                    "08.12.2020 № 1028; данные учёта обобщаются по итогам "
                    "квартала и календарного года (п. 9.3 Требований). "
                    "Контроль мест накопления — визуальный, при каждом "
                    "обращении с отходами; предельный срок накопления — "
                    "11 месяцев.")
                if pek.get("oro"):
                    doc.add_paragraph(
                        "Мониторинг состояния и загрязнения окружающей среды "
                        "на объектах размещения отходов осуществляется по "
                        "программе, утверждённой в соответствии с приказом "
                        "Минприроды России от 08.12.2020 № 1030.")
                else:
                    doc.add_paragraph(
                        "Собственные объекты размещения отходов не "
                        "эксплуатируются — программа мониторинга ОРО "
                        "(приказ № 1030) не разрабатывается.")
                pts = _legacy_points(ctx, "отход")
                if pts:
                    _table(doc, ["Место контроля", "Показатели", "Периодичность"],
                           [[str(p.get("point", "")), str(p.get("indicators", "")),
                             str(p.get("frequency", ""))] for p in pts])
            else:
                doc.add_paragraph("Отходы не заведены — контроль в области "
                                  "обращения с отходами не описывается.")

            # 9.4–9.5 ППП и искусственные грунты
            p94 = doc.add_paragraph()
            p94.add_run(f"{i}.4. Производственный контроль в области обращения "
                        "с побочными продуктами производства").bold = True
            doc.add_paragraph(
                "Порядок учёта побочных продуктов производства"
                + (": ведётся по перечню раздела 5."
                   if (ctx.extra or {}).get("ppp")
                   else " не устанавливается — побочные продукты не образуются."))
            p95 = doc.add_paragraph()
            p95.add_run(f"{i}.5. Производственный контроль в области обращения "
                        "с искусственными грунтами").bold = True
            doc.add_paragraph(
                "Контроль производства искусственных грунтов из органической "
                "части ТКО"
                + (": ведётся по перечню раздела 6."
                   if (ctx.extra or {}).get("artificial_soil")
                   else " не осуществляется — грунты не производятся."))

        _marks(doc, gap.get(key, []))
        doc.add_paragraph()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out
