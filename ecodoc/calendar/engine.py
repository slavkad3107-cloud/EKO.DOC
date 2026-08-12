"""Движок календаря: профиль организации → состав обязанностей → график на год."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ecodoc.calendar.obligations import OBLIGATIONS, Obligation, OrgProfile
from ecodoc.core.models import Medium, ReportContext
from ecodoc.core.money import D

_CAT_NORM = {"1": "I", "2": "II", "3": "III", "4": "IV",
             "I": "I", "II": "II", "III": "III", "IV": "IV"}


def norm_category(value) -> str:
    """Категория объекта НВОС к виду «I»…«IV».

    Категорию пишут по-разному — «III», «3», «III категория», «объект III
    категории», и сама программа подставляет «III категория» (nvos.py).
    Сравнение сырых строк отбрасывало такие объекты, и с ними из календаря
    пропадали обязанности (декларация, ПЭК и др.)."""
    import re
    s = str(value or "").strip().upper().replace("Ё", "Е")
    s = re.sub(r"КАТЕГОРИ\w*", " ", s)          # «III категория» → «III»
    s = re.sub(r"[^IVХ0-9]", " ", s.replace("Х", "X")).strip()
    if not s:
        return ""
    token = s.split()[0]
    return _CAT_NORM.get(token, "")


def _to_water_body(receiver) -> bool:
    """Приёмник стоков — водный объект, а не сеть водоотведения."""
    s = str(receiver or "").lower().replace("ё", "е")
    if not s:
        return False
    sewer = ("канализац", "цсв", "водоканал", "сеть", "коллектор", "гуп",
             "договор", "абонент", "очистные сооружения города")
    if any(w in s for w in sewer):
        return False
    body = ("река", "р.", "озер", "залив", "канал", "ручей", "море", "пруд",
            "водны", "водоем", "водоём", "рельеф")
    return any(w in s for w in body)


def category_of(obj) -> str:
    """Категория объекта: из поля, а если там мусор — из буквы кода НВОС."""
    cat = norm_category(getattr(obj, "category", ""))
    if cat:
        return cat
    try:
        from ecodoc.core import nvos
        return norm_category(nvos.category(getattr(obj, "code", "")))
    except Exception:
        return ""


def profile_from_context(ctx: ReportContext) -> OrgProfile:
    """Собрать профиль из данных контекста + ручных флагов ctx.extra['profile']."""
    p = OrgProfile()
    for o in ctx.objects:
        c = category_of(o)
        if c:
            p.categories.add(c)
        if o.region_code:
            p.region_codes.add(str(o.region_code))
    p.has_air = any(x.medium == Medium.AIR for x in ctx.pollutants)
    p.has_water = any(x.medium == Medium.WATER for x in ctx.pollutants)
    p.has_waste = bool(ctx.wastes)
    p.has_hazardous_waste = any(1 <= int(w.hazard_class) <= 4 for w in ctx.wastes)
    # сброс в водный объект — это отдельный факт, а не «есть строка со средой
    # вода»: у большинства объектов стоки уходят в городскую канализацию, и
    # ни 2-ТП (водхоз), ни проект НДС им не требуются. Признак берём из блока
    # водоучёта (приёмник — водный объект) либо из ручного флага профиля.
    water = (ctx.extra or {}).get("water") or {}
    p.discharges_to_water_body = any(
        _to_water_body(d.get("receiver")) for d in (water.get("discharge") or [])
        if isinstance(d, dict))

    # ручные флаги перекрывают автоопределение
    prof = ctx.extra.get("profile", {}) if isinstance(ctx.extra, dict) else {}
    if "is_msp" in prof:
        p.is_msp = bool(prof["is_msp"])
    for key in ("has_air", "has_water", "has_waste", "has_hazardous_waste",
                "discharges_to_water_body", "needs_szz", "is_rop"):
        if key in prof:
            setattr(p, key, bool(prof[key]))
    if prof.get("categories"):
        p.categories |= {norm_category(c) or str(c) for c in prof["categories"]}
    if prof.get("region_codes"):
        p.region_codes |= {str(c) for c in prof["region_codes"]}
    return p


@dataclass
class CalendarEntry:
    due: date | None          # фактический срок (с переносом с выходного)
    code: str
    title: str
    domain: str
    periodicity: str
    where: str
    coverage: str
    basis: str
    due_norm: date | None = None   # нормативная дата (как в НПА, без переноса)
    done: str = ""                 # отметка о сдаче: дата/номер квитанции


def submitted_marks(ctx) -> dict:
    """Отметки о сдаче: {код обязанности: «сдано 28.01.2026, вх. №…»}."""
    marks = (ctx.extra or {}).get("submitted") or {}
    return {str(k): str(v) for k, v in marks.items() if v}


# коды форм в программе ↔ коды обязанностей в реестре: без этой карты
# подсказка о сроке не показывалась для отчёта ПЭК и кадастра
FORM_TO_OBLIGATION = {
    "pek": "pek-report",
    "cadastre-spb": "cadastre",
}


def _penalty(obl) -> str:
    """Чем грозит просрочка именно этой обязанности."""
    if obl.code in ("2tp-air", "2tp-waste", "2tp-water", "4-oos"):
        return ("Статистическая форма — ответственность по ст. 13.19 КоАП "
                "(непредоставление первичных статистических данных).")
    if obl.code in ("nvos-payment", "nvos-advance"):
        return ("За просрочку платы начисляются пени (п. 4 ст. 16.4 ФЗ-7).")
    return "Возможен штраф по ст. 8.5 КоАП (сокрытие экологической информации)."


def workday(d: date) -> date:
    """Срок, выпавший на выходной, переносится на ближайший рабочий день.

    Общее правило (ст. 193 ГК РФ, п. 7 ст. 6.1 НК РФ). Без этого программа
    объявляла отчёт просроченным в его же законный последний день."""
    while d.weekday() >= 5:            # 5 — суббота, 6 — воскресенье
        d = date.fromordinal(d.toordinal() + 1)
    return d


def obligations_for(profile: OrgProfile) -> list[Obligation]:
    return [o for o in OBLIGATIONS if _safe(o, profile)]


def _safe(o: Obligation, p: OrgProfile) -> bool:
    try:
        return bool(o.applies(p))
    except Exception:
        return False


def build_calendar(ctx: ReportContext, year: int) -> tuple[list[CalendarEntry], list[CalendarEntry]]:
    """Вернуть (периодические записи с датами, чек-лист наличия без дат)."""
    profile = profile_from_context(ctx)
    marks = submitted_marks(ctx)
    periodic: list[CalendarEntry] = []
    possession: list[CalendarEntry] = []
    for o in obligations_for(profile):
        if o.kind == "periodic" and o.due:
            for (m, d) in o.due:
                norm = date(year, m, d)
                periodic.append(CalendarEntry(
                    workday(norm), o.code, o.title, o.domain,
                    o.periodicity, o.where, o.coverage, o.basis, norm,
                    done=marks.get(f"{o.code}:{year}") or marks.get(o.code, "")))
        else:
            possession.append(CalendarEntry(
                None, o.code, o.title, o.domain, o.periodicity,
                o.where, o.coverage, o.basis))
    periodic.sort(key=lambda e: e.due)
    return periodic, possession


def render_console(ctx: ReportContext, year: int) -> str:
    profile = profile_from_context(ctx)
    periodic, possession = build_calendar(ctx, year)
    lines = [
        f"КАЛЕНДАРЬ ЭКОЛОГИЧЕСКОЙ ОТЧЁТНОСТИ на {year} год",
        f"Организация: {ctx.organization.name or '—'}",
        f"Категории объектов: {', '.join(sorted(profile.categories)) or '— (не задана!)'}"
        f"   Воздух:{_yn(profile.has_air)} Вода:{_yn(profile.has_water)} "
        f"Отходы:{_yn(profile.has_waste)} МСП:{_yn(profile.is_msp)}",
        "",
        "── Сроки подачи (контур «Отчётность») ──",
    ]
    for e in periodic:
        lines.append(f"  {e.due:%d.%m.%Y}  {e.title}")
        lines.append(f"              {e.coverage} · {e.where} · осн.: {e.basis}")
    if not periodic:
        lines.append("  (нет периодических обязанностей — проверьте категорию и виды воздействия)")
    lines += ["", "── Обязательны к наличию (контур «Разработка») ──"]
    for e in possession:
        lines.append(f"  • {e.title}  [{e.where}]  осн.: {e.basis}")
    if not possession:
        lines.append("  (нет)")
    lines.append("\n⚠ Сроки/применимость сверяйте с действующими НПА; кадастр — срок региональный.")
    return "\n".join(lines)


def deadline_note(form_code: str, report_year: int,
                  today: date | None = None) -> str:
    """Подсказка о сроке сдачи формы за report_year (пусто, если срока нет).

    Срок берётся из реестра обязанностей (год отчёта + 1). Возвращает
    предупреждение о просрочке или напоминание, если срок близко.
    """
    if not report_year:
        return ""
    today = today or date.today()
    code = FORM_TO_OBLIGATION.get(form_code, form_code)
    obl = next((o for o in OBLIGATIONS
                if o.code == code and o.kind == "periodic" and o.due), None)
    if not obl:
        return ""
    due_year = report_year + 1
    nearest = min((workday(date(due_year, m, d)) for (m, d) in obl.due),
                  key=lambda dd: abs((dd - today).days))
    delta = (nearest - today).days
    when = nearest.strftime("%d.%m.%Y")
    if delta < 0:
        return (f"⚠ Срок сдачи «{obl.title}» за {report_year} год истёк "
                f"{-delta} дн. назад ({when}). {_penalty(obl)}")
    if delta <= 30:
        return f"⏰ До срока сдачи «{obl.title}» за {report_year} год — {delta} дн. ({when})."
    return ""


def export_ics_text(ctx: ReportContext, year: int) -> str:
    """Календарь сроков в формате iCalendar (Outlook/Google/Яндекс).

    Каждый срок — событие на весь день с напоминанием за 7 дней.
    """
    periodic, _ = build_calendar(ctx, year)
    org = ctx.organization.short_name or ctx.organization.name or "ЭКО.DOC"

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//EKO.DOC//calendar//RU",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{esc('Экоотчётность ' + org)}"]
    for e in periodic:
        d = e.due.strftime("%Y%m%d")
        lines += ["BEGIN:VEVENT",
                  f"UID:ecodoc-{e.code}-{d}@ekodoc",
                  f"DTSTART;VALUE=DATE:{d}",
                  f"SUMMARY:{esc(e.title)}",
                  f"DESCRIPTION:{esc(f'{e.coverage} · {e.where} · осн.: {e.basis}')}",
                  "BEGIN:VALARM", "ACTION:DISPLAY",
                  f"DESCRIPTION:{esc('Через 7 дней срок: ' + e.title)}",
                  "TRIGGER:-P7D", "END:VALARM",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def export_ics(ctx: ReportContext, year: int, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(export_ics_text(ctx, year), encoding="utf-8")
    return out_path


def export_xlsx(ctx: ReportContext, year: int, out_path: Path) -> Path:
    from ecodoc.render import xlsx

    periodic, possession = build_calendar(ctx, year)
    wb = xlsx.new_workbook()

    ws = wb.create_sheet("Сроки подачи")
    xlsx.header_row(ws, 1, ["Срок", "Отчёт", "Покрытие", "Куда", "Периодичность", "Основание"],
                    widths=[12, 46, 34, 26, 14, 34])
    r = 2
    for e in periodic:
        xlsx.data_row(ws, r, [e.due.strftime("%d.%m.%Y"), e.title, e.coverage,
                              e.where, e.periodicity, e.basis])
        r += 1

    ws2 = wb.create_sheet("Наличие документов")
    xlsx.header_row(ws2, 1, ["Документ", "Где", "Основание"], widths=[52, 30, 36])
    r = 2
    for e in possession:
        xlsx.data_row(ws2, r, [e.title, e.where, e.basis])
        r += 1
    return xlsx.save(wb, out_path)


def _yn(v: bool) -> str:
    return "да" if v else "нет"
