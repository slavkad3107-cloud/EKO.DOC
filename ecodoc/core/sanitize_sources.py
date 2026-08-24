"""Санитар источников выбросов (extra.emission_sources).

На реальной базе (Технострой) в перечне ИЗАВ набралось 352 записи из
93 файлов при ~10 настоящих источниках: двери эвакуационных выходов из тома
пожарной безопасности, источники шума «ИШ-11» из акустического расчёта,
вентсистемы из ИОС, вещества, записанные как источники, и дубли одного
номера («6501» / «№6501»). ИИ читает любую таблицу с колонками «№» и
«наименование» как перечень источников — здесь отсев и слияние дублей.

Как и у веществ/отходов: отклонённое не пропадает, а уходит в отчёт приёма
и в отчёт очистки с понятной причиной.
"""
from __future__ import annotations

import re

from ecodoc.core.sanitize import Verdict, codes_for_name, norm_code, norm_name

# слова, по которым строка — точно не источник выброса в атмосферу
_NOT_SOURCE_WORDS = (
    "дверь", "эвакуац", "шум", "иш-", "иш1", "иш2", "иш3", "источник шума",
    "лифт", "подпор", "дымоудален", "противодымн", "пожар",
    "светильник", "розетк", "кабель", "освещение",
    "регистратор", "этаж", "секция", "лестница", "время выхода",
    "точка отбора", "контрольная точка", "расчётная точка", "расчетная точка",
)

# латинские двойники кириллицы: OCR и копипаст из PDF мешают алфавиты
# («ИЗAВ» с латинской A, «источникa»), из-за чего словесные правила и
# префиксы номеров не срабатывали — приводим к кириллице перед сравнением
_HOMOGLYPHS = str.maketrans({
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
})


def _cyr(text: str) -> str:
    """Латинские двойники → кириллица (для словесных проверок и префиксов)."""
    return str(text or "").translate(_HOMOGLYPHS)
_PERIOD_WORDS = {
    "январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
    "сентябрь", "октябрь", "ноябрь", "декабрь", "итого", "всего", "год",
    "i квартал", "ii квартал", "iii квартал", "iv квартал",
}


def norm_source_number(value) -> str:
    """Номер ИЗАВ к единому виду: «№6501», «6501.0» → «6501»; «0001» остаётся.

    Ведущие нули — часть номера организованного источника, их не трогаем;
    убираем только «№», «#», пробелы и хвост «.0» от чисел из Excel."""
    s = _cyr(str(value or "").strip())
    if s.endswith(".0"):
        s = s[:-2]
    # «№ 6501», «#6501», «ИЗА 6503», «ИЗАВ-6503», «ист. 6505», «источник 6505»,
    # «№ ИЗАВ 1» — префиксы бывают ВЛОЖЕННЫМИ, поэтому (…)+ а не одно
    # срезание; длинное «источник(а)» — раньше короткого «ист», иначе
    # альтернация откусывает «ист» от «источника» и оставляет «очника»
    s = re.sub(r"^(?:(?:№|#|n|источника?|изав?|ист\.?|source)[\s.\-№]*)+", "",
               s, flags=re.I).strip()
    # «001.01.6501» — площадка.цех.источник из «Эколога»: номер — последний блок
    m = re.fullmatch(r"\d{1,3}\.\d{1,3}\.(\d{1,6})", s)
    if m:
        s = m.group(1)
    # слово вместо номера («источника», «ИЗА») — номера нет
    if s and not re.search(r"\d", s):
        return ""
    return s


def _is_substance_code(num: str) -> bool:
    """Похож ли «номер источника» на код вещества из перечня (0301, 2732…).

    Номера организованных ИЗАВ 0001–0999 с кодами веществ не пересекаются
    (коды веществ начинаются с 01xx и выше), 6xxx — неорганизованные, тоже
    не коды; поэтому совпадение с перечнем — надёжный признак."""
    from ecodoc.core.refdata import official_air
    code = norm_code(num)
    if not code or code.startswith("00") or code.startswith("6"):
        return False
    return code in official_air()


def effective_number(number, name) -> str:
    """Номер записи с учётом «имени-как-номера».

    «Автокран КС-55713» в графе номера при том же наименовании — это не
    номер, а продублированное имя: номера у записи нет. Используется и
    проверкой, и слиянием дублей — иначе они расходились."""
    num = norm_source_number(number)
    nm = str(name or "").strip()
    if num and nm and norm_name(_cyr(num)) == norm_name(_cyr(nm)):
        return ""
    return num


def check_source(number, name, pollutants=None) -> Verdict:
    """Пускать ли запись в перечень источников выбросов."""
    num = effective_number(number, name)
    nm = str(name or "").strip()
    v = Verdict(code=num)
    if not num and not nm:
        return Verdict(ok=False, reason="пустая запись: нет ни номера, ни наименования")
    low = norm_name(_cyr(nm))
    # слова-признаки ищем и в номере: акустика пишет «ИШ-21», ПБ — «Этаж 1,
    # Зона эвакуации 7», а ИИ кладёт это в графу номера
    raw_num = norm_name(_cyr(str(number or "")))
    hit = next((w for w in _NOT_SOURCE_WORDS if w in low or w in raw_num), "")
    if hit:
        return Verdict(ok=False, code=num,
                       reason=f"это не источник выбросов («{hit}» в записи) — "
                              f"строка из тома ПБ/ИОС/акустики попала в перечень ИЗАВ")
    # наименование — это вещество: таблицу веществ прочитали как источники
    # (у такой «записи» либо нет веществ, либо одно — оно само)
    if nm and len(pollutants or []) <= 1 and codes_for_name(nm):
        return Verdict(ok=False, code=num,
                       reason=f"«{nm[:40]}» — загрязняющее вещество, а не источник; "
                              f"таблица веществ принята за перечень источников")
    # номер — код вещества из официального перечня (0301, 0337, 2732…), а
    # «веществ» одно: это строка таблицы веществ объекта, не ИЗАВ
    if num and len(pollutants or []) <= 1 and _is_substance_code(num):
        return Verdict(ok=False, code=num,
                       reason=f"номер «{num}» — код загрязняющего вещества, а не "
                              f"источника; таблица веществ принята за перечень ИЗАВ")
    # месяц/квартал/год вместо источника — помесячная таблица выбросов из ООС
    if low in _PERIOD_WORDS or re.fullmatch(r"(\d\s*кв(артал)?\.?|20\d\d(\s*г\.?)?)", low):
        return Verdict(ok=False, code=num,
                       reason=f"«{nm[:30]}» — период, а не источник: помесячная "
                              f"таблица выбросов прочитана как перечень ИЗАВ")
    if not num and not (pollutants or []):
        # ни номера, ни веществ — одно название из какой-то таблицы тома;
        # источником это не станет, данных не добавит
        return Verdict(ok=False, code="",
                       reason="нет ни номера ИЗАВ, ни веществ — строка из "
                              "текста тома, а не источник выбросов")
    if not num:
        return Verdict(ok=True, code="", suspect=True,
                       reason="у источника нет номера — в НДВ/инвентаризации "
                              "каждый ИЗАВ нумеруется (0001…, 6001…)")
    if not nm and not (pollutants or []):
        return Verdict(ok=True, code=num, suspect=True,
                       reason="только номер, без наименования и веществ — "
                              "позиция ничего не даёт")
    return v


def _pkey(p: dict) -> str:
    return norm_code(p.get("code")) or norm_name(p.get("name"))


def merge_into(keep: dict, other: dict) -> None:
    """Долить в keep вещества из other, которых там ещё нет."""
    have = {_pkey(p) for p in (keep.get("pollutants") or []) if isinstance(p, dict)}
    for p in other.get("pollutants") or []:
        if not isinstance(p, dict):
            continue
        k = _pkey(p)
        if k and k not in have:
            keep.setdefault("pollutants", []).append(p)
            have.add(k)


def merge_sources(items: list) -> tuple[list, list]:
    """Слить дубли по нормализованному номеру (без номера — по имени).

    Остаётся запись с наибольшим числом веществ (обычно из инвентаризации
    или НДВ), вещества остальных доливаются. Возвращает (перечень, удалённые)."""
    by: dict = {}
    order: list = []
    removed: list = []
    for s in items:
        num = effective_number(s.get("number"), s.get("name"))
        key = num or ("name:" + norm_name(_cyr(str(s.get("name") or ""))))
        cand = dict(s, number=num)
        if key not in by:
            by[key] = cand
            order.append(key)
            continue
        keep = by[key]
        if len(cand.get("pollutants") or []) > len(keep.get("pollutants") or []):
            keep, cand = cand, keep          # богаче по веществам — остаётся
            by[key] = keep
        merge_into(keep, cand)
        removed.append({"label": f"№{num or '—'} {str(cand.get('name') or '')[:50]}",
                        "reason": f"дубль источника №{num or '—'} (оставлена запись "
                                  f"«{str(keep.get('name') or '')[:40]}»)",
                        "src": cand.get("_src", "")})
    return [by[k] for k in order], removed


def audit_sources(ctx) -> list[dict]:
    """Отчёт по источникам: что мусор, где дубли (ничего не меняет)."""
    out: list[dict] = []
    seen: dict = {}
    for i, s in enumerate((ctx.extra or {}).get("emission_sources") or []):
        if not isinstance(s, dict):
            continue
        v = check_source(s.get("number"), s.get("name"), s.get("pollutants"))
        row = {"index": i, "number": s.get("number"), "name": s.get("name"),
               "ok": v.ok, "suspect": v.suspect, "reason": v.reason,
               "norm_number": v.code, "pollutants": len(s.get("pollutants") or []),
               "src": s.get("_src", "")}
        key = v.code or ("name:" + norm_name(s.get("name")))
        if key in seen:
            row["duplicate_of"] = seen[key]
        else:
            seen[key] = i
        out.append(row)
    return out


def clean_sources(ctx, drop_bad: bool = True, drop_dupes: bool = True) -> dict:
    """Убрать мусор и дубли из источников выбросов. Возвращает отчёт."""
    items = [s for s in ((ctx.extra or {}).get("emission_sources") or [])
             if isinstance(s, dict)]
    report = {"removed_sources": [], "merged_sources": []}
    keep = []
    for s in items:
        v = check_source(s.get("number"), s.get("name"), s.get("pollutants"))
        if drop_bad and not v.ok:
            report["removed_sources"].append(
                {"label": f"№{s.get('number') or '—'} {str(s.get('name') or '')[:50]}",
                 "reason": v.reason, "src": s.get("_src", "")})
            continue
        keep.append(s)
    if drop_dupes:
        keep, merged = merge_sources(keep)
        report["merged_sources"] = merged
    ctx.extra["emission_sources"] = keep
    return report
