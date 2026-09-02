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


# получатель — региональный оператор / оператор по обращению с ТКО
# (2-ТП гр. 14 по п. 13 Указаний к № 614: «количество ТКО, переданных
# региональному оператору… оператору по обращению с ТКО»). Признак берём из
# текста получателя в акте/справке — отдельного поля в WasteAct нет.
_RE_REGOP = re.compile(r"регион|оператор\s+по\s+обращени[юя]\s+с\s+тко|оператор\s+тко", re.I)


def is_regional_operator(act: WasteAct) -> bool:
    """Получатель по акту — региональный оператор (оператор ТКО)?"""
    return bool(_RE_REGOP.search(f"{act.receiver or ''} {act.operation or ''}"))


def transfer_kind(op: str) -> str:
    """Назначение передачи по тексту операции акта: burial/storage/util/
    neutral/processing или '' — не распознано (тогда масса остаётся только
    в transferred, а форма 2-ТП не может разнести её по графам 15–23)."""
    op = (op or "").lower()
    if "захорон" in op or "размещ" in op:
        return "burial"
    if "хранени" in op:
        return "storage"
    if "утилиз" in op or "рецикл" in op:
        return "util"
    if "обезвреж" in op:
        return "neutral"
    if "обработ" in op or "сортиров" in op:
        return "processing"
    return ""


_RE_DATE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\b")
_RE_DATE_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


_MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
           "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11,
           "декабр": 12}
_RE_QUARTER = re.compile(r"\b(\d)\s*[-–]?\s*(?:й\s*)?кв(?:\.|артал)?\w*\s*(\d{2,4})?", re.I)
_RE_MONTH_YEAR = re.compile(r"\b(\d{1,2})[./](\d{4})\b")          # «03.2025»
_RE_YEAR = re.compile(r"\b(20\d{2})\b")
_ROMAN_Q = {"i": 1, "ii": 2, "iii": 3, "iv": 4}


def parse_period(text) -> tuple[int, int, int]:
    """(год, квартал, месяц) из даты ИЛИ текста периода; 0 — неизвестно.

    В справках операторов период пишут как угодно: «15.03.2025», «2025-03-15»,
    «3 кв 25», «III квартал 2024», «март 2025», «03.2025», «2025». Всё это —
    один и тот же смысл «к какому периоду отнести массу», поэтому разбор
    единый, и разбивка по годам/кварталам/месяцам строится из него."""
    s = str(text or "").strip().lower().replace("ё", "е")
    if not s:
        return 0, 0, 0
    m = _RE_DATE_ISO.search(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return y, ((mo - 1) // 3 + 1 if 1 <= mo <= 12 else 0), (mo if 1 <= mo <= 12 else 0)
    m = _RE_DATE.search(s)
    if m:
        mo, y = int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        return y, ((mo - 1) // 3 + 1 if 1 <= mo <= 12 else 0), (mo if 1 <= mo <= 12 else 0)
    m = _RE_QUARTER.search(s)
    if m and 1 <= int(m.group(1)) <= 4:
        q = int(m.group(1))
        y = int(m.group(2)) if m.group(2) else 0
        if 0 < y < 100:
            y += 2000
        return y, q, 0
    rm = re.search(r"\b(iv|iii|ii|i)\s*кв", s)
    if rm:
        y = _RE_YEAR.search(s)
        return (int(y.group(1)) if y else 0), _ROMAN_Q[rm.group(1)], 0
    m = _RE_MONTH_YEAR.search(s)
    if m and 1 <= int(m.group(1)) <= 12:
        mo, y = int(m.group(1)), int(m.group(2))
        return y, (mo - 1) // 3 + 1, mo
    for stem, mo in _MONTHS.items():
        if re.search(r"\b" + stem + r"[а-я]*\b", s):
            y = _RE_YEAR.search(s)
            return (int(y.group(1)) if y else 0), (mo - 1) // 3 + 1, mo
    y = _RE_YEAR.search(s)
    return (int(y.group(1)) if y else 0), 0, 0


def act_period(act: WasteAct) -> tuple[int, int, int]:
    """(год, квартал, месяц) акта: явные поля главнее, иначе разбор даты."""
    y, q, mo = int(act.year or 0), int(act.quarter or 0), int(act.month or 0)
    if y or q or mo:
        if mo and not q:
            q = (mo - 1) // 3 + 1
        return y, q, mo
    return parse_period(act.date)


def period_label(act: WasteAct) -> str:
    """«15.03.2025» / «март 2025» / «3 кв 2025» / «2025» / «без периода»."""
    y, q, mo = act_period(act)
    d = str(act.date or "").strip()
    if _RE_DATE.search(d) or _RE_DATE_ISO.search(d):
        return d                          # полная дата — показываем как есть
    names = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
             "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
    if mo:
        return f"{names[mo - 1]} {y or ''}".strip()
    if q:
        return f"{q} кв {y or ''}".strip()
    if y:
        return str(y)
    return "без периода"


def act_year_month(act: WasteAct):
    """(год, месяц) акта — из полей периода или даты; None — если нет."""
    y, _q, mo = act_period(act)
    return (y or None), (mo or None)


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


def aggregate_acts(acts: list[WasteAct], year=None, quarter=None,
                   warnings: list[str] | None = None) -> tuple[list[WasteFlow], list[dict]]:
    """Свернуть акты по ФККО в список WasteFlow + список получателей (для
    Приложения 3 журнала №1028, кадастра, формы III кат.).

    Если задан year (и quarter) — учитываются только акты этого периода по их
    дате (акты без даты включаются). В warnings (если передан список)
    дописываются предупреждения — напр. акт без распознанного назначения
    передачи, чтобы масса не терялась молча."""
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
        # имя — без учёта регистра, как в _flow_key: иначе акты без кода
        # давали «лом…» и «Лом…» двумя разными позициями
        key = code or (a.name or "").strip().lower()
        w = by_code.get(key)
        if w is None:
            w = WasteFlow(fkko_code=code, name=a.name, hazard_class=a.hazard_class)
            by_code[key] = w
            order.append(key)
        m = D(a.mass)
        op = _op(a)
        w.generated += m           # образовано (акт = образованный и переданный отход)
        w.transferred += m         # передано другим лицам, всего
        regop = is_tko(code) and is_regional_operator(a)
        kind = transfer_kind(op)
        if regop:
            # ТКО региональному оператору — это графа 14 формы 2-ТП, а не
            # графы 15–23 «по видам»; поэтому по видам НЕ раскладываем:
            # в 2-ТП гр.14 = transferred − сумма по видам
            pass
        elif kind == "burial":
            w.transferred_burial += m
        elif kind == "storage":
            w.transferred_storage += m
        elif kind == "util":
            w.transferred_util += m
        elif kind == "neutral":
            w.transferred_neutral += m
        elif kind == "processing":
            w.transferred_processing += m
        elif warnings is not None:
            # назначение передачи не распознано: масса остаётся только в
            # transferred (не теряется), но по графам 15–23 2-ТП её разнести
            # нельзя — эколог должен уточнить операцию в акте
            warnings.append(
                f"акт {a.date or 'без даты'} «{a.name}» ({code or 'без кода'}), "
                f"{float(m):g} т: не указано назначение передачи "
                f"(операция «{a.operation or ''}» — ожидается утилизация/"
                "обезвреживание/захоронение/хранение/обработка); в 2-ТП "
                "масса не разнесена по графам 15–23")
        # получатель (для Прил.3 / кадастра) — уникальный по (код, получатель);
        # mass и regional_operator нужны 2-ТП гр.14 (ТКО региональному оператору)
        if a.receiver:
            rk = (code, a.receiver)
            if rk not in seen_recv:
                seen_recv.add(rk)
                receivers.append({
                    "fkko": code, "receiver": a.receiver, "inn": a.receiver_inn,
                    "license": a.license, "carrier": a.carrier,
                    "operation": a.operation, "mass": 0.0,
                    "regional_operator": bool(is_regional_operator(a))})
            rec = next(r for r in receivers
                       if r["fkko"] == code and r["receiver"] == a.receiver)
            rec["mass"] = float(D(rec.get("mass") or 0) + m)

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
    # Ручные позиции, по которым актов нет, сохраняем, если в них есть либо
    # массы, либо осмысленное описание (код ФККО с классом, наименование).
    # Раньше выбрасывалась любая строка без масс — вместе с только что
    # заведённой вручную позицией, которую пользователь ещё не заполнил.
    out.extend(w for w in existing
               if _flow_key(w) not in seen and (_has_data(w) or _described(w)))
    return out


def _described(w: WasteFlow) -> bool:
    """У позиции есть содержательное описание, а не пустая строка-заготовка."""
    return bool(norm_fkko(w.fkko_code) or (w.name or "").strip())


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
    warnings: list[str] = []
    wastes, receivers = aggregate_acts(acts, year=year, quarter=quarter,
                                       warnings=warnings)
    ctx.wastes = _merge_flows(ctx.wastes or [], wastes)
    if receivers or warnings:
        if not isinstance(ctx.extra, dict):
            ctx.extra = {}
    if receivers:
        ctx.extra["waste_receivers"] = _merge_receivers(
            ctx.extra.get("waste_receivers"), receivers)
    # предупреждения агрегации — чтобы формы (2-ТП validate) могли их показать;
    # при каждом пересчёте список заменяется, а не копится
    if isinstance(ctx.extra, dict):
        if warnings:
            ctx.extra["waste_agg_warnings"] = warnings
        else:
            ctx.extra.pop("waste_agg_warnings", None)
    return True
