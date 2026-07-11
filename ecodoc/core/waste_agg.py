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

from ecodoc.core.models import WasteAct, WasteFlow
from ecodoc.core.money import D


def _op(act: WasteAct) -> str:
    return (act.operation or "").strip().lower()


def aggregate_acts(acts: list[WasteAct]) -> tuple[list[WasteFlow], list[dict]]:
    """Свернуть акты по ФККО в список WasteFlow + список получателей (для
    Приложения 3 журнала №1028, кадастра, формы III кат.)."""
    by_code: dict[str, WasteFlow] = {}
    order: list[str] = []
    receivers: list[dict] = []
    seen_recv: set = set()

    for a in acts:
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


def apply_acts(ctx) -> bool:
    """Если заданы справки-акты — рассчитать движение (wastes) и получателей из
    них (акты первичны). Если актов нет — оставить заполненное вручную движение.
    Возвращает True, если применено."""
    acts = getattr(ctx, "waste_acts", None) or []
    if not acts:
        return False
    wastes, receivers = aggregate_acts(acts)
    ctx.wastes = wastes
    if receivers:
        if not isinstance(ctx.extra, dict):
            ctx.extra = {}
        ctx.extra.setdefault("waste_receivers", receivers)
    return True
