"""Кросс-сверка: сводим находки из разных документов и решаем, что брать в базу.

Требование ТЗ: «должна быть кросс-сверка данных, которые выбираются в базу…
в случае если данные разняться надо показать откуда какие и предложить выбрать
какие взять в базу, если отсутствуют предложить ввести, только конкретно, что
вводить надо запрашивать».

Правила простые и предсказуемые:
  * одно значение из одного документа  → берём молча (если поле пустое);
  * одно значение из нескольких        → берём, помечаем «подтверждено N док.»;
  * разные значения                    → НЕ берём, спрашиваем пользователя;
  * критичные реквизиты (ИНН, КПП, ОГРН, ОКТМО, код объекта) — всегда
    показываем на подтверждение, даже если кандидат один: ошибка в них стоит
    дороже, чем лишний вопрос.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from ecodoc.intake.candidates import (ACCEPTED, MANUAL, NEW, REJECTED, Candidate,
                                      _norm_value, parse_key, read, write)

SINGLE, AGREE, CONFLICT, UNIT_DOUBT = "single", "agree", "conflict", "unit_doubt"

# поля, которые не применяем без подтверждения человеком
CRITICAL = {"organization.inn", "organization.kpp", "organization.ogrn",
            "organization.okpo", "organization.oktmo", "period.year"}

_MASS_ATTRS = {"mass", "generated", "transferred", "placed_norm", "placed_over",
               "mass_norm", "mass_limit", "mass_over", "volume_m3"}


@dataclass
class Group:
    key: str
    label: str
    status: str = SINGLE
    hint: str = ""
    current: str = ""                     # что сейчас в базе
    values: list = field(default_factory=list)   # [{value, norm, ids, docs, pages}]

    @property
    def is_question(self) -> bool:
        return self.status in (CONFLICT, UNIT_DOUBT)


@dataclass
class Ask:
    path: str
    label: str
    question: str
    forms: list = field(default_factory=list)
    docs: list = field(default_factory=list)


def _is_critical(key: str) -> bool:
    coll, _sel, attr = parse_key(key)
    return key in CRITICAL or (coll == "objects" and attr == "code")


def _as_decimal(value: str):
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _is_blank(value) -> bool:
    """Пусто ли поле в базе. Ноль в массах — это «не заполнено», а не значение
    (так же считает requirements._filled), иначе найденную массу было бы некуда
    записать: у новой позиции все числа нулевые."""
    if value in (None, ""):
        return True
    d = _as_decimal(value)
    return d is not None and d == 0


def to_tonnes(value: str, unit: str) -> str:
    """Привести массу к тоннам, если в документе были килограммы."""
    d = _as_decimal(value)
    if d is None:
        return str(value)
    u = (unit or "").strip().lower()
    if u in ("кг", "kg", "килограмм", "килограммов"):
        return str((d / 1000).normalize())
    return str(d.normalize())


def group(cands: list[Candidate], ctx=None) -> list[Group]:
    """Свести кандидатов по полю и определить, что спрашивать у пользователя."""
    by_key: dict[str, list[Candidate]] = {}
    for c in cands:
        if c.state in (REJECTED,):
            continue
        by_key.setdefault(c.key, []).append(c)

    out: list[Group] = []
    for key, items in by_key.items():
        _coll, _sel, attr = parse_key(key)
        vals: dict[str, dict] = {}
        for c in items:
            value = to_tonnes(c.value, c.unit) if attr in _MASS_ATTRS else c.value
            norm = _norm_value(key, value)
            v = vals.setdefault(norm, {"value": value, "norm": norm, "ids": [],
                                       "docs": [], "pages": []})
            v["ids"].append(c.id)
            if c.file and c.file not in v["docs"]:
                v["docs"].append(c.file)
            if c.page:
                v["pages"].append({"doc": c.doc, "page": c.page, "file": c.file,
                                   "quote": c.quote})
        g = Group(key=key, label=items[0].label or key,
                  values=sorted(vals.values(), key=lambda v: -len(v["docs"])))
        if ctx is not None:
            cur = read(ctx, key)
            g.current = "" if _is_blank(cur) else str(cur)
        if len(g.values) == 1:
            g.status = AGREE if len(g.values[0]["docs"]) > 1 else SINGLE
        else:
            g.status = CONFLICT
            nums = [_as_decimal(v["value"]) for v in g.values]
            if all(n is not None and n != 0 for n in nums):
                ratio = max(nums) / min(nums)
                if ratio in (Decimal(1000), Decimal(1)) or \
                   abs(ratio - Decimal(1000)) < Decimal("0.01"):
                    g.status = UNIT_DOUBT
                    g.hint = "значения отличаются в 1000 раз — похоже, кг против тонн"
                elif abs(ratio - 1) <= Decimal("0.005"):
                    g.hint = "расхождение меньше 0,5 % — возможно, округление"
        # значение уже есть в базе и не совпадает с найденным — тоже вопрос
        if g.current and g.status in (SINGLE, AGREE) and \
                _norm_value(key, g.current) != g.values[0]["norm"]:
            g.status = CONFLICT
            g.hint = g.hint or "в базе уже есть другое значение"
        if _is_critical(key) and g.status in (SINGLE, AGREE):
            g.hint = g.hint or "ключевой реквизит — подтвердите вручную"
        out.append(g)
    out.sort(key=lambda g: (not g.is_question, g.label))
    return out


def auto_apply(ctx, store, groups: list[Group], enabled: bool = True) -> list[str]:
    """Записать в базу бесспорное: одно значение, поле пустое, не критичное."""
    applied: list[str] = []
    if not enabled:
        return applied
    for g in groups:
        if g.is_question or _is_critical(g.key) or g.current:
            continue
        value = g.values[0]["value"]
        if write(ctx, g.key, value):
            applied.append(g.key)
            for cid in g.values[0]["ids"]:
                c = store.by_id(cid)
                if c and c.state == NEW:
                    c.state = ACCEPTED
    return applied


def decide(ctx, store, key: str, value: str, accept: bool = True) -> bool:
    """Решение пользователя по группе: принять конкретное значение или отклонить."""
    ids = [c.id for c in store.items if c.key == key]
    if not accept:
        for cid in ids:
            c = store.by_id(cid)
            if c and c.state == NEW:
                c.state = REJECTED
        store.save()
        return True
    ok = write(ctx, key, value)
    if ok:
        norm = _norm_value(key, value)
        for cid in ids:
            c = store.by_id(cid)
            if not c:
                continue
            c.state = ACCEPTED if _norm_value(key, c.value) == norm else REJECTED
        store.save()
    return ok


def manual(ctx, store, key: str, value: str, label: str = "") -> bool:
    """Пользователь ввёл значение сам (когда в документах его не нашлось)."""
    if not write(ctx, key, value):
        return False
    store.add(Candidate(key=key, value=str(value), label=label or key,
                        method=MANUAL, state=ACCEPTED, file="введено вручную"))
    store.save()
    return True


def asks(ctx, forms: list[str] | None = None,
         pending_keys: set[str] | None = None) -> list[Ask]:
    """Чего не хватает — конкретным вопросом «введите X».

    Поля, по которым уже есть кандидат на выбор, не спрашиваем: сначала пусть
    пользователь решит по найденному."""
    from ecodoc.intake import requirements
    pending = pending_keys or set()
    seen, out = set(), []
    target = forms or list(requirements.REQUIREMENTS)
    for form in target:
        req = requirements.REQUIREMENTS.get(form)
        if not req:
            continue
        missing, docs = requirements.check(ctx, form)
        for path, label, *rest in req["fields"]:
            human = label
            if human not in missing or path in seen or path in pending:
                continue
            seen.add(path)
            question = rest[0] if rest else f"Введите: {label}"
            out.append(Ask(path=path, label=label, question=question,
                           forms=[form], docs=docs[:3]))
        for a in out:
            if form not in a.forms and a.label in missing:
                a.forms.append(form)
    return out


# ── комплектность протоколов по классу опасности (требование ТЗ) ─────────

def lab_gaps(ctx) -> list[str]:
    """Проверка протоколов: IV класс — КХА или сан-хим; V — плюс биотестирование
    на двух форм-факторах. Возвращает список замечаний для пользователя."""
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    labs = extra.get("lab_results") or []
    kinds_by_waste: dict[str, set] = {}
    for rec in labs:
        if not isinstance(rec, dict):
            continue
        kind = str(rec.get("kind") or "").lower()
        target = str(rec.get("object") or rec.get("waste") or "").lower()
        bucket = kinds_by_waste.setdefault(target, set())
        if "кха" in kind or "хим" in kind:
            bucket.add("кха")
        if "биотест" in kind or "токсик" in kind:
            bucket.add("биотест")
    all_kinds = set().union(*kinds_by_waste.values()) if kinds_by_waste else set()

    out = []
    for w in ctx.wastes:
        try:
            hz = int(w.hazard_class)
        except (TypeError, ValueError):
            continue
        name = w.name or w.fkko_code or "отход"
        own = set()
        for target, kinds in kinds_by_waste.items():
            if target and (target in (w.name or "").lower()
                           or (w.fkko_code or "") in target):
                own |= kinds
        kinds = own or all_kinds
        if hz == 4 and "кха" not in kinds:
            out.append(f"{name}: IV класс — нужен протокол КХА или санитарно-"
                       f"химический (в загруженных документах не найден)")
        if hz == 5:
            if "кха" not in kinds:
                out.append(f"{name}: V класс — нужен протокол КХА или санитарно-"
                           f"химический")
            if "биотест" not in kinds:
                out.append(f"{name}: V класс — НЕТ токсикологии/биотестирования "
                           f"(нужно на 2 форм-факторах для подтверждения V класса)")
    return out
