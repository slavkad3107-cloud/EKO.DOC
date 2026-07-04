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


def profile_from_context(ctx: ReportContext) -> OrgProfile:
    """Собрать профиль из данных контекста + ручных флагов ctx.extra['profile']."""
    p = OrgProfile()
    for o in ctx.objects:
        c = _CAT_NORM.get(str(o.category).strip().upper())
        if c:
            p.categories.add(c)
        if o.region_code:
            p.region_codes.add(str(o.region_code))
    p.has_air = any(x.medium == Medium.AIR for x in ctx.pollutants)
    p.has_water = any(x.medium == Medium.WATER for x in ctx.pollutants)
    p.has_waste = bool(ctx.wastes)
    p.has_hazardous_waste = any(1 <= int(w.hazard_class) <= 4 for w in ctx.wastes)

    # ручные флаги перекрывают автоопределение
    prof = ctx.extra.get("profile", {}) if isinstance(ctx.extra, dict) else {}
    if "is_msp" in prof:
        p.is_msp = bool(prof["is_msp"])
    for key in ("has_air", "has_water", "has_waste", "has_hazardous_waste"):
        if key in prof:
            setattr(p, key, bool(prof[key]))
    if prof.get("categories"):
        p.categories |= {_CAT_NORM.get(str(c).upper(), str(c)) for c in prof["categories"]}
    if prof.get("region_codes"):
        p.region_codes |= {str(c) for c in prof["region_codes"]}
    return p


@dataclass
class CalendarEntry:
    due: date | None
    code: str
    title: str
    domain: str
    periodicity: str
    where: str
    coverage: str
    basis: str


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
    periodic: list[CalendarEntry] = []
    possession: list[CalendarEntry] = []
    for o in obligations_for(profile):
        if o.kind == "periodic" and o.due:
            for (m, d) in o.due:
                periodic.append(CalendarEntry(
                    date(year, m, d), o.code, o.title, o.domain,
                    o.periodicity, o.where, o.coverage, o.basis))
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
