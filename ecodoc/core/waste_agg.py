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


def norm_fkko(code) -> str:
    """Нормализовать код ФККО: только цифры («4 71 101 01 52 1» == «47110101521»).
    Иначе один отход из ручного ввода и из ИИ раздваивается."""
    return re.sub(r"\D", "", str(code or ""))


def is_tko(fkko) -> bool:
    """ТКО — блок ФККО «7 3…» (единое определение для декларации/2-ТП/кадастра)."""
    return norm_fkko(fkko).startswith("73")


_RE_DATE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b")
_RE_DATE_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


def act_year_month(act: WasteAct):
    """(год, месяц) из даты акта: ДД.ММ.ГГГГ или ISO ГГГГ-ММ-ДД.
    (None, None) — если даты нет/не распознана."""
    s = str(act.date or "")
    m = _RE_DATE_ISO.search(s)          # сначала ISO — иначе «2025-02-01»
    if m:                                # парсился бы как год 2001
        yr, mon = int(m.group(1)), int(m.group(2))
    else:
        m = _RE_DATE.search(s)
        if not m:
            return None, None
        mon = int(m.group(2))
        yr = int(m.group(3))
        if yr < 100:
            yr += 2000
    return yr, (mon if 1 <= mon <= 12 else None)


def act_year_quarter(act: WasteAct):
    """(год, квартал) из даты акта; (None, None) — если даты нет."""
    yr, mon = act_year_month(act)
    if yr is None:
        return None, None
    return yr, ((mon - 1) // 3 + 1 if mon else None)


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
        code = norm_fkko(a.fkko_code)     # нормализация: пробелы в коде не двоят отход
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
        elif "обработ" in op or "сортиров" in op:
            w.transferred_processing += m
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


# поля, которые СЧИТАЮТСЯ из актов (перезаписываются агрегацией)
_ACT_FIELDS = ("generated", "transferred", "transferred_util",
               "transferred_neutral", "transferred_storage",
               "transferred_burial", "transferred_processing")


def _flow_key(w: WasteFlow) -> str:
    """Ключ слияния: нормализованный ФККО, а для позиций без кода — имя
    (тот же ключ, что в aggregate_acts — иначе безкодовые позиции дублируются)."""
    return norm_fkko(w.fkko_code) or (w.name or "").strip().lower()


def _merge_flows(existing: list[WasteFlow], computed: list[WasteFlow]) -> list[WasteFlow]:
    """Слить рассчитанное из актов движение с существующим (ручным/из журналов).

    Из актов берутся только их поля (_ACT_FIELDS); остальное — остатки на
    начало/конец, размещено (лимит/сверх), принято, обработано, утилизировано
    собственными силами, описательные поля — сохраняется из существующей
    позиции с тем же ФККО (иначе ручной ввод стирался бы при каждой загрузке).
    Ручные позиции без актов остаются как есть."""
    by_key = {}
    for w in existing:
        by_key.setdefault(_flow_key(w), w)
    out: list[WasteFlow] = []
    seen: set = set()
    for c in computed:
        k = _flow_key(c)
        prev = by_key.get(k)
        if prev is not None:
            for f in _ACT_FIELDS:
                setattr(prev, f, getattr(c, f))
            if not prev.name and c.name:
                prev.name = c.name
            if not norm_fkko(prev.fkko_code) and c.fkko_code:
                prev.fkko_code = c.fkko_code
            out.append(prev)
        else:
            out.append(c)
        seen.add(k)
    # ручные позиции, по которым актов нет, оставляем ТОЛЬКО если в них есть
    # данные (остатки/размещение/массы). Полностью нулевые строки — мусор
    # старого авто-добавления ФККО, вычищаются.
    out.extend(w for w in existing
               if _flow_key(w) not in seen and _has_data(w))
    return out


_DATA_FIELDS = ("accumulated_start", "accumulated_start_nakopl", "generated",
                "received", "processed", "used", "neutralized", "transferred",
                "transferred_processing", "transferred_util", "transferred_neutral",
                "transferred_storage", "transferred_burial", "placed_norm",
                "placed_over", "accumulated_end")


def _has_data(w: WasteFlow) -> bool:
    """Есть ли в позиции хоть одна ненулевая масса."""
    return any(D(getattr(w, f, 0)) != 0 for f in _DATA_FIELDS)


def _merge_receivers(existing: list, computed: list) -> list:
    """Обновить перечень получателей из актов, сохранив ручные дополнения.

    Записи из актов авторитетны по составу (какие пары ФККО→получатель есть),
    но ручные поля (договор, лицензия и т.п.), заполненные в существующей
    записи, не затираются пустыми."""
    old_by_key = {(norm_fkko(r.get("fkko")), (r.get("receiver") or "").strip()): r
                  for r in (existing or []) if isinstance(r, dict)}
    out = []
    for r in computed:
        key = (norm_fkko(r.get("fkko")), (r.get("receiver") or "").strip())
        prev = old_by_key.pop(key, None)
        if prev:
            merged = dict(prev)
            for k, v in r.items():
                if v:                      # непустое из актов обновляет
                    merged[k] = v
            out.append(merged)
        else:
            out.append(r)
    # ручные записи, которых нет в актах (напр. получатель прошлых лет) — оставить
    out.extend(old_by_key.values())
    return out


def apply_acts(ctx) -> bool:
    """Если заданы справки-акты — рассчитать из них движение (образовано/
    передано по видам) и слить с существующим движением, сохранив ручные поля
    (остатки, размещение, принято и т.п.). Если актов нет — оставить движение
    как есть. Возвращает True, если применено."""
    acts = getattr(ctx, "waste_acts", None) or []
    if not acts:
        return False
    per = getattr(ctx, "period", None)
    year = getattr(per, "year", None) or None
    quarter = getattr(per, "quarter", None) or None
    wastes, receivers = aggregate_acts(acts, year=year, quarter=quarter)
    ctx.wastes = _merge_flows(ctx.wastes or [], wastes)
    if receivers:
        if not isinstance(ctx.extra, dict):
            ctx.extra = {}
        ctx.extra["waste_receivers"] = _merge_receivers(
            ctx.extra.get("waste_receivers"), receivers)
    return True
