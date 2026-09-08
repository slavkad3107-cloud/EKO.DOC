"""Таблицы отходов из ООС/ПНООЛР — детерминированно, без ИИ.

Эколог (08.09.2026): «ООС загружен был», а нормативов нет — ИИ-разбор
279-страничного тома упирался в лимиты облака и молчал. Между тем сводные
таблицы «Количество отходов, ожидаемых при проведении строительных работ» /
«… при эксплуатации» в тексте ООС читаются напрямую: наименование, код по
ФККО, класс, м³, т. Здесь они разбираются по тексту страниц (в т.ч. из
кэша текста и после OCR) и отдаются в том же виде, что ждёт
`analyzer._merge_oos_wastes` (stage, fkko, name, hazard_class, mass_t,
volume_m3, density, page).

Текст таблицы из PDF приходит «рваным»: наименование разбито по строкам,
иногда его хвост стоит ПОСЛЕ кода, два числа могут стоять в одной строке,
рядом мелькают номера строк. Поэтому опора — код ФККО: наименование и
класс берутся из каталога ФККО (если код там есть), а из текста — только
числа после кода (объём и масса, порядок — по шапке таблицы).
"""
from __future__ import annotations

import re

_CODE = re.compile(r"^\s*(\d)\s?(\d\d)\s?(\d\d\d)\s?(\d\d)\s?(\d\d)\s?(\d)\s*$")
_CLASS = re.compile(r"^\s*(I{1,3}|IV|V|[1-5])\s*(класс[а-я]*)?\s*$", re.I)
_NUMS = re.compile(r"(?<![\d,.])-?\d{1,7}(?:[.,]\d{1,4})?(?![\d,.])")
_DASH = re.compile(r"^\s*[-–—]\s*$")
_HEAD = re.compile(r"таблица\s*[\d.]*\s*[-–—]?\s*([^\n]{0,120})", re.I)
_STOP = re.compile(r"^\s*(всего|итого)\b", re.I)
_MEASURE = re.compile(r"оператор|размещен|утилизац|обезвреж|передач|лицензи|договор|"
                      r"полигон|захорон|накоплен|спецавтотранспорт|вывоз|переработ|"
                      r"специализирован|организац[а-я]*,? имеющ|региональн|"
                      r"^(передача|сдача|продажа|использован)", re.I)
_JUNK = re.compile(r"^(№|вид отхода|наименование.*|код по фкко|класс|опасно|опасности|сти|"
                   r"количество|ожидаемых|отходов|мероприятие по|обращению с|отходом|"
                   r"м3|м³|куб\.?\s?м|т|изм\.|кол\.уч\.|лист|№док\.|подпись|дата|"
                   r"взамен инв\.№|подпись и дата|инв\.№ подл)\s*$", re.I)
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
_VOL_HDR = re.compile(r"^\s*(м3|м³|куб\.?\s?м)\s*$", re.I)
_MASS_HDR = re.compile(r"^\s*(т|тонн[а-я]*|т/год)\s*$", re.I)


def _stage_of(heading: str) -> str:
    h = heading.lower().replace("ё", "е")
    if "строител" in h or "снос" in h or "демонтаж" in h:
        return "строительство"
    if "эксплуатац" in h:
        return "эксплуатация"
    return ""


def _clean_name(lines: list[str]) -> str:
    keep = []
    for ln in lines:
        t = ln.strip(" \t;")
        if not t or _JUNK.match(t) or _MEASURE.search(t) or _DASH.match(t):
            continue
        if _STOP.match(t) or _CLASS.match(t) or re.fullmatch(r"\d{1,3}", t):
            continue
        if _NUMS.fullmatch(t):
            continue
        keep.append(t)
    name = " ".join(keep)
    name = re.sub(r"\s+", " ", name).strip(" ,;")
    return name[:200]


def _numbers(lines: list[str], start: int, limit: int = 6) -> list[str]:
    """Числа после кода: сначала дробные, потом целые ≥ 100 (номера строк
    таблицы — маленькие целые — не считаем количеством)."""
    dec, big = [], []
    j = start
    while j < len(lines) and j < start + limit:
        t = lines[j].strip()
        if _CODE.match(t) or _STOP.match(t) or _HEAD.search(t):
            break
        for tok in _NUMS.findall(t):
            v = tok.replace(",", ".")
            if "." in v:
                dec.append(v)
            elif abs(int(v)) >= 100:
                big.append(v)
        if len(dec) >= 2:
            break
        j += 1
    out = dec[:2]
    if len(out) < 2:
        out += big[: 2 - len(out)]
    return out


def _class_near(lines: list[str], idx: int) -> int:
    """Класс опасности рядом с кодом (до 2 строк выше и до 3 ниже)."""
    for k in list(range(idx + 1, min(len(lines), idx + 4))) + [idx - 1, idx - 2]:
        if 0 <= k < len(lines):
            m = _CLASS.match(lines[k].strip())
            if m:
                tok = m.group(1).upper()
                return _ROMAN.get(tok) or int(tok)
    return 0


def _header_order(lines: list[str], upto: int, start: int = 0) -> str:
    """«vol» — в шапке сначала м³, потом т (обычно); «mass» — наоборот.
    Смотрим только шапку ЭТОЙ таблицы (от заголовка до первого кода) —
    иначе колонки соседней мелкой таблицы выше путали порядок."""
    vi = mi = None
    for k in range(max(0, start, upto - 40), upto):
        t = lines[k]
        if vi is None and _VOL_HDR.match(t):
            vi = k
        if mi is None and _MASS_HDR.match(t):
            mi = k
    if vi is not None and mi is not None and mi < vi:
        return "mass"
    return "vol"


def parse_page(text: str, stage_hint: str = "") -> tuple[list[dict], str]:
    """Строки таблицы отходов на странице; возвращает (строки, стадия
    последней найденной таблицы) — стадия переносится на следующую страницу,
    если таблица продолжается без заголовка."""
    from ecodoc.core import fkko
    lines = text.splitlines()
    rows: list[dict] = []
    stage = stage_hint
    buf: list[str] = []
    head_at, order = 0, ""
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _HEAD.search(ln)
        if m and re.search(r"отход", m.group(1), re.I):
            st = _stage_of(m.group(1))
            if st:
                stage = st
            buf = []
            head_at, order = i, ""          # порядок колонок — по шапке этой таблицы
            i += 1
            continue
        cm = _CODE.match(ln)
        if cm and stage:
            code = "".join(cm.groups())
            name = _clean_name(buf)
            buf = []
            hazard = _class_near(lines, i)
            chk = fkko.check(code)
            if getattr(chk, "verified", False) and getattr(chk, "name", ""):
                name = chk.name                     # каталог надёжнее рваного текста
                hazard = hazard or int(getattr(chk, "hazard", 0) or 0)
            if not hazard and code[-1] in "12345":
                hazard = int(code[-1])
            nums = _numbers(lines, i + 1)
            if not order:
                order = _header_order(lines, i, start=head_at)
            if order == "mass":
                mass = nums[0] if len(nums) > 0 else ""
                vol = nums[1] if len(nums) > 1 else ""
            else:
                vol = nums[0] if len(nums) > 0 else ""
                mass = nums[1] if len(nums) > 1 else ""
            row = {"stage": stage, "fkko": code, "name": name, "hazard_class": hazard,
                   "volume_m3": vol, "mass_t": mass, "density": ""}
            try:
                if vol and mass and float(vol) > 0:
                    row["density"] = f"{float(mass) / float(vol):.3f}"
            except ValueError:
                pass
            rows.append(row)
            i += 1
            continue
        if _STOP.match(ln):
            buf = []
        else:
            buf.append(ln)
        i += 1
    return rows, stage


def extract(doc) -> list[dict]:
    """Все строки таблиц отходов документа (ExtractedDoc: pages/text)."""
    pages = list(getattr(doc, "pages", None) or []) or [getattr(doc, "text", "") or ""]
    out: list[dict] = []
    stage = ""
    seen: set = set()
    for pno, text in enumerate(pages, start=1):
        if not text or ("ФККО" not in text
                        and not re.search(r"\d \d\d \d\d\d \d\d \d\d \d", text)):
            # стадия «живёт» только через соседние страницы таблицы
            if not re.search(r"Таблица", text or ""):
                stage = ""
            continue
        rows, stage = parse_page(text, stage)
        for r in rows:
            key = (r["stage"], r["fkko"])
            if key in seen:
                continue
            seen.add(key)
            r["page"] = pno
            out.append(r)
    return out


def is_project_doc(doc) -> bool:
    """Похож ли документ на ООС/ПНООЛР/инвентаризацию (по имени и тексту)."""
    name = str(getattr(doc, "path", "") or "").lower().replace("ё", "е")
    head = (getattr(doc, "text", "") or "")[:6000].lower()
    return bool(re.search(r"оос|пмоос|пноолр|инвентаризац|мероприятий по охране окружающей", name)
                or re.search(r"перечень мероприятий по охране окружающей среды|"
                             r"проект нормативов образования отходов|"
                             r"оценка воздействия на окружающую среду", head))
