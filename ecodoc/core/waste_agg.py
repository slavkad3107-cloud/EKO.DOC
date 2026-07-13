"""Агрегация справок-актов на отходы в движение (WasteFlow) + получателей.

Первичный ввод по отходам — список WasteAct (справки-акты): наименование,
ФККО, класс, масса, вид обращения (утилизация/обезвреживание/размещение/
хранение), перевозчик, приёмщик. Отсюда СЧИТАЮТСЯ все отходные формы: журнал
№1028, 2-ТП (отходы), кадастр, раздел отходов декларации.

Семантика для отходообразователя (акты — это ПЕРЕДАЧА отходов другим лицам):
образовано = сумма масс; всё передано; вид обращения задаёт, для чего передано
(утилизация/обезвреживание/захоронение/хранение); собственных размещения/
утилизации/обезвреживания нет (их делает получатель). Плату за размещение
эколог задаёт отдельно (placed_*), т.к. она зависит от договора/статуса ТКО.
"""
from __future__ import annotations

import re

from ecodoc.core.models import WasteAct, WasteFlow
from ecodoc.core.money import D


def _op(act: WasteAct) -> str:
    return (act.operation or "").strip().lower()


_RE_DATE = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})")


def act_year_quarter(act: WasteAct):
    """(год, квартал) из даты акта ДД.ММ.ГГГГ, или (None, None) если нет даты."""
    m = _RE_DATE.search(str(act.date or ""))
    if not m:
        return None, None
    mon = int(m.group(2))
    yr = int(m.group(3))
    if yr < 100:
        yr += 2000
    q = (mon - 1) // 3 + 1 if 1 <= mon <= 12 else None
    return yr, q


def _in_period(act: WasteAct, year, quarter) -> bool:
    """Попадает ли акт в отчётный период. Акты без даты включаются всегда."""
    if not year:
        return True
    ay, aq = act_year_quarter(act)
    if ay is None:            # нет даты — не отбрасываем
        return True
    if ay != int(year):
        return False
    if quarter and aq and int(aq) != int(quarter):
        return False
    return True


def aggregate_acts(acts: list[WasteAct], year=None, quarter=None) -> tuple[list[WasteFlow], list[dict]]:
    """Свернуть акты по ФККО в список WasteFlow + список получателей (для
    Приложения 3 журнала №1028, кадастра, формы III кат.).

    Если задан year (и quarter) — учитываются только акты этого периода по их
    дате (акты без даты включаются)."""
    by_code: dict[str, WasteFlow] = {}
    order: list[str] = []
    receivers: list[dict] = []
    seen_recv: set = set()

    for a in acts:
        if not _in_period(a, year, quarter):
            continue
        code = str(a.fkko_code or "").strip()
        if not code and not a.name:
            continue
        key = code or a.name
        w = by_code.get(key)
        if w is None:
            w = WasteFlow(fkko_code=code, name=a.name, hazard_class=a.hazard_class)
            by_code[key] = w
            order.append(key)
        m = D(a.mass)
        op = _op(a)
        w.generated += m           # образовано (акт = образованный и переданный отход)
        w.transferred += m         # передано другим лицам, всего
        if "захорон" in op or "размещ" in op:
            w.transferred_burial += m
        elif "хранени" in op:
            w.transferred_storage += m
        elif "утилиз" in op or "рецикл" in op:
            w.transferred_util += m
        elif "обезвреж" in op:
            w.transferred_neutral += m
        # получатель (для Прил.3 / кадастра) — уникальный по (код, получатель)
        if a.receiver:
            rk = (code, a.receiver)
            if rk not in seen_recv:
                seen_recv.add(rk)
                receivers.append({
                    "fkko": code, "receiver": a.receiver, "inn": a.receiver_inn,
                    "license": a.license, "carrier": a.carrier,
                    "operation": a.operation})

    wastes = [by_code[k] for k in order]
    return wastes, receivers


def period_breakdown(acts: list[WasteAct], year=None) -> dict:
    """Распределение массы актов по кварталам/месяцам за год + всего.
    Возвращает {'quarters': {1..4: т}, 'months': {1..12: т}, 'total': т,
    'no_date': т}. Для отображения в отчёте приёма («разнести по периодам»)."""
    quarters = {q: D(0) for q in (1, 2, 3, 4)}
    months = {mn: D(0) for mn in range(1, 13)}
    total = D(0)
    no_date = D(0)
    for a in acts:
        ay, aq = act_year_quarter(a)
        m = D(a.mass)
        if ay is None:
            no_date += m
            continue
        if year and ay != int(year):
            continue
        total += m
        if aq:
            quarters[aq] += m
        mo = _RE_DATE.search(str(a.date or ""))
        if mo:
            mon = int(mo.group(2))
            if 1 <= mon <= 12:
                months[mon] += m
    return {"quarters": {q: float(v) for q, v in quarters.items()},
            "months": {mn: float(v) for mn, v in months.items() if v},
            "total": float(total), "no_date": float(no_date)}


def apply_acts(ctx) -> bool:
    """Если заданы справки-акты — рассчитать движение (wastes) и получателей из
    них (акты первичны). Если актов нет — оставить заполненное вручную движение.
    Возвращает True, если применено."""
    acts = getattr(ctx, "waste_acts", None) or []
    if not acts:
        return False
    per = getattr(ctx, "period", None)
    year = getattr(per, "year", None) or None
    quarter = getattr(per, "quarter", None) or None
    wastes, receivers = aggregate_acts(acts, year=year, quarter=quarter)
    ctx.wastes = wastes
    if receivers:
        if not isinstance(ctx.extra, dict):
            ctx.extra = {}
        ctx.extra.setdefault("waste_receivers", receivers)
    return True
