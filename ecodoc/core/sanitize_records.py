"""Санитар реквизитов и записей: краткое наименование, объекты НВОС,
лицензии в справках-актах, происхождение паспортов отходов.

Замечания пользователя по живой базе (02.09.2026):
  * краткое наименование ИП «МИНИХ ЕЛЕНА АНАТОЛЬЕВНА» = полному, а должно
    быть «ИП Миних Е.А.»; у ЮЛ — «ООО «Технострой»» от полного «ОБЩЕСТВО С
    ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ТЕХНОСТРОЙ"»;
  * во вкладке ОБЪЕКТ — мусор: принимать только формат «41-0247-005048-П»;
  * в актах в графах лицензий — числа «181.0», «320.0», имя перевозчика;
  * паспорта отходов «откуда попало»: из расчёта платы, из апелляционной
    жалобы — а брать можно только из паспортов, протоколов КХА/биотеста,
    ООС, ПНООЛР, инвентаризации (в т.ч. сканов).
Всё отклонённое — с причиной, ничего не выдумываем.
"""
from __future__ import annotations

import re

from ecodoc.core.nvos import is_valid as nvos_valid, normalize as nvos_normalize

# ── краткое наименование ────────────────────────────────────────────────
_OPF = [
    ("общество с ограниченной ответственностью", "ООО"),
    ("публичное акционерное общество", "ПАО"),
    ("непубличное акционерное общество", "НАО"),
    ("акционерное общество", "АО"),
    ("закрытое акционерное общество", "ЗАО"),
    ("открытое акционерное общество", "ОАО"),
    ("индивидуальный предприниматель", "ИП"),
    ("муниципальное унитарное предприятие", "МУП"),
    ("государственное унитарное предприятие", "ГУП"),
    ("федеральное государственное унитарное предприятие", "ФГУП"),
    ("государственное бюджетное учреждение", "ГБУ"),
    ("муниципальное бюджетное учреждение", "МБУ"),
    ("садоводческое некоммерческое товарищество", "СНТ"),
    ("товарищество собственников жилья", "ТСЖ"),
]
_WORD = re.compile(r"[а-яёa-z0-9]+", re.I)


def _stem(w: str) -> str:
    w = w.lower().replace("ё", "е")
    return w[:6] if len(w) > 6 else w


def _initials(full: str) -> str:
    """«МИНИХ ЕЛЕНА АНАТОЛЬЕВНА» → «Миних Е.А.»"""
    parts = [p for p in _WORD.findall(full) if p.isalpha()]
    if not parts:
        return full.strip()
    sur = parts[0].capitalize()
    ini = "".join(p[0].upper() + "." for p in parts[1:3])
    return f"{sur} {ini}".strip()


def suggest_short_name(name: str, inn: str = "") -> str:
    """Краткое наименование из полного.

    ИП (12-значный ИНН или слово «предприниматель») → «ИП Фамилия И.О.»;
    ЮЛ с расшифрованной ОПФ → «ООО «Название»»; иначе — полное как есть."""
    full = str(name or "").strip()
    if not full:
        return ""
    low = full.lower().replace("ё", "е")
    is_ip = len(re.sub(r"\D", "", str(inn or ""))) == 12 or "предпринимател" in low
    for long, short in _OPF:
        if low.startswith(long):
            rest = full[len(long):].strip(" ,«»\"'")
            if short == "ИП":
                return f"ИП {_initials(rest)}"
            title = rest if rest.isupper() is False else rest.capitalize()
            return f"{short} «{title}»"
    if is_ip:
        return f"ИП {_initials(full)}"
    return full


def short_name_problem(name: str, short_name: str, inn: str = "") -> str:
    """Почему краткое наименование не годится («» — всё в порядке)."""
    full, short = str(name or "").strip(), str(short_name or "").strip()
    if not full:
        return ""
    if not short:
        return "краткое наименование не заполнено"
    if short.lower() == full.lower():
        return "краткое наименование совпадает с полным — нужно сокращённое " \
               f"(например «{suggest_short_name(full, inn)}»)"
    stems = {_stem(w) for w in _WORD.findall(full) if len(w) > 3}
    stems_short = {_stem(w) for w in _WORD.findall(short) if len(w) > 3}
    # у ИП сокращение — фамилия с инициалами: фамилия должна совпасть
    if stems and not (stems & stems_short):
        return ("краткое наименование не похоже на полное — вероятно, взято "
                f"из чужого документа; ожидается что-то вроде "
                f"«{suggest_short_name(full, inn)}»")
    return ""


# ── объекты НВОС ────────────────────────────────────────────────────────
def object_problem(code: str) -> str:
    """Только формат «41-0247-005048-П»; всё остальное — не объект."""
    if not nvos_valid(nvos_normalize(code)):
        return ("код объекта не в формате НВОС «NN-NNNN-NNNNNN-Б» — "
                "кадастровые номера, шифры проектов и прочее объектами не являются")
    return ""


def clean_objects(ctx) -> list[dict]:
    """Убрать из объектов всё, что не код НВОС. Возвращает удалённые."""
    removed = []
    keep = []
    for ob in ctx.objects:
        prob = object_problem(ob.code)
        if prob:
            removed.append({"label": f"{ob.code} {ob.name or ''}"[:70], "reason": prob})
            continue
        ob.code = nvos_normalize(ob.code)
        keep.append(ob)
    ctx.objects = keep
    return removed


# ── лицензии в справках-актах ───────────────────────────────────────────
# реквизит лицензии: «Л020-00113-47/00095706», «(78)-1234-СТОУ», «077 00456»,
# «№ 78-00123 от 01.01.2020», «Л 480082»; а «181.0», «320», «Прогресс» — нет
_RE_LIC = re.compile(
    r"(л\s?\d{3}|\(\d{2}\)|№\s?\d|\d{2,3}[-\s]\d{4,}|стоу|сто\b|от\s+\d{2}\.\d{2}\.\d{4}|"
    r"\d{3}\s?\d{5}|/\d{5,})", re.I)


def license_problem(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return f"«{s}» — просто число, не реквизит лицензии (похоже на " \
               f"значение из соседней графы таблицы)"
    if s.lower() in ("не указано", "нет", "-", "—"):
        return ""
    if not _RE_LIC.search(s) and not re.search(r"\d{4,}", s):
        return f"«{s[:30]}» не похоже на номер лицензии (нет номера/даты) — " \
               f"возможно, это наименование контрагента"
    return ""


def clean_act_licenses(ctx) -> list[dict]:
    """Очистить заведомо мусорные графы лицензий (число, имя). Возвращает правки."""
    fixed = []
    for i, a in enumerate(ctx.waste_acts):
        for attr in ("license", "carrier_license"):
            val = getattr(a, attr, "")
            prob = license_problem(val)
            if prob and (re.fullmatch(r"\d+(\.\d+)?", str(val).strip())
                         or str(val).strip().lower() == str(a.carrier or "").strip().lower()):
                fixed.append({"index": i, "field": attr, "was": val, "reason": prob})
                setattr(a, attr, "")
    return fixed


# ── происхождение паспортов ─────────────────────────────────────────────
# Состав и класс отхода — только из документов, где они установлены:
# паспорт, протокол КХА/биотестирования, ООС, ПНООЛР, инвентаризация,
# паспорт как скан (jpg/png — если ИИ прочитал в нём «паспорт»).
_PASSPORT_SRC = re.compile(
    r"паспорт|п\.?\s?о\.?\s?о\.?|протокол|прот\.|кха|биотест|био_|оос|пноолр|"
    r"инвентаризац|состав отход|класс опасности", re.I)
_NOT_PASSPORT_SRC = re.compile(
    r"расч[её]т.{0,20}плат|деклараци|жалоб|1028|журнал|отч[её]т 1028|"
    r"справк|акт|договор|счет|счёт|платеж|2-тп|2тп", re.I)


def passport_source_ok(src: str) -> bool:
    """Годится ли документ-источник для паспорта (по имени файла)."""
    s = str(src or "")
    if _NOT_PASSPORT_SRC.search(s) and not _PASSPORT_SRC.search(s):
        return False
    if _PASSPORT_SRC.search(s):
        return True
    # сканы-картинки: имя ничего не говорит — не отвергаем, но и не ручаемся
    return bool(re.search(r"\.(jpe?g|png|tiff?)\b", s, re.I))


def check_passports(ctx) -> list[dict]:
    """Сверка паспортов: источник, каталог ФККО, наименование/класс, акты."""
    from ecodoc.core import fkko
    from ecodoc.core.waste_agg import norm_fkko
    act_codes = {norm_fkko(a.fkko_code) for a in ctx.waste_acts}
    flow_codes = {norm_fkko(w.fkko_code) for w in ctx.wastes}
    out = []
    seen: dict = {}
    for i, p in enumerate((ctx.extra or {}).get("waste_passports") or []):
        if not isinstance(p, dict):
            continue
        code = norm_fkko(p.get("fkko"))
        src = str(p.get("_src") or "")
        chk = fkko.check(code, str(p.get("name") or "")) if code else None
        comps = [c for c in (p.get("components") or []) if isinstance(c, dict)]
        problems = []
        src_ok = passport_source_ok(src)
        if not src_ok:
            problems.append("источник не паспорт/протокол/ООС/ПНООЛР — данные "
                            "могли попасть из чужого документа")
        if not code:
            problems.append("нет кода ФККО")
        elif chk and not chk.ok:
            problems.append(chk.problem)
        if chk and chk.ok and chk.verified:
            if chk.name_mismatch:
                problems.append(f"наименование расходится с каталогом: «{chk.name[:50]}»")
            try:
                ours = int(p.get("hazard_class") or 0)
            except (TypeError, ValueError):
                ours = 0
            if ours and chk.hazard and ours != chk.hazard:
                problems.append(f"класс {ours}, а по каталогу {chk.hazard}")
        if not comps:
            problems.append("нет компонентного состава")
        if code and code in seen:
            problems.append(f"дубль паспорта по ФККО (строка {seen[code] + 1})")
        else:
            seen[code] = i
        in_acts = code in act_codes or code in flow_codes
        out.append({"index": i, "fkko": code, "fkko_fmt": fkko.fmt(code) if code else "",
                    "name": p.get("name") or "", "hazard_class": p.get("hazard_class") or "",
                    "components": len(comps), "src": src, "src_ok": src_ok,
                    "in_catalog": bool(chk and chk.verified),
                    "catalog_name": (chk.name if chk else "") or "",
                    "name_ok": not (chk and chk.name_mismatch),
                    "class_ok": not any("класс" in x and "каталогу" in x for x in problems),
                    "in_acts": in_acts, "problems": problems})
    return out


def clean_passports(ctx, drop_bad_source: bool = True, drop_dupes: bool = True) -> list[dict]:
    """Убрать паспорта из чужих документов и дубли. Возвращает удалённые."""
    from ecodoc.core.waste_agg import norm_fkko
    items = [p for p in ((ctx.extra or {}).get("waste_passports") or []) if isinstance(p, dict)]
    removed, keep, by_code = [], [], {}
    for p in items:
        src = str(p.get("_src") or "")
        code = norm_fkko(p.get("fkko"))
        comps = [c for c in (p.get("components") or []) if isinstance(c, dict)]
        if drop_bad_source and not passport_source_ok(src):
            removed.append({"label": f"{code} {p.get('name') or ''}"[:60],
                            "reason": f"источник «{src[:40]}» — не паспорт/протокол/ООС/ПНООЛР"})
            continue
        if drop_dupes and code and code in by_code:
            prev = by_code[code]
            if len(comps) > len(prev.get("components") or []):
                keep[keep.index(prev)] = p
                by_code[code] = p
                removed.append({"label": f"{code} {prev.get('name') or ''}"[:60],
                                "reason": "дубль паспорта (оставлен с составом)"})
            else:
                removed.append({"label": f"{code} {p.get('name') or ''}"[:60],
                                "reason": "дубль паспорта по ФККО"})
            continue
        keep.append(p)
        if code:
            by_code[code] = p
    ctx.extra["waste_passports"] = keep
    return removed
