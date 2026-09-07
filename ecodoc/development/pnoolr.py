"""ПНООЛР — проект нормативов образования отходов и лимитов на размещение.

Структура текстовой части (.docx) — по Методическим указаниям, утв. приказом
Минприроды России от 07.12.2020 № 1021 (действует с 01.01.2021 по 01.01.2027;
приказ в Формы/Разработка/ПНООЛР), и сверена с двумя принятыми проектами
из архива пользователя (ООО «ВСМ-Сервис», ООО «ЭК «СФЕРА», 2024; ООО «ЭП
«Меркурий», 2021 — Формы/Разработка/ПНООЛР/ИСТОЧНИК.txt):

  титульный лист (прил. 1) → содержание →
  1. Общие сведения о ЮЛ/ИП →
  2. Сведения о хозяйственной и иной деятельности (прил. 2: сырьё →
     операция → продукция → отход → обращение) →
  3. Сведения об образуемых отходах (прил. 3: код, класс, происхождение,
     агрегатное состояние, состав) →
  4. Расчёт и обоснование нормативов образования отходов (раздел II
     указаний: методы — по материально-сырьевому балансу, по удельным
     отраслевым нормативам, расчётно-аналитический, экспериментальный,
     по фактическим объёмам образования; прил. 4). Типовые формулы —
     из ecodoc/development/oos_waste_calc.py (те же, что в разделе ООС:
     ТКО по нормам накопления, материалы × норматив потерь, лампы N·T/K,
     огарки электродов, осадок мойки колёс, выгребные ямы, избыток грунта) →
  5. Расчёт максимального образования отходов за год (Го = Но · П) и
     сведения о предлагаемом образовании (прил. 5) →
  6. Сведения о местах накопления отходов (прил. 6) →
  7. Сведения о планируемом обращении: обработка/утилизация/
     обезвреживание самим ХС (прил. 7), передача другим ХС (прил. 8),
     приём от других (прил. 9), размещение на собственных ОРО (прил. 10,
     11), передача для размещения (прил. 12) →
  8. Сводные данные по образованию отходов и запрашиваемым лимитам
     (прил. 13) → список источников → приложения.

Расчётная часть (.xlsx) остаётся приложением: нормативы и лимиты по
отходам считаются из типовых формул (исходные данные ООС: extra.oos),
проектных нормативов ООС/ПНООЛР (extra.oos_wastes) и фактических данных
(акты за годы). Плейсхолдеров в документе нет: где данных нет — нейтральная
формулировка, а конкретика «чего не хватает и откуда взять» — в gaps().
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import ReportContext
from ecodoc.render import xlsx

TITLE = "Проект нормативов образования отходов и лимитов на их размещение"
NA = "—"

# разделы ПНООЛР, для которых у программы обычно нет данных (в тексте —
# типовая формулировка, в gaps — что дописать)
_NARRATIVE = [
    "Сведения о хозяйственной и иной деятельности (описание процессов)",
    "Характеристика мест накопления отходов (карта-схема, вместимость)",
    "Мероприятия по снижению количества образующихся отходов",
]

# методы определения нормативов — раздел II приказа № 1021
METHODS = {
    "fact": "метод расчёта по фактическим объёмам образования отходов "
            "(среднее за период наблюдений)",
    "project": "расчётно-аналитический метод (по проектной документации — "
               "раздел ООС / ранее утверждённый ПНООЛР)",
    "unit": "метод расчёта по удельным отраслевым нормативам образования отходов",
    "balance": "метод расчёта по материально-сырьевому балансу",
    "exp": "экспериментальный метод",
}


def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return None
    return float(d) if d else None


def _f(v) -> str:
    from ecodoc.development.waste_inventory import fmt_num
    return fmt_num(v)


# ──────────────────────────────────────────────────────────────────────────
# расчёт по типовым формулам — переиспользуем oos_waste_calc через
# сборщики раздела ООС (исходные данные — extra.oos.construction/operation)
# ──────────────────────────────────────────────────────────────────────────
def calc_rows(ctx: ReportContext) -> dict[str, dict]:
    """fkko → {t, m3, stage, name, lines:[строки расчёта с формулой]}.

    Берём только те отходы, для которых есть исходные данные и формула
    (oos_waste_calc); всё, что ООС добавляет в сводку «как есть» из базы,
    здесь не считается расчётом."""
    from ecodoc.core.waste_agg import norm_fkko
    try:
        from ecodoc.development import oos
        cw = oos.construction_wastes(ctx)
        ow = oos.operation_wastes(ctx)
    except Exception:
        return {}
    out: dict[str, dict] = {}

    def add(fkko, name, stage, t, m3, line):
        code = norm_fkko(fkko)
        if not code or not t:
            return
        r = out.setdefault(code, {"t": 0.0, "m3": 0.0, "stage": stage, "name": name,
                                  "lines": []})
        r["t"] += float(t)
        r["m3"] += float(m3 or 0)
        r["lines"].append(line)

    for r in cw.get("tko") or []:
        add("73310001724", "Мусор от офисных и бытовых помещений организаций "
            "несортированный (исключая крупногабаритный)", "строительство", r["t"], r["m3"],
            f"{r['label']}: М = {r['people']} чел. × {_f(r['norm'])} м³/год × "
            f"{r['months']}/12 мес = {_f(r['m3'])} м³; × ρ = {_f(r['density'])} т/м³ "
            f"= {_f(r['t'])} т")
    c = cw.get("cesspool")
    if c:
        add("73210001304", "Отходы (осадки) из выгребных ям", "строительство", c["t"], c["m3"],
            f"М = {c['people']} чел. × {c['shifts']} смен × {_f(c['norm'])} л/(чел.·смену) "
            f"/ 1000 = {_f(c['m3'])} м³; × ρ = {_f(c['density'])} т/м³ = {_f(c['t'])} т")
    for r in cw.get("wheel") or []:
        add("72310101394", "Осадок (шлам) механической очистки нефтесодержащих сточных "
            "вод, содержащий нефтепродукты в количестве менее 15 %, обводненный",
            "строительство", r["t"], r["m3"],
            f"{r['label']}: Q = (C₁ − C₂) · q · 10⁻⁶ · P / (1 − B/100) = "
            f"({_f(r['c1'])} − {_f(r['c2'])}) × {_f(r['q'])} м³/сут × 10⁻⁶ × {r['days']} сут "
            f"/ (1 − {_f(r['humidity'])}/100) = {_f(r['t'])} т")
    for r in cw.get("materials") or []:
        if r.get("note") or not r.get("fkko"):
            continue
        if r["unit"] == "т":
            line = (f"{r['material']}: М = {_f(r['qty'])} т × {_f(r['pct'])} % / 100 = "
                    f"{_f(r['t'])} т ({_f(r['m3'])} м³ при ρ = {_f(r['density'])} т/м³)")
        else:
            line = (f"{r['material']}: V = {_f(r['qty'])} {r['unit']} × {_f(r['pct'])} % / 100 "
                    f"= {_f(r['m3'])} м³; М = V × ρ = {_f(r['m3'])} × {_f(r['density'])} "
                    f"= {_f(r['t'])} т")
        add(r["fkko"], r["waste_name"], "строительство", r["t"], r["m3"], line)
    e = cw.get("electrodes")
    if e:
        add("91910001205", "Остатки и огарки стальных сварочных электродов", "строительство",
            e["t"], e["m3"], f"М = {_f(e['total'])} т электродов × {_f(e['pct'])} % / 100 = "
                             f"{_f(e['t'])} т ({_f(e['m3'])} м³ при ρ = {_f(e['density'])} т/м³)")
    s = cw.get("soil")
    if s:
        add("81110001495", "Грунт, образовавшийся при проведении землеройных работ, не "
            "загрязненный опасными веществами", "строительство", s["t"], s["m3"],
            f"М = V × ρ = {_f(s['m3'])} м³ × {_f(s['density'])} т/м³ = {_f(s['t'])} т")
    for r in ow.get("norm") or []:
        if r.get("note") or not r.get("fkko"):
            continue
        add(r["fkko"], r["name"], "эксплуатация", r["t"], r["m3"],
            f"М = {_f(r['count'])} {r['count_unit'] or 'ед.'} × {_f(r['norm'])} "
            f"{r['norm_unit']}/год"
            + (f" × ρ = {_f(r['density'])} т/м³" if r["norm_unit"] == "м3" else "")
            + f" = {_f(r['t'])} т ({_f(r['m3'])} м³)")
    for r in ow.get("lamps") or []:
        if not r.get("t"):
            continue
        add("48241100525", "Лампы накаливания, утратившие потребительские свойства",
            "эксплуатация", r["t"], r["m3"],
            f"{r['name']}: N = {_f(r['count'])} шт. × {_f(r['hours'])} ч/год / "
            f"{_f(r['life_h'])} ч = {_f(r['replaced'])} шт.; × {_f(r['mass_kg'])} кг / 1000 "
            f"= {_f(r['t'])} т")
    return out


def rows(ctx: ReportContext) -> list[dict]:
    """Расчётная таблица: норматив образования и лимит размещения по отходам.

    Норматив (norm): по типовой формуле (calc_rows, метод «unit»), иначе
    проектный из ООС/ПНООЛР (norm_t, «project»), иначе среднее по годам
    актов (fact_years, «fact»), иначе образовано по движению (generated).
    Лимит (limit): размещено на собственных объектах (placed_*), иначе None.
    """
    from ecodoc.core.waste_agg import norm_fkko
    from ecodoc.development.waste_inventory import collect

    calc = calc_rows(ctx)
    out = []
    for r in collect(ctx):
        placed = 0.0
        for w in ctx.wastes:
            if norm_fkko(w.fkko_code) == r["fkko"]:
                placed += (_num(w.placed_norm) or 0.0) + (_num(w.placed_over) or 0.0)
        years = {y: m for y, m in r["fact_years"].items() if m}
        c = calc.get(r["fkko"])
        if c:
            norm, method = c["t"], "unit"
        elif r["norm_t"] is not None:
            norm, method = r["norm_t"], "project"
        elif years:
            norm, method = sum(years.values()) / len(years), "fact"
        elif r["generated"]:
            norm, method = r["generated"], "fact"
        else:
            norm, method = None, ""
        transferred_place = sum(
            _num(w.transferred_burial) or 0.0 for w in ctx.wastes
            if norm_fkko(w.fkko_code) == r["fkko"]) + sum(
            _num(w.transferred_storage) or 0.0 for w in ctx.wastes
            if norm_fkko(w.fkko_code) == r["fkko"])
        out.append({**r, "norm": norm, "method": method, "limit": placed or None,
                    "years": years, "calc": c,
                    "transferred_place": transferred_place or None})
    return out


def gaps(ctx: ReportContext, data: list[dict] | None = None) -> list[str]:
    from ecodoc.development.waste_inventory import gaps as inv_gaps, main_object
    data = data if data is not None else rows(ctx)
    out = list(inv_gaps(ctx))
    o = main_object(ctx)
    cat = (o.category if o else "") or ""
    if cat in ("III", "IV"):
        out.insert(0, f"объект {cat} категории — ПНООЛР по ст. 18 ФЗ-89 не требуется "
                      "(нормативы и лимиты устанавливаются для I–II категорий); "
                      "документ формируется как расчётно-справочный")
    if not ctx.period.year:
        out.append("не указан отчётный год — норматив считается за конкретный период")
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    if not any(r["method"] == "unit" for r in data):
        out.append("нет исходных данных для расчёта по типовым формулам "
                   "(вкладка РАЗРАБОТКА → ООС: численность, материалы, лампы, "
                   "нормативы накопления) — раздел 4 обоснован проектными "
                   "нормативами и фактом по актам")
    for r in data:
        if not r["norm"]:
            out.append(f"{r['name'] or r['fkko']}: нет ни проектного норматива, ни "
                       f"фактического образования — норматив не на чем обосновать "
                       f"(загрузите ООС/ПНООЛР или справки-акты)")
        elif r["method"] == "fact" and len(r["years"]) < 3:
            out.append(f"{r['name'] or r['fkko']}: факт только за "
                       f"{len(r['years']) or 1} год(а) — для статистического "
                       f"метода нужны данные за 3 года или расчёт по удельным "
                       f"показателям")
    if not extra.get("waste_storage"):
        out.append("не описаны места накопления отходов (extra.waste_storage: "
                   "номер на карте-схеме, наименование, вместимость) — раздел 6 "
                   "заполнен по одному месту на отход без вместимости")
    if not extra.get("waste_contracts"):
        out.append("нет реквизитов договоров на передачу отходов "
                   "(extra.waste_contracts: получатель, № и дата, срок) — в "
                   "разделе 7 графы договора пустые")
    if not extra.get("own_oro"):
        out.append("не указано, есть ли собственные объекты размещения отходов "
                   "(extra.own_oro: № ГРОРО) — принято «собственных ОРО нет»")
    out += [f"раздел «{name}» пишется экологом по исходным данным предприятия "
            f"(в документе — типовая формулировка)" for name in _NARRATIVE]
    return out


# ──────────────────────────────────────────────────────────────────────────
# .docx
# ──────────────────────────────────────────────────────────────────────────
def _contract(ctx: ReportContext, receiver: str) -> dict:
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    for c in extra.get("waste_contracts") or []:
        if isinstance(c, dict) and receiver and \
                str(c.get("receiver", "")).lower()[:20] == receiver.lower()[:20]:
            return c
    return {}


def _receiver_lines(ctx: ReportContext, r: dict) -> tuple[str, str, str]:
    """Получатель (с ИНН/лицензией), реквизиты договора, срок действия."""
    from ecodoc.core.waste_agg import norm_fkko
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    recv_info = [x for x in (extra.get("waste_receivers") or [])
                 if isinstance(x, dict) and norm_fkko(x.get("fkko")) == r["fkko"]]
    parts = []
    for name in r["receivers"]:
        info = next((x for x in recv_info if x.get("receiver") == name), {})
        line = name
        if info.get("inn"):
            line += f", ИНН {info['inn']}"
        lic = info.get("license") or next(iter(r["licenses"]), "")
        if lic:
            line += f", лицензия {lic}"
        parts.append(line)
    receiver = "; ".join(parts) or "специализированная организация по договору"
    c = _contract(ctx, r["receivers"][0]) if r["receivers"] else {}
    return receiver, c.get("contract") or NA, c.get("term") or NA


def _sec_title(doc, ctx: ReportContext) -> None:
    from ecodoc.development.waste_inventory import (docx_approval, docx_para,
                                                     main_object, site_address)
    org = ctx.organization
    o = main_object(ctx)
    docx_approval(doc, ctx)
    for _ in range(5):
        doc.add_paragraph()
    docx_para(doc, "ПРОЕКТ", bold=True, align="center", size=16)
    docx_para(doc, "НОРМАТИВОВ ОБРАЗОВАНИЯ ОТХОДОВ", bold=True, align="center", size=16)
    docx_para(doc, "И ЛИМИТОВ НА ИХ РАЗМЕЩЕНИЕ", bold=True, align="center", size=16)
    docx_para(doc, "(ПНООЛР)", bold=True, align="center", size=14)
    doc.add_paragraph()
    docx_para(doc, org.name or org.short_name or "", bold=True, align="center", size=13)
    if org.short_name and org.name and org.short_name != org.name:
        docx_para(doc, f"({org.short_name})", align="center")
    docx_para(doc, f"Объект: {(o.name if o else '') or 'НВОС'}"
                   + (f" — код {o.code}" if o else "")
                   + (f", {o.category} категория" if o and o.category else ""),
              align="center")
    if site_address(ctx):
        docx_para(doc, f"Адрес: {site_address(ctx)}", align="center")
    for _ in range(8):
        doc.add_paragraph()
    docx_para(doc, f"{_dt.date.today().year} г.", align="center")
    doc.add_page_break()


_TOC = [
    "Введение",
    "1. Общие сведения о юридическом лице (индивидуальном предпринимателе)",
    "2. Сведения о хозяйственной и иной деятельности, в результате которой "
    "образуются отходы",
    "3. Сведения об образуемых отходах",
    "4. Расчёт и обоснование нормативов образования отходов",
    "5. Расчёт максимального образования отходов за год. Сведения о предлагаемом "
    "образовании отходов",
    "6. Сведения о местах (площадках) накопления отходов",
    "7. Сведения о планируемом обращении с отходами",
    "8. Сводные данные по образованию отходов и запрашиваемым лимитам на их "
    "размещение",
    "Список использованных источников",
    "Приложения",
]


def _sec_intro(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import docx_heading, docx_para, main_object
    org = ctx.organization
    o = main_object(ctx)
    docx_heading(doc, "Введение", 1)
    docx_para(doc, (
        f"Проект нормативов образования отходов и лимитов на их размещение "
        f"разработан для {org.name or org.short_name or 'хозяйствующего субъекта'} "
        f"по объекту {(o.name if o else '') or 'НВОС'}"
        f"{(' (код ' + o.code + ')') if o else ''} в "
        f"соответствии со ст. 18 Федерального закона от 24.06.1998 № 89-ФЗ «Об "
        f"отходах производства и потребления» и Методическими указаниями по "
        f"разработке проектов нормативов образования отходов и лимитов на их "
        f"размещение, утверждёнными приказом Минприроды России от 07.12.2020 "
        f"№ 1021 (зарег. Минюстом 25.12.2020 № 61835)."), align="justify")
    docx_para(doc, (
        "Нормативы образования отходов установлены на основании расчётов по "
        "типовым формулам (удельные показатели образования), проектной "
        "документации и фактических данных учёта отходов (справки-акты, журнал "
        "учёта по приказу № 1028); лимиты на размещение — по объёмам отходов, "
        f"размещаемых на объектах размещения. Всего в проекте {len(data)} видов "
        f"отходов."), align="justify")


def _sec_1(doc, ctx: ReportContext) -> None:
    from ecodoc.development.waste_inventory import (_org_rows, docx_heading,
                                                     docx_para, docx_table)
    docx_heading(doc, _TOC[1], 1)
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    rows_ = _org_rows(ctx) + [
        ["Сведения о собственных объектах размещения отходов (ГРОРО)",
         extra.get("own_oro") or "самостоятельно эксплуатируемые (собственные) "
                                 "объекты размещения отходов отсутствуют"],
        ["Ответственный за охрану окружающей среды",
         extra.get("waste_responsible") or NA],
    ]
    docx_table(doc, ["Показатель", "Сведения"], rows_, widths_cm=[7, 10], font_size=11)
    deps = [d for d in (extra.get("departments") or []) if isinstance(d, dict)]
    if deps:
        docx_para(doc, "Перечень подразделений (участков):", bold=True)
        for d in deps:
            docx_para(doc, f"• {d.get('name', '')}"
                           + (f" — {d['process']}" if d.get("process") else ""))
    else:
        docx_para(doc, "Перечень подразделений (участков), режим работы, "
                       "численность персонала и площадь территории принимаются "
                       "по исходным данным предприятия (приложение 1).",
                  align="justify")


def _sec_2(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import (_handling, _origin_text,
                                                     docx_heading, docx_para,
                                                     docx_table)
    docx_heading(doc, _TOC[2], 1)
    org = ctx.organization
    docx_para(doc, (
        f"Основной вид деятельности: {org.okved or 'не указан'} (ОКВЭД). Описание "
        f"технологических процессов, используемого сырья и материалов, "
        f"выпускаемой продукции (услуг) приводится по исходным данным "
        f"предприятия; блок-схема производственных процессов — приложение."),
        align="justify")
    docx_para(doc, "Сведения о хозяйственной и иной деятельности (по образцу "
                   "приложения 2 к приказу № 1021):", bold=True)
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    deps = [d for d in (extra.get("departments") or []) if isinstance(d, dict)]
    table = []
    if deps:
        for d in deps:
            codes = {str(c).replace(" ", "") for c in (d.get("wastes") or [])}
            names = [r["name"] for r in data if r["fkko"] in codes] or [NA]
            table.append([d.get("materials") or NA, d.get("process") or d.get("name"),
                          d.get("product") or NA, "; ".join(names),
                          d.get("handling") or "накопление, передача лицензированной "
                                               "организации"])
    else:
        for r in data:
            table.append([NA, _origin_text(r), NA, r["name"] or r["fkko"], _handling(r)])
    docx_table(doc, ["Используемое сырьё, материалы, полуфабрикаты",
                     "Производственные операции (без детализации)",
                     "Производимая продукция (услуги, работы)",
                     "Образующиеся отходы", "Операции по обращению с отходами"],
               table, widths_cm=[3.5, 4, 3, 4.5, 4], font_size=9)


def _sec_3(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import (_fmt_code, _origin_text,
                                                     _roman, docx_heading,
                                                     docx_para, docx_table)
    docx_heading(doc, _TOC[3], 1)
    docx_para(doc, "В результате осуществления деятельности образуются следующие "
                   "виды отходов (по образцу приложения 3 к приказу № 1021):",
              align="justify")
    table = []
    for i, r in enumerate(data, start=1):
        table.append([str(i), r["name"] or NA, _fmt_code(r["fkko"]),
                      _roman(r["hazard"]), _origin_text(r), r["agg"] or NA,
                      r["composition"] or NA])
    docx_table(doc, ["№ п/п", "Наименование вида отходов", "Код по ФККО",
                     "Класс опасности", "Происхождение или условия образования",
                     "Агрегатное состояние и физическая форма", "Состав, %"],
               table, widths_cm=[0.9, 4.5, 2.4, 1.3, 3.2, 2.7, 3.5], font_size=8)
    docx_para(doc, "Класс опасности отходов подтверждён паспортами (I–IV классы, "
                   "приказ Минприроды России № 286 от 15.05.2026; ранее — № 1026) "
                   "и протоколами биотестирования (V класс). Копии — в приложении.",
              align="justify")


def _sec_4(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import (_fmt_code, _roman, docx_heading,
                                                     docx_para, docx_table, fmt_num)
    docx_heading(doc, _TOC[4], 1)
    docx_para(doc, (
        "Нормативы образования отходов определены в соответствии с разделом II "
        "Методических указаний (приказ № 1021) одним из методов: по "
        "материально-сырьевому балансу; по удельным отраслевым нормативам "
        "образования отходов; расчётно-аналитическим методом; экспериментальным "
        "методом; по фактическим объёмам образования отходов (статистическим "
        "методом). Норматив образования в среднем за год (ПНо) для отходов, "
        "образующихся при износе изделий с ограниченным сроком эксплуатации, "
        "допускается определять по формуле ПНо = Mi / T, где Mi — масса "
        "изделий, признанных отходами, т; T — срок эксплуатации, лет."),
        align="justify")
    docx_para(doc, (
        "Расчёт по удельным показателям: М = N · Hу · ρ, где N — количество "
        "единиц (персонал, площадь, материалы, изделия), Hу — удельный норматив "
        "образования (норма накопления, норматив потерь материала), ρ — "
        "плотность отхода, т/м³. Статистический метод: Но = Σ(Mi) / n, где Mi — "
        "фактическое образование отхода за i-й год по данным учёта, т; n — "
        "число лет наблюдений (не менее трёх)."), align="justify")
    docx_para(doc, "Сводная таблица методов (по образцу приложения 4 к приказу "
                   "№ 1021):", bold=True)
    docx_table(doc, ["№", "Наименование вида отходов", "Код по ФККО", "Класс",
                     "Метод определения норматива", "Норматив, т/год"],
               [[str(i), r["name"] or NA, _fmt_code(r["fkko"]), _roman(r["hazard"]),
                 METHODS.get(r["method"], "не определён — нет данных"),
                 fmt_num(r["norm"]) if r["norm"] else NA]
                for i, r in enumerate(data, start=1)],
               widths_cm=[0.8, 5, 2.4, 1.2, 5.6, 2], font_size=8)
    for i, r in enumerate(data, start=1):
        docx_heading(doc, f"4.{i}. {r['name'] or 'Отход'} ({_fmt_code(r['fkko'])}, "
                          f"{_roman(r['hazard']) or 'класс не определён'})", 2)
        if r["method"] == "unit" and r.get("calc"):
            c = r["calc"]
            docx_para(doc, f"Применён {METHODS['unit']} (стадия: {c['stage']}). "
                           f"Исходные данные и расчёт:", align="justify")
            for line in c["lines"]:
                docx_para(doc, "• " + line, size=11)
            if len(c["lines"]) > 1:
                docx_para(doc, f"Итого: {fmt_num(c['t'])} т"
                               + (f" ({fmt_num(c['m3'])} м³)" if c["m3"] else "") + ".")
            if r["norm_t"] is not None:
                docx_para(doc, f"Справочно — норматив по проектной документации "
                               f"(ООС/ПНООЛР): {fmt_num(r['norm_t'])} т/год.")
            if r["years"]:
                docx_para(doc, "Справочно — фактическое образование по данным учёта: "
                          + "; ".join(f"{y} г. — {fmt_num(m)} т"
                                      for y, m in sorted(r["years"].items())) + ".")
        elif r["method"] == "project":
            docx_para(doc, (
                f"Норматив образования принят по проектной документации "
                f"(раздел ООС / ПНООЛР) — {METHODS['project']}: "
                f"{fmt_num(r['norm'])} т/год."), align="justify")
            if r["years"]:
                docx_para(doc, "Справочно — фактическое образование по данным учёта: "
                          + "; ".join(f"{y} г. — {fmt_num(m)} т"
                                      for y, m in sorted(r["years"].items())) + ".")
        elif r["method"] == "fact" and r["years"]:
            docx_para(doc, f"Применён {METHODS['fact']}. Исходные данные — "
                           f"справки-акты за годы наблюдений:", align="justify")
            docx_table(doc, ["Год", "Фактическое образование, т"],
                       [[str(y), fmt_num(m)] for y, m in sorted(r["years"].items())],
                       widths_cm=[3, 5], font_size=10)
            docx_para(doc, f"Но = ({' + '.join(fmt_num(m) for _, m in sorted(r['years'].items()))}) "
                           f"/ {len(r['years'])} = {fmt_num(r['norm'])} т/год."
                           + (" Период наблюдений менее трёх лет: норматив "
                              "подлежит подтверждению расчётом по удельным "
                              "показателям при накоплении данных учёта."
                              if len(r["years"]) < 3 else ""), align="justify")
        elif r["method"] == "fact":
            docx_para(doc, (
                f"Норматив принят по фактическому образованию за отчётный период "
                f"(данные учёта движения отходов): {fmt_num(r['norm'])} т/год; "
                f"подтверждается расчётом по удельным показателям при "
                f"представлении исходных данных предприятия."), align="justify")
        else:
            docx_para(doc, "Норматив образования по данному отходу не определён: "
                           "отсутствуют проектное значение и данные учёта. Требуется "
                           "расчёт по удельным показателям по исходным данным "
                           "предприятия.", align="justify")
        docx_para(doc, f"Предлагаемый норматив образования отхода — "
                       f"{fmt_num(r['norm']) if r['norm'] else 'не определён'} т/год.",
                  bold=True)


def _sec_5(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import (_fmt_code, _origin_text, _roman,
                                                     docx_heading, docx_para,
                                                     docx_table, fmt_num)
    docx_heading(doc, _TOC[5], 1)
    docx_para(doc, (
        "Годовое образование отходов (Го) определяется по нормативу образования "
        "(Но) и плановым показателям производства продукции, выполнения работ, "
        "оказания услуг (П): Го = Но · П. При нормативе, установленном в тоннах "
        "в год, максимальное годовое образование принимается равным нормативу."),
        align="justify")
    docx_para(doc, "Предлагаемое ежегодное образование отходов (по образцу "
                   "приложения 5 к приказу № 1021):", bold=True)
    table = []
    for i, r in enumerate(data, start=1):
        n = fmt_num(r["norm"]) if r["norm"] else NA
        table.append([str(i), r["name"] or NA, _fmt_code(r["fkko"]),
                      _roman(r["hazard"]), _origin_text(r), "т/год", n, n])
    docx_table(doc, ["№ п/п", "Наименование вида отходов", "Код по ФККО",
                     "Класс опасности", "Технологический процесс / подразделение",
                     "Ед. изм.", "Норматив образования",
                     "Предлагаемое ежегодное образование, т/год"],
               table, widths_cm=[0.9, 4.5, 2.4, 1.3, 3.5, 1.2, 2, 2.4], font_size=8)
    total = sum(r["norm"] or 0 for r in data)
    docx_para(doc, f"Итого предлагаемое образование отходов: {fmt_num(total or None)} "
                   f"т/год.", bold=True)


def _sec_6(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import (_fmt_code, _roman, docx_heading,
                                                     docx_para, docx_table, fmt_num)
    docx_heading(doc, _TOC[6], 1)
    docx_para(doc, (
        "Накопление отходов осуществляется раздельно по видам в оборудованных "
        "местах (площадках) накопления на срок не более 11 месяцев (ст. 1 "
        "Федерального закона № 89-ФЗ) с соблюдением требований СанПиН "
        "2.1.3684-21; вывоз — по мере формирования транспортной партии "
        "лицензированными организациями. Места накопления показаны на "
        "карте-схеме площадки (приложение 2)."), align="justify")
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    places = [p for p in (extra.get("waste_storage") or []) if isinstance(p, dict)]
    table = []
    if places:
        for p in places:
            codes = {str(c).replace(" ", "") for c in (p.get("wastes") or [])}
            for r in data:
                if r["fkko"] in codes:
                    table.append([p.get("number") or NA, p.get("name") or NA,
                                  p.get("capacity_t") or NA, p.get("capacity_m3") or NA,
                                  r["name"], _fmt_code(r["fkko"]), _roman(r["hazard"]),
                                  fmt_num(r["norm"]) if r["norm"] else NA,
                                  p.get("limit_t") or NA, p.get("limit_m3") or NA])
    else:
        for i, r in enumerate(data, start=1):
            table.append([f"МНО-{i}", _storage_name(r), NA, NA, r["name"] or NA,
                          _fmt_code(r["fkko"]), _roman(r["hazard"]),
                          fmt_num(r["norm"]) if r["norm"] else NA, NA, NA])
    docx_table(doc, ["№ на карте-схеме", "Наименование места накопления",
                     "Вместимость, т", "Вместимость, м³", "Наименование вида отхода",
                     "Код по ФККО", "Класс", "Планируемое ежегодное образование, т",
                     "Предельное накопление, т", "Предельное накопление, м³"],
               table, widths_cm=[1.6, 2.4, 1.4, 1.4, 4, 2.2, 1, 1.8, 1.4, 1.4],
               font_size=8)


def _storage_name(r: dict) -> str:
    """Типовое место накопления по классу/агрегатному состоянию отхода."""
    agg = (r.get("agg") or "").lower()
    if r.get("hazard") == 1:
        return "закрытое помещение, специальный контейнер (ртутьсодержащие)"
    if "жидк" in agg or "шлам" in agg or "паст" in agg:
        return "герметичная ёмкость на площадке с твёрдым покрытием"
    if r.get("fkko", "").startswith("73"):
        return "контейнерная площадка с твёрдым покрытием"
    if r.get("hazard") == 5:
        return "открытая площадка с твёрдым покрытием / бункер"
    return "закрытый контейнер на площадке с твёрдым покрытием"


def _sec_7(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import (_fmt_code, _roman, docx_heading,
                                                     docx_table, fmt_num)
    from ecodoc.core.waste_agg import transfer_kind
    docx_heading(doc, _TOC[7], 1)
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}

    docx_heading(doc, "7.1. Планируемая ежегодная обработка, утилизация, "
                      "обезвреживание отходов самим хозяйствующим субъектом", 2)
    own = [x for x in (extra.get("own_treatment") or []) if isinstance(x, dict)]
    docx_table(doc, ["№", "Наименование вида отходов", "Код по ФККО", "Класс",
                     "Технологический процесс", "Обработка, т", "Утилизация, т",
                     "Обезвреживание, т", "Всего, т"],
               [[str(i), x.get("name", ""), _fmt_code(x.get("fkko", "")),
                 _roman(x.get("hazard")), x.get("process", ""), x.get("processing", ""),
                 x.get("util", ""), x.get("neutral", ""), x.get("total", "")]
                for i, x in enumerate(own, start=1)],
               font_size=8, widths_cm=[0.8, 4, 2.2, 1, 3, 1.6, 1.6, 1.8, 1.4],
               empty_text="Хозяйствующий субъект деятельности по обработке, "
                          "утилизации, обезвреживанию отходов не ведёт")

    docx_heading(doc, "7.2. Планируемая ежегодная передача отходов другим "
                      "хозяйствующим субъектам для обработки, утилизации, "
                      "обезвреживания", 2)
    t72, t75 = [], []
    for i, r in enumerate(data, start=1):
        kinds = {transfer_kind(op) for op in r["operations"]}
        receiver, contract, term = _receiver_lines(ctx, r)
        norm = fmt_num(r["norm"]) if r["norm"] else NA
        if kinds & {"processing", "util", "neutral"} or not kinds:
            t72.append([str(i), r["name"] or NA, _fmt_code(r["fkko"]),
                        _roman(r["hazard"]),
                        norm if "processing" in kinds else NA,
                        norm if "util" in kinds or not kinds else NA,
                        norm if "neutral" in kinds else NA,
                        receiver, contract, term])
        if kinds & {"burial", "storage"}:
            t75.append([str(i), r["name"] or NA, _fmt_code(r["fkko"]),
                        _roman(r["hazard"]),
                        norm if "storage" in kinds else NA,
                        norm if "burial" in kinds else NA, norm,
                        receiver, contract, term])
    docx_table(doc, ["№", "Наименование вида отходов", "Код по ФККО", "Класс",
                     "Для обработки, т/год", "Для утилизации, т/год",
                     "Для обезвреживания, т/год",
                     "Получатель (наименование, ИНН, лицензия)",
                     "Дата и № договора", "Срок действия договора"],
               t72, widths_cm=[0.7, 3.6, 2.1, 0.9, 1.4, 1.4, 1.6, 4, 1.8, 1.5],
               font_size=8)

    docx_heading(doc, "7.3. Планируемый ежегодный приём отходов от других "
                      "хозяйствующих субъектов", 2)
    docx_table(doc, ["№", "Наименование вида отходов", "Код по ФККО", "Класс",
                     "Для обработки, т", "Для утилизации, т", "Для обезвреживания, т",
                     "От кого принимается", "Договор"],
               [], font_size=8,
               empty_text="Приём отходов от других хозяйствующих субъектов не "
                          "планируется")

    docx_heading(doc, "7.4. Планируемое ежегодное размещение отходов на "
                      "самостоятельно эксплуатируемых (собственных) объектах "
                      "размещения", 2)
    own_place = [[str(i), r["name"], _fmt_code(r["fkko"]), _roman(r["hazard"]),
                  extra.get("own_oro") or NA, NA, fmt_num(r["limit"]), fmt_num(r["limit"])]
                 for i, r in enumerate(data, start=1) if r["limit"]]
    docx_table(doc, ["№", "Наименование вида отходов", "Код по ФККО", "Класс",
                     "Объект размещения, № в ГРОРО", "Хранение, т",
                     "Захоронение, т", "Всего, т"],
               own_place, font_size=8,
               empty_text="Собственных объектов размещения отходов нет; "
                          "размещение на собственных объектах не планируется")

    docx_heading(doc, "7.5. Планируемая ежегодная передача отходов другим "
                      "хозяйствующим субъектам с целью их дальнейшего размещения", 2)
    docx_table(doc, ["№", "Наименование вида отходов", "Код по ФККО", "Класс",
                     "Хранение, т/год", "Захоронение, т/год", "Всего, т/год",
                     "Получатель (наименование, ИНН, лицензия, объект ГРОРО)",
                     "Дата и № договора", "Срок действия договора"],
               t75, widths_cm=[0.7, 3.6, 2.1, 0.9, 1.4, 1.5, 1.4, 4, 1.8, 1.5],
               font_size=8,
               empty_text="Передача отходов на размещение не планируется "
                          "(по актам все отходы передаются на утилизацию/"
                          "обезвреживание)")


def _sec_8(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import (_fmt_code, _origin_text, _roman,
                                                     docx_heading, docx_para,
                                                     docx_table, fmt_num)
    from ecodoc.core.waste_agg import transfer_kind
    docx_heading(doc, _TOC[8], 1)
    docx_para(doc, "Сводные данные по образованию отходов и запрашиваемым лимитам "
                   "на их размещение (по образцу приложения 13 к приказу № 1021):",
              align="justify")
    table = []
    for cls in (1, 2, 3, 4, 5):
        rs = [r for r in data if r["hazard"] == cls]
        if not rs:
            continue
        for r in rs:
            kinds = {transfer_kind(op) for op in r["operations"]}
            placing = "burial" in kinds or "storage" in kinds
            norm = fmt_num(r["norm"]) if r["norm"] else NA
            table.append([r["name"] or NA, _fmt_code(r["fkko"]), _roman(r["hazard"]),
                          _origin_text(r), "т/год", norm, norm,
                          norm if placing else NA,
                          "; ".join(r["receivers"]) if placing else NA,
                          fmt_num(r["limit"]) if r["limit"] else NA])
        table.append([f"Итого отходов {_roman(cls)} класса опасности", "", "", "", "",
                      fmt_num(sum(r["norm"] or 0 for r in rs) or None), "", "", "", ""])
    table.append(["ВСЕГО", "", "", "", "", fmt_num(sum(r["norm"] or 0 for r in data) or None),
                  "", fmt_num(sum(r["norm"] or 0 for r in data
                                  if {transfer_kind(op) for op in r["operations"]}
                                  & {"burial", "storage"}) or None), "",
                  fmt_num(sum(r["limit"] or 0 for r in data) or None)])
    docx_table(doc, ["Наименование вида отходов", "Код по ФККО", "Класс",
                     "Отходообразующий вид деятельности, процесс", "Ед. изм.",
                     "Норматив образования", "Максимальное годовое образование, т",
                     "Передаётся на размещение другим ХС, т/год",
                     "Объект размещения (получатель, № ГРОРО)",
                     "Размещение на собственных ОРО (лимит), т/год"],
               table, widths_cm=[3.8, 2.1, 0.9, 3, 1.1, 1.6, 1.8, 1.8, 3, 1.6],
               font_size=8)


def _sec_sources(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import docx_bullets, docx_heading, docx_para
    docx_heading(doc, "Список использованных источников", 1)
    docx_bullets(doc, [
        "Федеральный закон от 24.06.1998 № 89-ФЗ «Об отходах производства и "
        "потребления».",
        "Федеральный закон от 10.01.2002 № 7-ФЗ «Об охране окружающей среды».",
        "Приказ Минприроды России от 07.12.2020 № 1021 «Об утверждении методических "
        "указаний по разработке проектов нормативов образования отходов и лимитов "
        "на их размещение».",
        "Федеральный классификационный каталог отходов (приказ Росприроднадзора от "
        "22.05.2017 № 242, с изменениями).",
        "Приказ Минприроды России от 31.03.2025 № 158 «Об утверждении критериев "
        "отнесения отходов к I–V классам опасности…».",
        "Приказ Минприроды России от 08.12.2020 № 1028 «Об утверждении порядка "
        "учёта в области обращения с отходами».",
        "Приказ Минприроды России от 15.05.2026 № 286 (типовая форма паспорта "
        "отходов I–IV классов опасности).",
        "СанПиН 2.1.3684-21 «Санитарно-эпидемиологические требования к содержанию "
        "территорий городских и сельских поселений…».",
        "Методические рекомендации по оценке объёмов образования отходов "
        "производства и потребления (ГУ НИЦПУРО, 2003); Сборник удельных "
        "показателей образования отходов производства и потребления (1999).",
    ])
    docx_heading(doc, "Приложения", 1)
    docx_para(doc, "Перечень исходных данных и документов, прилагаемых к проекту "
                   "(по перечню данных для разработки ПНООЛР):", italic=True)
    passports = [r["name"] for r in data if r["passport"]]
    docx_bullets(doc, [
        "Приложение 1. Исходные данные предприятия (численность, режим работы, "
        "площади, сырьё и продукция).",
        "Приложение 2. Карта-схема площадки с местами накопления отходов.",
        "Приложение 3. Документы на землю и недвижимость (аренда/собственность).",
        "Приложение 4. Копии договоров на передачу отходов и лицензий получателей"
        + (": " + "; ".join(sorted({x for r in data for x in r["receivers"]})) + "."
           if any(r["receivers"] for r in data) else "."),
        "Приложение 5. Копии паспортов отходов, протоколов КХА и биотестирования"
        + (f" (паспорта в базе: {len(passports)})." if passports else "."),
        "Приложение 6. Данные учёта отходов (журнал по приказу № 1028, 2-ТП "
        "(отходы)) за предыдущие годы.",
        "Приложение 7. Расчётная часть (нормативы и лимиты по отходам) — файл "
        "«ПНООЛР_расчётная_часть.xlsx».",
    ])


def _sec_gaps(doc, ctx: ReportContext, data: list[dict]) -> None:
    from ecodoc.development.waste_inventory import docx_heading, docx_para
    docx_heading(doc, "Пометки программы: что дописать или уточнить", 1)
    problems = gaps(ctx, data)
    if not problems:
        docx_para(doc, "Замечаний нет.")
    for g in problems:
        docx_para(doc, "• " + g, size=10)


def generate_docx(ctx: ReportContext, out_path: str | Path) -> Path:
    """Текстовая часть ПНООЛР (.docx) по структуре приказа № 1021."""
    from ecodoc.development.waste_inventory import (docx_heading, docx_new,
                                                     docx_para)
    data = rows(ctx)
    doc = docx_new()
    _sec_title(doc, ctx)
    docx_heading(doc, "Содержание", 1)
    for line in _TOC:
        docx_para(doc, line)
    doc.add_page_break()
    _sec_intro(doc, ctx, data)
    _sec_1(doc, ctx)
    _sec_2(doc, ctx, data)
    _sec_3(doc, ctx, data)
    _sec_4(doc, ctx, data)
    _sec_5(doc, ctx, data)
    _sec_6(doc, ctx, data)
    _sec_7(doc, ctx, data)
    _sec_8(doc, ctx, data)
    _sec_sources(doc, ctx, data)
    _sec_gaps(doc, ctx, data)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


# ──────────────────────────────────────────────────────────────────────────
# .xlsx — расчётная часть (приложение к проекту)
# ──────────────────────────────────────────────────────────────────────────
def generate_xlsx(ctx: ReportContext, out_path: str | Path) -> Path:
    """Расчётная часть ПНООЛР (.xlsx): нормативы и лимиты, расчёт, факт по годам."""
    org = ctx.organization
    data = rows(ctx)
    wb = xlsx.new_workbook()

    ws = wb.create_sheet("Титул")
    xlsx.merge(ws, "A1:F1", TITLE.upper(), bold=True, align="center")
    xlsx.merge(ws, "A2:F2", f"{org.name or org.short_name} · "
                            f"{ctx.period.year or '____'} год · расчётная часть "
                            f"(приложение к текстовой части)", align="center")
    from ecodoc.development.waste_inventory import main_object, site_address
    o = main_object(ctx)
    info = [("ИНН", org.inn), ("ОГРН", org.ogrn),
            ("Объект НВОС", (o.code if o else "") or "—"),
            ("Адрес объекта", site_address(ctx) or "—"),
            ("Видов отходов", str(len(data)))]
    for i, (label, value) in enumerate(info, start=4):
        xlsx.cell(ws, f"A{i}", label, bold=True)
        xlsx.merge(ws, f"B{i}:F{i}", value or "—", align="left")
    xlsx.widths(ws, {"A": 26, "B": 30, "C": 18, "D": 18, "E": 18, "F": 18})

    ws2 = wb.create_sheet("Нормативы и лимиты")
    xlsx.header_row(ws2, 1, ["№", "Наименование отхода", "Код ФККО", "Класс",
                             "Норматив образования, т/год", "Метод определения",
                             "Лимит на размещение, т/год",
                             "Обращение", "Объекты размещения / приёмщики"])
    xlsx.widths(ws2, {"A": 5, "B": 44, "C": 16, "D": 8, "E": 18, "F": 34, "G": 18,
                      "H": 20, "I": 30})
    for i, r in enumerate(data, start=1):
        xlsx.data_row(ws2, i + 1, [i, r["name"] or "—", r["fkko"] or "—",
                                   r["hazard"] or "—", r["norm"],
                                   METHODS.get(r["method"], "не определён"),
                                   r["limit"],
                                   ", ".join(r["operations"]) or "—",
                                   ", ".join(r["receivers"]) or "—"])
    total_row = len(data) + 2
    xlsx.cell(ws2, f"B{total_row}", "ИТОГО", bold=True)
    xlsx.cell(ws2, f"E{total_row}", sum(r["norm"] or 0 for r in data) or None, bold=True)
    xlsx.cell(ws2, f"G{total_row}", sum(r["limit"] or 0 for r in data) or None, bold=True)

    ws5 = wb.create_sheet("Расчёт по формулам")
    xlsx.header_row(ws5, 1, ["Наименование отхода", "Код ФККО", "Стадия",
                             "Расчёт (исходные данные × норматив)", "т/год", "м³/год"])
    xlsx.widths(ws5, {"A": 44, "B": 16, "C": 14, "D": 90, "E": 12, "F": 12})
    row_i = 2
    for r in data:
        c = r.get("calc")
        if not c:
            continue
        for line in c["lines"]:
            xlsx.data_row(ws5, row_i, [r["name"] or "—", r["fkko"], c["stage"], line,
                                       None, None])
            row_i += 1
        xlsx.data_row(ws5, row_i, [r["name"] or "—", r["fkko"], c["stage"], "итого",
                                   c["t"], c["m3"] or None])
        row_i += 1
    if row_i == 2:
        xlsx.data_row(ws5, 2, ["исходных данных для расчёта по типовым формулам нет "
                               "(вкладка РАЗРАБОТКА → ООС)", "", "", "", None, None])

    years = sorted({y for r in data for y in r["years"]})
    ws4 = wb.create_sheet("Факт по годам")
    xlsx.header_row(ws4, 1, ["Наименование отхода", "Код ФККО"] + [str(y) for y in years]
                    + ["Среднее, т/год"])
    xlsx.widths(ws4, {"A": 44, "B": 16})
    for i, r in enumerate(data, start=2):
        vals = [r["years"].get(y) for y in years]
        avg = (sum(v for v in vals if v) / len([v for v in vals if v])) \
            if any(vals) else None
        xlsx.data_row(ws4, i, [r["name"] or "—", r["fkko"] or "—"] + vals + [avg])

    ws3 = wb.create_sheet("Чего не хватает")
    xlsx.header_row(ws3, 1, ["Что дописать или уточнить"])
    xlsx.widths(ws3, {"A": 110})
    for i, text in enumerate(gaps(ctx, data) or ["замечаний нет"], start=2):
        xlsx.data_row(ws3, i, [text])

    return xlsx.save(wb, Path(out_path))


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    """ПНООЛР: .docx — текстовая часть по приказу № 1021, .xlsx — расчётная."""
    out = Path(out_path)
    if out.suffix.lower() == ".xlsx":
        return generate_xlsx(ctx, out)
    return generate_docx(ctx, out)


def generate_all(ctx: ReportContext, out_dir: str | Path) -> dict:
    """Текстовая часть .docx + расчётная часть .xlsx; ответ API {path, files, gaps}."""
    out_dir = Path(out_dir)
    suffix = f"_{ctx.period.year}" if ctx.period.year else ""
    docx_path = generate_docx(ctx, out_dir / f"ПНООЛР{suffix}.docx")
    xlsx_path = generate_xlsx(ctx, out_dir / f"ПНООЛР_расчётная_часть{suffix}.xlsx")
    return {"path": str(docx_path), "files": [str(docx_path), str(xlsx_path)],
            "gaps": gaps(ctx)}
