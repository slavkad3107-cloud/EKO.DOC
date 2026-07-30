"""Инвентаризация стационарных источников выбросов (Приказ Минприроды № 871).

Питает НДВ, ПЭК, 2-ТП (воздух) и плату за выбросы. Данные берутся из того,
что программа извлекла из ООС/НДВ/проектной документации:
  * `ctx.extra['emission_sources']` — источники (номер, наименование, вещества);
  * `ctx.pollutants` (среда «воздух») — валовые выбросы по веществам.

Если источники не найдены, документ всё равно собирается: перечень веществ
есть, а в разделе «чего не хватает» прямо сказано, что нужны источники.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import Medium, ReportContext
from ecodoc.render import xlsx

TITLE = "Инвентаризация стационарных источников выбросов"


def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return None
    return float(d) if d else None


def sources(ctx: ReportContext) -> list[dict]:
    """Источники выбросов из разобранных документов."""
    out = []
    for s in (ctx.extra or {}).get("emission_sources", []):
        if not isinstance(s, dict):
            continue
        subs = [p for p in (s.get("pollutants") or []) if isinstance(p, dict)]
        out.append({"number": str(s.get("number") or ""),
                    "name": str(s.get("name") or ""),
                    "kind": str(s.get("kind") or ""),
                    "src": str(s.get("_src") or ""),
                    "pollutants": subs})
    return out


def air_pollutants(ctx: ReportContext) -> list[dict]:
    """Вещества-выбросы с массами (валовые за год)."""
    out = []
    for p in ctx.pollutants:
        if p.medium != Medium.AIR:
            continue
        total = sum(x for x in (_num(p.mass_norm), _num(p.mass_limit),
                                _num(p.mass_over)) if x)
        out.append({"code": p.code or "", "name": p.name or "",
                    "norm": _num(p.mass_norm), "limit": _num(p.mass_limit),
                    "over": _num(p.mass_over), "total": total or None,
                    "source": p.source or ""})
    return out


def gaps(ctx: ReportContext) -> list[str]:
    out = []
    srcs, subs = sources(ctx), air_pollutants(ctx)
    if not srcs:
        out.append("не найдены источники выбросов — загрузите раздел ООС, проект "
                   "НДВ или отчёт по инвентаризации (вкладка ЗАГРУЗКА, "
                   "категория «воздух»)")
    if not subs:
        out.append("не заданы вещества и массы выбросов — заполните вкладку ВЫБРОСЫ")
    for s in srcs:
        if not s["number"]:
            out.append(f"источник «{s['name'] or '—'}»: не указан номер")
        if not s["pollutants"]:
            out.append(f"источник №{s['number'] or '—'}: не указаны вещества и объёмы")
    for p in subs:
        if not p["code"]:
            out.append(f"вещество «{p['name'] or '—'}»: не указан код")
        if not p["total"]:
            out.append(f"вещество {p['name'] or p['code']}: не указана масса, т/год")
    return out


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    """Собрать документ инвентаризации выбросов (.xlsx)."""
    org = ctx.organization
    srcs, subs = sources(ctx), air_pollutants(ctx)
    wb = xlsx.new_workbook()

    ws = wb.create_sheet("Титул")
    xlsx.merge(ws, "A1:F1", TITLE.upper(), bold=True, align="center")
    xlsx.merge(ws, "A2:F2",
               f"(Приказ Минприроды России № 871) за {ctx.period.year or '____'} год",
               align="center")
    info = [("Организация", org.name or org.short_name), ("ИНН", org.inn),
            ("Объект НВОС", ", ".join(o.code for o in ctx.objects) or "—"),
            ("Адрес объекта", "; ".join(o.address for o in ctx.objects if o.address) or "—"),
            ("Источников выбросов", str(len(srcs))),
            ("Веществ", str(len(subs)))]
    for i, (label, value) in enumerate(info, start=4):
        xlsx.cell(ws, f"A{i}", label, bold=True)
        xlsx.merge(ws, f"B{i}:F{i}", value or "—", align="left")
    xlsx.widths(ws, {"A": 26, "B": 26, "C": 18, "D": 18, "E": 18, "F": 18})

    ws2 = wb.create_sheet("Источники")
    xlsx.header_row(ws2, 1, ["№ источника", "Наименование", "Тип",
                             "Вещества (код, наименование, г/с, т/год)",
                             "Откуда взято"])
    xlsx.widths(ws2, {"A": 14, "B": 38, "C": 18, "D": 56, "E": 26})
    for i, s in enumerate(srcs, start=2):
        subs_text = "; ".join(
            f"{p.get('code', '')} {p.get('name', '')}"
            f"{' — ' + str(p.get('g_s')) + ' г/с' if p.get('g_s') else ''}"
            f"{', ' + str(p.get('t_year')) + ' т/год' if p.get('t_year') else ''}"
            for p in s["pollutants"]) or "нет данных"
        xlsx.data_row(ws2, i, [s["number"] or "—", s["name"] or "—",
                               s["kind"] or "—", subs_text, s["src"] or "—"])

    ws3 = wb.create_sheet("Вещества")
    xlsx.header_row(ws3, 1, ["Код", "Вещество", "В пределах норматива, т/год",
                             "В пределах лимита, т/год", "Сверх лимита, т/год",
                             "Всего, т/год", "Источник данных"])
    xlsx.widths(ws3, {"A": 10, "B": 40, "C": 16, "D": 16, "E": 16, "F": 14, "G": 20})
    for i, p in enumerate(subs, start=2):
        xlsx.data_row(ws3, i, [p["code"] or "—", p["name"] or "—", p["norm"],
                               p["limit"], p["over"], p["total"],
                               p["source"] or "—"])

    ws4 = wb.create_sheet("Чего не хватает")
    xlsx.header_row(ws4, 1, ["Замечание"])
    xlsx.widths(ws4, {"A": 110})
    problems = gaps(ctx) or ["замечаний нет"]
    for i, text in enumerate(problems, start=2):
        xlsx.data_row(ws4, i, [text])

    return xlsx.save(wb, Path(out_path))
