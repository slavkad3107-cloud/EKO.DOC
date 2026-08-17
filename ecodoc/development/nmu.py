"""План мероприятий по снижению выбросов ЗВ в атмосферный воздух в периоды НМУ.

Действующая нормативная база (проверена на август 2026):
  * пп. 2 п. 12 ст. 19 Федерального закона от 04.05.1999 № 96-ФЗ «Об охране
    атмосферного воздуха» — обязанность разработки Плана мероприятий;
  * приказ Минприроды России от 28.11.2025 № 662 «Об утверждении требований
    к содержанию, составу, форме, порядку разработки, согласования
    и утверждения плана мероприятий по снижению выбросов загрязняющих веществ
    в атмосферный воздух в периоды неблагоприятных метеорологических условий»
    (Минюст 28.11.2025 № 84375; действует с 01.03.2026 до 01.03.2032).
    Состав документа взят ДОСЛОВНО из п. 3 требований (пп. «а»–«и»)
    и рекомендуемого образца-приложения: пп. 1–6 — сведения о лице и объекте
    ОНВОС и вид прогноза; п. 7 — перечень мероприятий (графы: № п/п, номер
    источника, наименование мероприятия, загрязняющее вещество, величины
    выбросов до и после мероприятия, г/с); п. 8 — результаты расчётов
    рассеивания (приказ МПР от 06.06.2017 № 273, п. 35 Методики № 581);
    п. 9 — метод контроля (п. 18 Порядка инвентаризации, приказ № 871);
  * приказ Минприроды России от 26.11.2025 № 651 (Минюст 28.11.2025 № 84372;
    01.03.2026–01.03.2032) — требования к самим мероприятиям: снижение при
    общем прогнозе НМУ — не менее 20 % (не менее 15 % для регулируемых видов
    деятельности — тепло-/электроэнергетика, ЖКХ); при специализированном
    прогнозе по степеням опасности НМУ: первая — ≥15 % (≥5 % рег.),
    вторая — ≥20 % (≥10 % рег.), третья — ≥40 % (≥20 % рег.);
  * приказ Минприроды России от 26.11.2025 № 652 — специализированные
    прогнозы НМУ (для объектов I категории, кроме регулируемых видов).

Приказ Минприроды России от 28.11.2019 № 811 УТРАТИЛ СИЛУ с 01.03.2026
(старые «режимы 1/2/3» с ориентирами 15–20/20–40/40–60 % — история);
ссылаться на него в новых планах нельзя.

Откуда данные (ничего не выдумываем):
  * пп. 1–5 формы — ctx.organization и ctx.objects (код, категория, адрес);
  * перечень мероприятий — ctx.extra['emission_sources'] (номер, наименование,
    вещества с г/с и т/год) + ctx.pollutants (medium=air, валовые т/год);
  * собственные мероприятия пользователя — ctx.extra['nmu']:
      forecast_kind:  «общий» | «специализированный» (п. 6 формы);
      regulated:      True для регулируемых видов деятельности (ТЭК/ЖКХ);
      measures:       [{mode: 1|2|3, text, reduction_pct, source, substance}]
                      (mode 1/2/3 = степень опасности НМУ; при общем прогнозе
                      применяются мероприятия mode 1);
      dispersion:     текст о выполненных расчётах рассеивания (п. 8 формы);
      control_method: «инструментальный» | «расчетный» (п. 9 формы);
      responsible:    должность, ФИО ответственного за проведение;
      no_measures_required: True — по п. 5 требований № 662 (превышений ПДК
                      в периоды НМУ по расчётам нет, мероприятия не нужны).
Если своих мероприятий нет — по каждому источнику подставляются типовые
формулировки (по виду источника) с целевым процентом степени, и это явно
помечается. Всё, что машина взять не может, помечено «[требуется: …]»,
и тот же список возвращает gaps(ctx).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import Medium, ReportContext

TITLE = ("План мероприятий по снижению выбросов загрязняющих веществ "
         "в атмосферный воздух в периоды неблагоприятных метеорологических "
         "условий")

NPA = ("приказ Минприроды России от 26.11.2025 № 651, приказ Минприроды "
       "России от 28.11.2025 № 662; пп. 2 п. 12 ст. 19 Федерального закона "
       "от 04.05.1999 № 96-ФЗ «Об охране атмосферного воздуха»")

# Степени опасности НМУ (специализированный прогноз, приказ № 652);
# ключ 0 — общий прогноз НМУ (без градации по степеням).
MODES = {
    0: "Мероприятия при поступлении общего прогноза НМУ",
    1: "Мероприятия при НМУ первой степени опасности",
    2: "Мероприятия при НМУ второй степени опасности",
    3: "Мероприятия при НМУ третьей степени опасности",
}

# Целевое снижение выбросов, % (приказ № 651): {mode: (прочие, регулируемые)}
TARGETS: dict[int, tuple[int, int]] = {
    0: (20, 15),
    1: (15, 5),
    2: (20, 10),
    3: (40, 20),
}

# типовые формулировки мероприятий по виду источника: (ключевые слова, тексты
# по степеням 1/2/3). Первая степень — организационно-технические без снижения
# производительности; вторая — с частичным снижением нагрузки; третья —
# частичная остановка производств, не имеющих непрерывного цикла.
_TYPICAL: list[tuple[tuple[str, ...], dict[int, str]]] = [
    (("котел", "котель", "печь", "тэц", "теплогенератор", "сушил"), {
        1: "усиление контроля топочного режима и герметичности газоходов, "
           "запрет продувки и чистки котлоагрегатов и газоходов",
        2: "перевод котлоагрегатов на резервное газообразное/малосернистое "
           "топливо, снижение нагрузки котлоагрегатов",
        3: "снижение нагрузки котлоагрегатов до технологического минимума, "
           "остановка резервных котлоагрегатов"}),
    (("сварк", "свароч", "резк", "металлообраб"), {
        1: "усиление контроля режимов сварки, работа только на исправном "
           "оборудовании с местной вытяжкой",
        2: "ограничение объёма сварочных и газорезательных работ",
        3: "запрет сварочных и газорезательных работ, кроме аварийных"}),
    (("окрас", "покрас", "лакокрас", "грунтов"), {
        1: "запрет окрасочных работ на открытых площадках",
        2: "ограничение окрасочных работ, перенос на период после отмены НМУ",
        3: "полное прекращение окрасочных работ"}),
    (("пыл", "дроб", "пересып", "сыпуч", "щебен", "цемент", "бетон",
      "грунт", "склад"), {
        1: "интенсификация орошения (гидрообеспыливания) мест пересыпки "
           "и открытых складов пылящих материалов",
        2: "ограничение погрузочно-разгрузочных работ с пылящими материалами",
        3: "прекращение погрузочно-разгрузочных работ с пылящими материалами"}),
    (("транспорт", "автотранспорт", "стоянк", "двигател", "техник",
      "дорог", "дэс", "дизель"), {
        1: "запрет работы двигателей автотранспорта и спецтехники "
           "на холостом ходу",
        2: "ограничение движения и работы автотранспорта и спецтехники "
           "на территории объекта",
        3: "остановка работы техники, не занятой в непрерывном цикле"}),
]

_TYPICAL_DEFAULT = {
    1: "усиление контроля за соблюдением технологического регламента "
       "и эффективностью газоочистного оборудования, запрет пусконаладочных "
       "работ и работ с залповыми выбросами",
    2: "снижение производительности источника с соответствующим уменьшением "
       "выброса загрязняющих веществ",
    3: "частичная остановка источника (производства, не имеющего "
       "непрерывного цикла), снижение нагрузки до технологического минимума",
}


# ── числа ────────────────────────────────────────────────────────────────────

def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except Exception:
        return None


def _fmt(value: Decimal | None) -> str:
    if value is None:
        return "—"
    if not value:
        return "0"
    text = f"{value.normalize():f}"
    return text


def _after(before: Decimal | None, pct: Decimal) -> Decimal | None:
    """Выброс после мероприятия: величина × (100 − %)/100."""
    if before is None:
        return None
    out = before * (Decimal(100) - pct) / Decimal(100)
    return out.quantize(Decimal("0.000001")).normalize()


# ── сбор данных ──────────────────────────────────────────────────────────────

def _cfg(ctx: ReportContext) -> dict:
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    cfg = extra.get("nmu")
    return cfg if isinstance(cfg, dict) else {}


def sources(ctx: ReportContext) -> list[dict]:
    """Источники выбросов — та же выборка, что в инвентаризации (№ 871)."""
    from ecodoc.development.air_inventory import sources as air_sources
    return air_sources(ctx)


def substances(ctx: ReportContext) -> list[dict]:
    """Сводный перечень веществ: {code, name, g_s, t_year}.

    Суммы г/с и т/год — по источникам из extra['emission_sources'];
    валовые т/год дополняются из ctx.pollutants (medium=air), если по
    источникам масса не набралась. Вещества, известные только из
    ctx.pollutants, тоже попадают в перечень (без г/с).
    """
    agg: dict[str, dict] = {}

    def slot(code: str, name: str) -> dict:
        key = code or name.lower()
        return agg.setdefault(key, {"code": code, "name": name,
                                    "g_s": None, "t_year": None})

    for s in sources(ctx):
        for p in s["pollutants"]:
            code = str(p.get("code") or "").strip()
            name = str(p.get("name") or "").strip()
            if not (code or name):
                continue
            r = slot(code, name)
            r["name"] = r["name"] or name
            for src_key, dst_key in (("g_s", "g_s"), ("t_year", "t_year")):
                d = _dec(p.get(src_key))
                if d is not None:
                    r[dst_key] = (r[dst_key] or Decimal(0)) + d

    for p in ctx.pollutants:
        if p.medium != Medium.AIR:
            continue
        total = ((_dec(p.mass_norm) or Decimal(0))
                 + (_dec(p.mass_limit) or Decimal(0))
                 + (_dec(p.mass_over) or Decimal(0)))
        r = slot(str(p.code or "").strip(), str(p.name or "").strip())
        r["name"] = r["name"] or p.name
        if r["t_year"] is None and total:
            r["t_year"] = total
    return list(agg.values())


def forecast_kind(ctx: ReportContext) -> str:
    """Вид прогноза НМУ (п. 6 формы): из extra['nmu'] или по категории.

    Объекты I категории (кроме регулируемых видов деятельности) обязаны
    получать специализированный прогноз (приказ № 652); II–III категории
    работают по общему прогнозу. Пустая строка — вид не определить.
    """
    kind = str(_cfg(ctx).get("forecast_kind") or "").strip().lower()
    if kind in ("общий", "специализированный"):
        return kind
    cats = {str(o.category or "").strip().upper() for o in ctx.objects}
    if "I" in cats and not _cfg(ctx).get("regulated"):
        return "специализированный"
    if cats & {"II", "III"}:
        return "общий"
    return ""


def plan_modes(ctx: ReportContext) -> list[int]:
    """Какие таблицы мероприятий входят в План: [0] — общий прогноз,
    [1, 2, 3] — специализированный (и по умолчанию, пока вид не указан:
    полный вариант, чтобы ничего не потерять)."""
    return [0] if forecast_kind(ctx) == "общий" else [1, 2, 3]


def target_pct(ctx: ReportContext, mode: int) -> int:
    """Целевое снижение по приказу № 651 для степени/вида прогноза, %."""
    other, regulated = TARGETS[mode]
    return regulated if _cfg(ctx).get("regulated") else other


def _typical_text(source_name: str, mode: int) -> str:
    low = (source_name or "").lower()
    step = 1 if mode == 0 else mode   # общий прогноз — орг.-тех. комплекс
    for keys, texts in _TYPICAL:
        if any(k in low for k in keys):
            return texts[step]
    return _TYPICAL_DEFAULT[step]


def user_measures(ctx: ReportContext, mode: int) -> list[dict]:
    """Мероприятия, заданные пользователем для степени (mode 0 → берём 1)."""
    step = 1 if mode == 0 else mode
    out = []
    for m in _cfg(ctx).get("measures", []) or []:
        if isinstance(m, dict) and int(m.get("mode", 0) or 0) == step:
            out.append(m)
    return out


def measure_rows(ctx: ReportContext, mode: int) -> tuple[list[list[str]], bool]:
    """Строки таблицы п. 7 (графы образца № 662) для одной степени.

    Возвращает (строки, типовые_ли): графы — № п/п, номер источника,
    мероприятие, вещество, выброс до г/с, выброс после г/с.
    """
    pct = Decimal(target_pct(ctx, mode))
    srcs = sources(ctx)
    by_number = {s["number"]: s for s in srcs if s["number"]}
    own = user_measures(ctx, mode)
    rows: list[list[str]] = []

    if own:
        n = 0
        for m in own:
            m_pct = _dec(m.get("reduction_pct")) or pct
            text = str(m.get("text") or "")
            src = by_number.get(str(m.get("source") or "").strip())
            polls = (src["pollutants"] if src else []) or []
            if src and polls:
                for p in polls:
                    n += 1
                    before = _dec(p.get("g_s"))
                    rows.append([str(n), src["number"], text,
                                 f"{p.get('code', '')} {p.get('name', '')}".strip() or "—",
                                 _fmt(before), _fmt(_after(before, m_pct))])
            else:
                n += 1
                total = None
                for s in substances(ctx):
                    if s["g_s"] is not None:
                        total = (total or Decimal(0)) + s["g_s"]
                rows.append([str(n),
                             str(m.get("source") or "") or "по объекту в целом",
                             text,
                             str(m.get("substance") or "") or
                             "все контролируемые вещества",
                             _fmt(total), _fmt(_after(total, m_pct))])
        return rows, False

    n = 0
    for s in srcs:
        polls = s["pollutants"] or [{}]
        for p in polls:
            n += 1
            before = _dec(p.get("g_s"))
            subst = f"{p.get('code', '')} {p.get('name', '')}".strip()
            rows.append([str(n), s["number"] or "—",
                         _typical_text(s["name"], mode),
                         subst or "[требуется: вещества источника]",
                         _fmt(before), _fmt(_after(before, pct))])
    return rows, True


def efficiency_rows(ctx: ReportContext) -> list[list[str]]:
    """Сводный расчёт снижения по веществам: масса × процент степени.

    Строка на вещество и степень: код, вещество, до (г/с и т/год),
    степень НМУ, снижение %, после (г/с и т/год).
    """
    rows = []
    modes = plan_modes(ctx)
    for s in sorted(substances(ctx), key=lambda r: (r["code"], r["name"])):
        for mode in modes:
            pct = Decimal(target_pct(ctx, mode))
            rows.append([
                s["code"] or "—", s["name"] or "—",
                _fmt(s["g_s"]), _fmt(s["t_year"]),
                "общий прогноз" if mode == 0 else f"{mode}-я степень",
                str(pct),
                _fmt(_after(s["g_s"], pct)), _fmt(_after(s["t_year"], pct))])
    return rows


# ── чего не хватает ─────────────────────────────────────────────────────────

def gaps(ctx: ReportContext) -> list[str]:
    """Список того, что машина взять не может, — он же печатается в Плане."""
    out: list[str] = []
    org = ctx.organization
    cfg = _cfg(ctx)
    if not (org.name or org.short_name):
        out.append("требуется: наименование юридического лица / ИП (п. 1 Плана)")
    if not ctx.objects:
        out.append("требуется: объект ОНВОС — наименование, адрес, категория, "
                   "код (пп. 2–5 Плана); заведите объект на вкладке ОБЪЕКТ")
    else:
        for o in ctx.objects:
            label = o.code or o.name or "объект"
            if not o.address:
                out.append(f"требуется: адрес (место нахождения) объекта {label} "
                           "(п. 3 Плана)")
            if not o.category:
                out.append(f"требуется: категория объекта {label} (п. 4 Плана)")
            if not o.code:
                out.append(f"требуется: код объекта ОНВОС «{o.name or '—'}» "
                           "(п. 5 Плана)")
    if not forecast_kind(ctx):
        out.append("требуется: вид прогноза НМУ — общий или специализированный "
                   "(п. 6 Плана; extra['nmu']['forecast_kind'])")
    if cfg.get("no_measures_required"):
        out.append("требуется: подтверждающие материалы об отсутствии "
                   "превышений ПДК в периоды НМУ (п. 5 требований № 662)")
        return out
    srcs = sources(ctx)
    if not srcs:
        out.append("требуется: источники выбросов — загрузите отчёт об "
                   "инвентаризации (приказ № 871), раздел ООС или проект НДВ "
                   "(вкладка ЗАГРУЗКА, категория «воздух»)")
    for s in srcs:
        if not s["number"]:
            out.append(f"требуется: номер источника «{s['name'] or '—'}» "
                       "(графа 2 перечня мероприятий)")
        if not s["pollutants"]:
            out.append(f"требуется: вещества и выбросы (г/с) источника "
                       f"№{s['number'] or '—'} (графы 4–6 перечня)")
        else:
            for p in s["pollutants"]:
                if _dec(p.get("g_s")) is None:
                    out.append("требуется: выброс г/с вещества "
                               f"«{p.get('name') or p.get('code') or '—'}» "
                               f"источника №{s['number'] or '—'} (графы 5–6)")
    for mode in plan_modes(ctx):
        if not user_measures(ctx, mode):
            out.append(f"требуется: проверка технологом типовых мероприятий — "
                       f"«{MODES[mode]}» (подставлены по виду источников)")
    if not cfg.get("dispersion"):
        out.append("требуется: результаты расчётов рассеивания (приказ МПР "
                   "от 06.06.2017 № 273, п. 35 Методики № 581), "
                   "обосновывающие эффективность мероприятий (п. 8 Плана)")
    if str(cfg.get("control_method") or "").strip().lower() not in (
            "инструментальный", "расчетный", "расчётный"):
        out.append("требуется: метод контроля — инструментальный или расчётный, "
                   "по п. 18 Порядка инвентаризации № 871 (п. 9 Плана)")
    if not (cfg.get("responsible") or org.director_name):
        out.append("требуется: ответственный за проведение мероприятий "
                   "(должность, ФИО)")
    return out


# ── документ ────────────────────────────────────────────────────────────────

def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    """Собрать План мероприятий НМУ (.docx) по форме приказа № 662."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.shared import Cm, Pt

    org = ctx.organization
    cfg = _cfg(ctx)
    kind = forecast_kind(ctx)
    modes = plan_modes(ctx)
    problems = gaps(ctx)

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    for s in doc.sections:
        s.left_margin, s.right_margin = Cm(3), Cm(1.5)
        s.top_margin, s.bottom_margin = Cm(2), Cm(2)

    # грифы по рекомендуемому образцу № 662: слева «Утверждено», справа
    # «Согласовано» (уполномоченный орган субъекта РФ, п. 6 требований)
    grif = doc.add_table(rows=1, cols=2)
    grif.rows[0].cells[0].text = ("УТВЕРЖДЕНО\n"
                                  f"{org.official_title or 'Руководитель'}\n"
                                  f"____________ {org.director_name or '[ФИО]'}\n"
                                  "«___» __________ 20__ г.\nМесто для печати")
    grif.rows[0].cells[1].text = ("СОГЛАСОВАНО\n[требуется: уполномоченный "
                                  "орган субъекта РФ — региональный "
                                  "экологический надзор]\n«___» ______ 20__ г.\n"
                                  "Место для печати")

    doc.add_paragraph()
    h = doc.add_paragraph()
    h.alignment = AL.CENTER
    run = h.add_run(TITLE)
    run.bold = True
    run.font.size = Pt(14)
    base = doc.add_paragraph()
    base.alignment = AL.CENTER
    base.add_run(f"Разработан в соответствии с: {NPA}.").italic = True

    # ── пп. 1–6 формы ────────────────────────────────────────────────────
    obj = ctx.objects[0] if ctx.objects else None
    doc.add_paragraph(
        "1. Наименование юридического лица или фамилия, имя, отчество "
        "индивидуального предпринимателя: "
        f"{org.name or org.short_name or '[требуется: наименование]'}"
        + (f", ИНН {org.inn}" if org.inn else "")
        + (f", ОГРН {org.ogrn}" if org.ogrn else "") + ".")
    doc.add_paragraph(
        "2. Наименование объекта, оказывающего негативное воздействие "
        f"на окружающую среду: {obj.name if obj and obj.name else '[требуется]'}.")
    doc.add_paragraph(
        "3. Сведения о фактическом месте нахождения объекта: "
        f"{obj.address if obj and obj.address else '[требуется: адрес]'}.")
    doc.add_paragraph(
        "4. Категория объекта: "
        f"{obj.category if obj and obj.category else '[требуется]'}.")
    doc.add_paragraph(
        "5. Код объекта: "
        f"{obj.code if obj and obj.code else '[требуется: код ОНВОС]'}.")
    doc.add_paragraph(
        "6. Вид получаемого прогноза НМУ: "
        f"{kind or '[требуется: общий или специализированный]'}."
        + (" Специализированный прогноз предоставляется по договору "
           "(приказ Минприроды России от 26.11.2025 № 652)."
           if kind == "специализированный" else ""))

    # ── п. 7: перечень мероприятий ──────────────────────────────────────
    doc.add_paragraph()
    doc.add_paragraph().add_run(
        "7. Перечень мероприятий по снижению выбросов в периоды НМУ").bold = True
    if cfg.get("no_measures_required"):
        doc.add_paragraph(
            "По результатам инвентаризации стационарных источников и выбросов "
            "и расчётов рассеивания в выбросах объекта ОНВОС отсутствуют "
            "загрязняющие вещества, концентрация которых в периоды НМУ будет "
            "превышать предельно допустимые концентрации. Разработка "
            "мероприятий по снижению выбросов в периоды НМУ не требуется "
            "(п. 5 требований, утв. приказом № 662). "
            "[требуется: подтверждающие материалы об отсутствии превышений "
            "ПДК в периоды НМУ (п. 5 требований № 662)]")
    else:
        header = ["№ п/п", "Номер источника выбросов",
                  "Наименование мероприятия по уменьшению выбросов "
                  "загрязняющих веществ в атмосферный воздух в периоды НМУ",
                  "Наименование загрязняющего вещества",
                  "Величины выбросов до мероприятия, г/с",
                  "Величины выбросов после мероприятия, г/с"]
        for mode in modes:
            sub = doc.add_paragraph()
            sub.add_run(f"{MODES[mode]} "
                        f"(целевое снижение выбросов — не менее "
                        f"{target_pct(ctx, mode)} %, приказ № 651)").bold = True
            rows, typical = measure_rows(ctx, mode)
            _table(doc, header, rows)
            if typical and rows:
                doc.add_paragraph(
                    "Мероприятия подставлены по виду источников — "
                    f"[требуется: проверка технологом типовых мероприятий — "
                    f"«{MODES[mode]}» (подставлены по виду источников)]")

    # ── п. 8: расчёты рассеивания ───────────────────────────────────────
    doc.add_paragraph()
    doc.add_paragraph().add_run(
        "8. Результаты расчётов рассеивания выбросов").bold = True
    doc.add_paragraph(
        "Эффективность мероприятий обосновывается расчётами рассеивания, "
        "выполненными в соответствии с методами расчётов рассеивания "
        "выбросов вредных (загрязняющих) веществ в атмосферном воздухе "
        "(приказ Минприроды России от 06.06.2017 № 273) с учётом п. 35 "
        "Методики разработки (расчёта) и установления нормативов допустимых "
        "выбросов (приказ Минприроды России от 11.08.2020 № 581), "
        "с приложением документарного подтверждения расчётов.")
    if cfg.get("dispersion"):
        doc.add_paragraph(str(cfg["dispersion"]))
    else:
        doc.add_paragraph(
            "[требуется: результаты расчётов рассеивания (приказ МПР "
            "от 06.06.2017 № 273, п. 35 Методики № 581), обосновывающие "
            "эффективность мероприятий (п. 8 Плана)]")

    # ── п. 9: метод контроля ────────────────────────────────────────────
    doc.add_paragraph()
    doc.add_paragraph().add_run("9. Информация о методе контроля").bold = True
    method = str(cfg.get("control_method") or "").strip()
    doc.add_paragraph(
        "Метод контроля (инструментальный или расчётный) определён при "
        "проведении инвентаризации стационарных источников и выбросов "
        "в соответствии с п. 18 Порядка проведения инвентаризации "
        "(приказ Минприроды России от 19.11.2021 № 871): "
        + (method if method else
           "[требуется: метод контроля — инструментальный или расчётный, "
           "по п. 18 Порядка инвентаризации № 871 (п. 9 Плана)]") + ".")

    # ── 10: сводный расчёт снижения ─────────────────────────────────────
    if not cfg.get("no_measures_required"):
        doc.add_paragraph()
        doc.add_paragraph().add_run(
            "10. Сводный расчёт снижения выбросов по веществам").bold = True
        doc.add_paragraph(
            "Расчётное снижение принято по целевым показателям приказа "
            "№ 651 (величина выброса × процент снижения); фактическая "
            "достаточность подтверждается расчётами рассеивания (п. 8).")
        _table(doc, ["Код", "Загрязняющее вещество", "До, г/с", "До, т/год",
                     "Прогноз / степень НМУ", "Снижение, %",
                     "После, г/с", "После, т/год"],
               efficiency_rows(ctx))

    # ── 11: организация работ ───────────────────────────────────────────
    doc.add_paragraph()
    doc.add_paragraph().add_run(
        "11. Организация работ в периоды НМУ").bold = True
    resp = cfg.get("responsible") or (
        f"{org.official_title or 'Руководитель'} {org.director_name}".strip()
        if org.director_name else "")
    doc.add_paragraph(
        "Ответственный за проведение мероприятий: "
        + (resp or "[требуется: ответственный за проведение мероприятий "
                   "(должность, ФИО)]") + ".")
    doc.add_paragraph(
        "Мероприятия вводятся с момента поступления прогноза НМУ и "
        "проводятся в течение всего периода его действия. В периоды НМУ "
        "не допускаются: остановка газоочистного оборудования на "
        "профилактику, залповые выбросы, продувка и чистка оборудования и "
        "газоходов, пусконаладочные работы и испытания оборудования "
        "с изменением технологического режима (приказ № 651).")
    doc.add_paragraph(
        "Поступление прогнозов и проведение мероприятий фиксируются "
        "в журнале учёта:")
    _table(doc, ["Дата, время получения прогноза",
                 "Вид прогноза / степень опасности НМУ",
                 "Период действия НМУ",
                 "Проведённые мероприятия (№ по Плану)",
                 "Начало / окончание работ", "Подпись ответственного"],
           [["", "", "", "", "", ""]])

    # ── чего не хватает (тот же список, что gaps) ───────────────────────
    if problems:
        doc.add_paragraph()
        doc.add_paragraph().add_run(
            "Чего не хватает (проверьте перед согласованием — "
            "п. 6 требований № 662: план согласовывает уполномоченный "
            "орган субъекта РФ в течение 15 рабочих дней)").bold = True
        for text in problems:
            doc.add_paragraph(f"— [{text}]")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
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
        cells[0].text = ("[требуется: данные не заведены — источники и "
                         "вещества]")
