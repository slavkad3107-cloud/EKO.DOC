"""Определение кода ОКТМО по адресу — БЕСПЛАТНО, без обязательного токена.

ОКТМО — обязательный реквизит места внесения платы за НВОС; чаще всего именно
его не хватает. Готового бесплатного API «ОКТМО по адресу» без ключа нет
(сервис ФНС — JS-страница, DaData — по токену), поэтому основной путь здесь —
ОФФЛАЙН: полный классификатор ОКТМО (ОК 033-2013, data/oktmo_full.json.gz,
173 тыс. муниципальных образований и населённых пунктов) плюс маленький
пользовательский справочник «ключевое слово адреса → ОКТМО»
(data/oktmo_ref.json, правится экологом, имеет приоритет). Порядок источников:

  1. пользовательский справочник по ключевым словам (data/oktmo_ref.json);
  2. полный классификатор: адрес → регион → район/округ → поселение /
     населённый пункт по совпадению названий (resolve());
  3. если оффлайн не уверен (в СПб/Москве адрес часто без округа: «СПб,
     Промышленная ул., 10») — бесплатный геокодер OSM Nominatim даёт округ /
     район, и снова ищем в классификаторе (resolve_online(); выключается
     ECODOC_OFFLINE=1, без сети просто пропускается);
  4. DaData — только если задан токен DADATA_TOKEN;
  5. иначе — OktmoError с коротким текстом и кандидатами в e.candidates
     (GUI даёт выбрать вручную).
"""
from __future__ import annotations

import gzip
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from ecodoc.core.refdata import DATA_DIR, oktmo_ref


class OktmoError(RuntimeError):
    pass


# ── регионы: префикс ОКТМО (= ОКАТО) → код субъекта РФ, название, регэкспы ──
# Префикс ОКТМО и код субъекта РФ — РАЗНЫЕ нумерации: 78 в ОКТМО — Ярославская
# область, а субъект 78 — Санкт-Петербург (ОКТМО 40). Код объекта НВОС
# начинается с префикса ОКТМО территориального органа, а справочники НМУ/ТО РПН
# ждут код субъекта — переводим здесь.
# Кортеж: (префикс, код субъекта, название, [регэкспы по адресу]).
# Регэксп прилагательного «ленинградск» срабатывает только вместе со словом
# «обл/область/край/респ…» в той же части адреса (см. _region_of), а города
# федерального значения и республики-существительные — сами по себе.
REGIONS: list[tuple[str, str, str, list[str]]] = [
    ("01", "22", "Алтайский край", [r"алтайск"]),
    ("02", "23", "Федеральная территория «Сириус»", [r"\bсириус\b"]),
    ("03", "23", "Краснодарский край", [r"краснодарск"]),
    ("04", "24", "Красноярский край", [r"красноярск"]),
    ("05", "25", "Приморский край", [r"приморск"]),
    ("07", "26", "Ставропольский край", [r"ставропольск"]),
    ("08", "27", "Хабаровский край", [r"хабаровск"]),
    ("10", "28", "Амурская область", [r"амурск"]),
    ("11", "29", "Архангельская область", [r"архангельск"]),
    ("12", "30", "Астраханская область", [r"астраханск"]),
    ("14", "31", "Белгородская область", [r"белгородск"]),
    ("15", "32", "Брянская область", [r"брянск"]),
    ("17", "33", "Владимирская область", [r"владимирск"]),
    ("18", "34", "Волгоградская область", [r"волгоградск"]),
    ("19", "35", "Вологодская область", [r"вологодск"]),
    ("20", "36", "Воронежская область", [r"воронежск"]),
    ("21", "93", "Донецкая Народная Республика", [r"донецк", r"\bднр\b"]),
    ("22", "52", "Нижегородская область", [r"нижегородск"]),
    ("23", "95", "Запорожская область", [r"запорожск"]),
    ("24", "37", "Ивановская область", [r"ивановск"]),
    ("25", "38", "Иркутская область", [r"иркутск"]),
    ("26", "06", "Республика Ингушетия", [r"ингушети", r"ингушск"]),
    ("27", "39", "Калининградская область", [r"калининградск"]),
    ("28", "69", "Тверская область", [r"тверск"]),
    ("29", "40", "Калужская область", [r"калужск"]),
    ("30", "41", "Камчатский край", [r"камчатск"]),
    ("32", "42", "Кемеровская область — Кузбасс", [r"кемеровск", r"кузбасс"]),
    ("33", "43", "Кировская область", [r"кировск.{0,3}обл"]),
    ("34", "44", "Костромская область", [r"костромск"]),
    ("35", "91", "Республика Крым", [r"\bкрым"]),
    ("36", "63", "Самарская область", [r"самарск"]),
    ("37", "45", "Курганская область", [r"курганск"]),
    ("38", "46", "Курская область", [r"курск"]),
    ("40", "78", "Санкт-Петербург", [r"санкт[\s\-]*петербург", r"с\.?[\s\-]*петербург",
                                     r"\bспб\b", r"\bпетербург"]),
    ("41", "47", "Ленинградская область", [r"ленинградск", r"\bло\b", r"ленобл", r"лен\.?\s*обл"]),
    ("42", "48", "Липецкая область", [r"липецк"]),
    ("43", "94", "Луганская Народная Республика", [r"луганск", r"\bлнр\b"]),
    ("44", "49", "Магаданская область", [r"магаданск"]),
    ("45", "77", "Москва", [r"\bмосква\b", r"\bг\.?\s*москв[аы]\b"]),
    ("46", "50", "Московская область", [r"московск", r"подмосков"]),
    ("47", "51", "Мурманская область", [r"мурманск"]),
    ("49", "53", "Новгородская область", [r"(?<!нижегород)новгородск", r"\bвеликий новгород"]),
    ("50", "54", "Новосибирская область", [r"новосибирск"]),
    ("52", "55", "Омская область", [r"\bомск"]),
    ("53", "56", "Оренбургская область", [r"оренбургск"]),
    ("54", "57", "Орловская область", [r"орловск"]),
    ("56", "58", "Пензенская область", [r"пензенск"]),
    ("57", "59", "Пермский край", [r"пермск"]),
    ("58", "60", "Псковская область", [r"псковск"]),
    ("60", "61", "Ростовская область", [r"ростовск"]),
    ("61", "62", "Рязанская область", [r"рязанск"]),
    ("63", "64", "Саратовская область", [r"саратовск"]),
    ("64", "65", "Сахалинская область", [r"сахалинск"]),
    ("65", "66", "Свердловская область", [r"свердловск"]),
    ("66", "67", "Смоленская область", [r"смоленск"]),
    ("67", "92", "Севастополь", [r"севастополь"]),
    ("68", "68", "Тамбовская область", [r"тамбовск"]),
    ("69", "70", "Томская область", [r"томск"]),
    ("70", "71", "Тульская область", [r"тульск"]),
    ("71", "72", "Тюменская область", [r"тюменск"]),
    ("73", "73", "Ульяновская область", [r"ульяновск"]),
    ("74", "96", "Херсонская область", [r"херсонск"]),
    ("75", "74", "Челябинская область", [r"челябинск"]),
    ("76", "75", "Забайкальский край", [r"забайкальск"]),
    ("77", "87", "Чукотский автономный округ", [r"чукот"]),
    ("78", "76", "Ярославская область", [r"ярославск"]),
    ("79", "01", "Республика Адыгея", [r"адыге"]),
    ("80", "02", "Республика Башкортостан", [r"башкортостан", r"башкир"]),
    ("81", "03", "Республика Бурятия", [r"буряти"]),
    ("82", "05", "Республика Дагестан", [r"дагестан"]),
    ("83", "07", "Кабардино-Балкарская Республика", [r"кабардино", r"\bкбр\b"]),
    ("84", "04", "Республика Алтай", [r"респ\w*\.?\s+алтай\b", r"\bалтай\b"]),
    ("85", "08", "Республика Калмыкия", [r"калмыки"]),
    ("86", "10", "Республика Карелия", [r"карели"]),
    ("87", "11", "Республика Коми", [r"\bкоми\b"]),
    ("88", "12", "Республика Марий Эл", [r"марий\s*эл"]),
    ("89", "13", "Республика Мордовия", [r"мордови"]),
    ("90", "15", "Республика Северная Осетия — Алания", [r"осети", r"алани"]),
    ("91", "09", "Карачаево-Черкесская Республика", [r"карачаево", r"\bкчр\b"]),
    ("92", "16", "Республика Татарстан", [r"татарстан"]),
    ("93", "17", "Республика Тыва", [r"\bтыва\b", r"\bтува\b"]),
    ("94", "18", "Удмуртская Республика", [r"удмурт"]),
    ("95", "19", "Республика Хакасия", [r"хакаси"]),
    ("96", "20", "Чеченская Республика", [r"чеченск", r"\bчечня\b"]),
    ("97", "21", "Чувашская Республика", [r"чуваш"]),
    ("98", "14", "Республика Саха (Якутия)", [r"якути", r"\bсаха\b"]),
    ("99", "79", "Еврейская автономная область", [r"еврейск"]),
    # автономные округа внутри «материнских» субъектов: свой блок кодов
    ("118", "83", "Ненецкий автономный округ", [r"(?<!ямало-)(?<!ямало )ненецк"]),
    ("718", "86", "Ханты-Мансийский автономный округ — Югра", [r"ханты", r"\bюгр[аы]\b"]),
    ("719", "89", "Ямало-Ненецкий автономный округ", [r"ямал"]),
]
# префикс ОКТМО → код субъекта, и обратно (у субъекта 23 два префикса: 03 и 02)
OKTMO_PREFIX_TO_SUBJECT: dict[str, str] = {p: s for p, s, _n, _r in REGIONS}
SUBJECT_TO_OKTMO_PREFIX: dict[str, str] = {}
for _p, _s, _n, _r in reversed(REGIONS):
    SUBJECT_TO_OKTMO_PREFIX[_s] = _p
REGION_NAME_BY_PREFIX: dict[str, str] = {p: n for p, s, n, _r in REGIONS}
REGION_NAME_BY_SUBJECT: dict[str, str] = {s: n for p, s, n, _r in REGIONS}
_REGION_WORD = re.compile(r"\b(обл\.?|область|области|край|края|респ\.?|республик\w*|"
                          r"а\.?о\.?|автономн\w*|округ\w*)\b|обл")
_REGION_RX = [(p, [re.compile(x) for x in rx]) for p, s, n, rx in REGIONS]
# сокращения, которые сами по себе называют регион («ЛО», «СПб», «Ленобласть»)
_ABBR_RX = {r"\bло\b", r"ленобл", r"лен\.?\s*обл", r"\bспб\b"}
# города федерального значения и республики-существительные узнаём без слова «область»
_STANDALONE = {"40", "45", "67", "02", "21", "43", "35", "26", "83", "84", "85", "86",
               "87", "88", "89", "90", "91", "92", "93", "94", "95", "96", "97", "98",
               "80", "81", "82", "79", "118", "718", "719", "77", "32"}


def subject_of_prefix(prefix: str) -> str:
    """Код субъекта РФ по префиксу ОКТМО/кода объекта НВОС («40» → «78»)."""
    p = str(prefix or "").strip()
    return OKTMO_PREFIX_TO_SUBJECT.get(p[:3]) or OKTMO_PREFIX_TO_SUBJECT.get(p[:2], "")


def prefix_of_oktmo(oktmo: str) -> str:
    """Префикс региона из ОКТМО с учётом автономных округов (118/718/719)."""
    s = re.sub(r"\D", "", str(oktmo or ""))
    if len(s) < 2:
        return ""
    if s[:3] in ("118", "718", "719"):
        return s[:3]
    return s[:2]


# ── полный классификатор ─────────────────────────────────────────────────────
_FULL: dict = {"mtime": None, "data": None, "by_region": None}


def full_path() -> Path:
    return DATA_DIR / "oktmo_full.json.gz"


def full_catalog() -> dict:
    """{'items': [[код, название, центр?], …], 'latest_change': …} или {}."""
    path = full_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _FULL["mtime"] != mtime:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            _FULL["data"] = json.load(f)
        _FULL["mtime"] = mtime
        by_region: dict[str, list] = {}
        for it in _FULL["data"].get("items", []):
            by_region.setdefault(prefix_of_oktmo(it[0]), []).append(it)
            # НАО/ХМАО/ЯНАО видны и в «материнском» регионе (адреса пишут по-разному)
            if it[0][:3] in ("118", "718", "719"):
                by_region.setdefault(it[0][:2], []).append(it)
        _FULL["by_region"] = by_region
    return _FULL["data"] or {}


def _items_of_region(prefix: str) -> list:
    full_catalog()
    return (_FULL["by_region"] or {}).get(prefix, [])


def level_of(code: str) -> str:
    s = re.sub(r"\D", "", str(code or ""))
    if len(s) == 11:
        return "locality"
    if len(s) != 8:
        return ""
    if s[2:] == "000000" or s in ("11800000", "71800000", "71900000"):
        return "region"
    if s[5:] == "000":
        return "district"
    if s[6:] == "00":
        # заголовки групп «Городские/Сельские поселения … района» (41612100,
        # 41612400) — не муниципальные образования
        return "group"
    return "settlement"


LEVEL_RU = {"region": "субъект РФ", "district": "район / округ",
            "settlement": "поселение", "locality": "населённый пункт"}


# ── нормализация названий ────────────────────────────────────────────────────
# типовые слова, которые не несут имени: в классификаторе («муниципальный округ
# Новоизмайловское», «город Петергоф», «гп Янино-1») и в адресах («г.», «р-н»,
# «пос.», «дер.»). Убираем их и сравниваем «ядро» названия.
_TYPE_WORDS = {
    "муниципальный", "муниципальное", "муниципальные", "округ", "округа",
    "городской", "городское", "городские", "сельский", "сельское", "сельсовет",
    "поселение", "поселения", "образование", "район", "районы", "р-н", "рн",
    "внутригородская", "внутригородской", "внутригородское", "территория",
    "тер", "город", "г", "гор", "поселок", "посёлок", "пос", "п", "пгт", "рп",
    "гп", "сп", "мо", "дер", "деревня", "д", "село", "с", "станица", "ст-ца",
    "хутор", "х", "аул", "слобода", "сл", "местечко", "м", "жд", "ж/д",
    "станции", "станция", "ст", "разъезд", "рзд", "кп", "снт", "тер.", "нп",
    "городского", "типа", "федерального", "значения", "области", "край",
    "республики", "автономного", "автономный", "территории", "промзона",
    "промышленная", "зона", "квартал",
}
# части адреса, которые точно про улицу/дом, а не про населённый пункт
_STREET_RX = re.compile(
    r"\b(ул|улица|пр-кт|пр-т|просп|проспект|пер|переулок|наб|набережная|ш|шоссе|"
    r"б-р|бульвар|пл|площадь|проезд|пр-д|туп|тупик|линия|аллея|дом|д|стр|строение|"
    r"корп|к|лит|литера|оф|офис|кв|пом|помещение|участок|уч|зу|владение|вл|"
    r"кад|кадастровый|км|этаж)\b\.?\s*\d|"
    r"\b(ул|улица|пр-кт|пр-т|просп|проспект|пер|переулок|наб|набережная|шоссе|"
    r"б-р|бульвар|площадь|проезд|пр-д|тупик|линия|аллея|участок|владение|"
    r"кадастровый|земельный)\b|"
    # «Колтушское ш.», «Московское ш», «ш. Революции» — сокращение в конце/начале части
    r"\b(ш|пл|пр|туп|наб|пер|б-р)\.?\s*$|^\s*(ш|пл|пр|туп|наб|пер|б-р)\.?\s", re.I)


def _norm(s: str) -> str:
    s = str(s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'`]", " ", s)
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"[^\w\s\-/]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _core(name: str) -> str:
    """«муниципальный округ Новоизмайловское» → «новоизмайловское»,
    «г. Петергоф» → «петергоф», «Всеволожский р-н» → «всеволожский»."""
    toks = [t.strip(".") for t in _norm(name).replace(".", ". ").split()]
    keep = [t for t in toks if t and t not in _TYPE_WORDS]
    return " ".join(keep)


def _split_address(address: str) -> list[str]:
    """Части адреса без индекса, улиц и домов: то, что может быть регионом,
    районом, поселением или населённым пунктом."""
    text = re.sub(r"\b\d{6}\b", " ", str(address or ""))
    text = re.sub(r"(?i)\b(россия|российская федерация|рф)\b", " ", text)
    text = re.sub(r"(?i)^.*?по адресу\s*:?", " ", text)   # «Проектирование … по адресу: …»
    parts = []
    for raw in re.split(r"[,;]", text):
        p = raw.strip(" .")
        if not p:
            continue
        if _STREET_RX.search(p):
            continue
        # части с числами (дом, литера, офис) — не населённые пункты,
        # кроме «Янино-1»/«Заречье-2»
        if re.search(r"\d", p) and not re.search(r"(?i)[а-я]{3,}-\d", p):
            continue
        parts.append(p)
    if not parts and "," not in text and ";" not in text:
        # адрес одной строкой без запятых («ЛО Всеволожский р-н Заневское п.
        # Промзона Янино Промышленный пр. 10»): отрезаем улицу/дом, остальное —
        # набор слов, по которым ищем поселение/НП
        cut = re.split(r"(?i)\b(ул|улица|пр-кт|пр-т|просп|проспект|пер|переулок|наб|"
                       r"шоссе|ш|б-р|бульвар|пл|площадь|проезд|туп|тупик|линия|аллея|"
                       r"участок|дом|стр|корп|лит|оф|кв)\b", text)[0]
        cut = re.sub(r"\d+", " ", cut).strip(" .")
        if cut:
            parts.append(cut)
    return parts


def _region_of(address: str) -> list[str]:
    """Префиксы регионов, найденные в адресе (обычно один)."""
    found: list[str] = []
    low = _norm(address)
    parts = re.split(r"[,;]", low)
    for prefix, rxs in _REGION_RX:
        for rx in rxs:
            if not rx.search(low):
                continue
            ok = prefix in _STANDALONE or rx.pattern in _ABBR_RX
            if not ok:
                # прилагательное «…ская» должно стоять при слове «область/край/респ»
                # в той же части адреса, иначе «Ленинградский пр.» в Москве даст ЛО
                ok = any(rx.search(p) and _REGION_WORD.search(p) for p in parts)
            if not ok:
                # адрес без слова «область»: «Ленинградская, Всеволожский р-н»
                for p in parts:
                    core = _core(p)
                    if rx.search(p) and len(core.split()) == 1 and core.endswith("ая"):
                        ok = True
                        break
            if ok:
                found.append(prefix)
                break
    out = []
    for p in found:
        if p not in out:
            out.append(p)
    # «Москва» и «Московская область» вместе: столица только если она названа
    # как город; иначе область
    if "45" in out and "46" in out and not re.search(r"\bг\.?\s*москва\b", low):
        out.remove("45")
    if "45" in out and "46" in out:
        out.remove("46")
    return out


def _guess_region_by_name(parts: list[str]) -> list[str]:
    """Региона в адресе нет — ищем район/город, уникальный по всей стране."""
    cores = {_core(p) for p in parts}
    cores.discard("")
    if not cores:
        return []
    hits: set[str] = set()
    for it in full_catalog().get("items", []):
        lvl = level_of(it[0])
        if lvl in ("region", "group", ""):
            continue
        # деревень-тёзок по стране много — их не считаем, только районы и города
        if lvl == "locality" and not re.match(r"(?i)^(г|город)\s", it[1]):
            continue
        if _core(it[1]) in cores:
            hits.add(prefix_of_oktmo(it[0]))
    return sorted(hits)


_ADJ_END = re.compile(r"(ский|ская|ское|ского|ской|ском|ских|инский|инская|ый|ий|ая|"
                      r"ое|ого|ой|ом|ых|их|ск|ин|ина|ино|а|я|о|е|ы|и|ь|й)$")


def _stem(s: str) -> str:
    """«истринский» → «истр», «истра» → «истр», «всеволожск» → «всеволож»."""
    prev = None
    while prev != s and len(s) > 4:
        prev = s
        s = _ADJ_END.sub("", s)
    return s


def _match_score(item_core: str, part_cores: list[str], words: set[str],
                 stems: bool = False) -> float:
    """Насколько название из классификатора совпало с частями адреса."""
    if not item_core:
        return 0.0
    best = 0.0
    for pc in part_cores:
        if not pc:
            continue
        if pc == item_core:
            return 1.0
        # «янино» ↔ «янино-1», «всеволожск» ↔ «всеволожский»
        a, b = pc, item_core
        if len(a) >= 5 and len(b) >= 5 and (a.startswith(b) or b.startswith(a)):
            best = max(best, 0.85 if abs(len(a) - len(b)) <= 3 else 0.7)
        elif stems and " " not in a and " " not in b:
            sa, sb = _stem(a), _stem(b)
            if len(sa) >= 4 and len(sb) >= 4 and (sa == sb or sa.startswith(sb)
                                                  or sb.startswith(sa)):
                best = max(best, 0.7)
    if best == 0.0 and item_core in words and len(item_core) >= 4:
        best = 0.8                       # отдельное слово адреса = имя целиком
    if best == 0.0 and " " in item_core:
        toks = [t for t in item_core.split() if len(t) >= 4]
        if toks and all(t in words for t in toks):
            best = 0.75
    return best


def _result(prefix: str, **kw) -> dict:
    out = {"oktmo": "", "value": "", "level": "", "level_code": "", "confidence": 0.0,
           "candidates": [], "region": prefix,
           "region_name": REGION_NAME_BY_PREFIX.get(prefix, ""),
           "subject": OKTMO_PREFIX_TO_SUBJECT.get(prefix, ""),
           "source": "oktmo_full", "note": "", "oktmo11": ""}
    out.update(kw)
    return out


def resolve(address: str, limit: int = 5) -> dict:
    """Адрес → {oktmo, value, level, confidence, candidates[:limit], region…}.

    Никогда не бросает исключений: если ничего не нашли — oktmo пустой,
    confidence 0 и пояснение в 'note'. Уверенность: ≥0.9 — единственное точное
    совпадение поселения/НП внутри найденного района; ≥0.8 — точное совпадение
    без района; ≤0.6 — только район (у которого есть поселения) или регион."""
    address = str(address or "").strip()
    if not address:
        return _result("", note="адрес пустой")
    if not full_catalog():
        return _result("", note="полный классификатор ОКТМО (data/oktmo_full.json.gz) не найден")
    parts = _split_address(address)
    regions = _region_of(address)
    note = ""
    if not regions:
        regions = _guess_region_by_name(parts)
        if len(regions) > 1:
            note = ("регион в адресе не указан, а район/город встречается в "
                    "нескольких субъектах: " + ", ".join(
                        REGION_NAME_BY_PREFIX.get(r, r) for r in regions))
            regions = []
    if not regions:
        return _result("", note=note or ("регион (субъект РФ) в адресе не распознан — "
                                         "допишите область/республику/город"))
    prefix = regions[0]
    region_name = REGION_NAME_BY_PREFIX.get(prefix, "")

    # части адреса, которые оказались самим регионом, дальше не нужны
    rxs = dict(_REGION_RX)[prefix]
    rcore = _core(region_name)
    part_cores = []
    for p in parts:
        c = _core(p)
        if not c or c == rcore:
            continue
        low = _norm(p)
        if any(rx.search(low) for rx in rxs) and (
                _REGION_WORD.search(low) or prefix in _STANDALONE
                or (len(c.split()) == 1 and c.endswith("ая"))):
            continue
        part_cores.append(c)
    words = {w for c in part_cores for w in c.split() if len(w) >= 4}

    items = _items_of_region(prefix)
    federal_city = prefix in ("40", "45", "67")
    # 1) районы/округа: насколько каждый упомянут в адресе
    dscore: dict[str, float] = {}
    has_children: set[str] = set()
    for it in items:
        lvl = level_of(it[0])
        if lvl == "settlement":
            has_children.add(it[0][:5])
        if lvl != "district" or federal_city:
            continue
        sc = _match_score(_core(it[1]), part_cores, words, stems=True)
        if len(it) > 2:
            sc = max(sc, _match_score(_core(it[2]), part_cores, words) * 0.9)
        if sc > 0:
            dscore[it[0][:5]] = max(dscore.get(it[0][:5], 0), sc)
    hard = [d for d, s in dscore.items() if s >= 0.85]
    # часть адреса, которая назвала район, поселения не ищет
    if len(hard) == 1:
        d_item = _find_item(hard[0] + "000")
        consumed = {_core(d_item[1])} if d_item else set()
        part_cores = [c for c in part_cores if c not in consumed]

    # 2) поселения / населённые пункты / округа без поселений
    scored: list[tuple[float, list]] = []
    for it in items:
        lvl = level_of(it[0])
        if lvl in ("region", "group", ""):
            continue
        if lvl == "district" and not federal_city and it[0][:5] in has_children:
            # район с поселениями: сам по себе не место платы, только подсказка
            sc = dscore.get(it[0][:5], 0)
            if sc > 0:
                scored.append((sc * 0.6, it))
            continue
        sc = _match_score(_core(it[1]), part_cores, words)
        if sc <= 0 and len(it) > 2:
            sc = _match_score(_core(it[2]), part_cores, words) * 0.9
        if sc > 0:
            scored.append((sc, it))
    if not scored:
        code = prefix + "000000" if len(prefix) == 2 else prefix + "00000"
        return _result(prefix, oktmo=code, value=region_name, level=LEVEL_RU["region"],
                       level_code="region", confidence=0.3,
                       note="в адресе распознан только регион — район/поселение "
                            "не найдены, уточните адрес или выберите ОКТМО вручную")

    # 3) район сужает: при одном точном районе оставляем его кандидатов; при
    # «похожем» районе (Истринский → округ Истра) — бонус его кандидатам
    if len(hard) == 1:
        inside = [(s, it) for s, it in scored if it[0][:5] == hard[0]]
        if any(level_of(it[0]) != "district" for _s, it in inside):
            scored = inside
    soft = {d for d, s in dscore.items() if s >= 0.6}
    if soft and any(it[0][:5] in soft for _s, it in scored) \
            and any(it[0][:5] not in soft for _s, it in scored):
        scored = [(s, it) for s, it in scored if it[0][:5] in soft]

    # 4) свёртка до 8-значного МО: НП даёт ОКТМО своего поселения/округа
    best: dict[str, dict] = {}
    for sc, it in scored:
        lvl = level_of(it[0])
        code8 = it[0][:8]
        score = sc
        if lvl != "district" and (it[0][:5] in soft or it[0][:5] in hard):
            score = min(1.0, score + 0.1)
        cand = best.get(code8)
        if not cand or score > cand["confidence"]:
            lvl_out = "settlement" if lvl == "locality" else lvl
            if lvl == "district" and (federal_city or code8[:5] not in has_children):
                lvl_out = "district_final"
            best[code8] = {"oktmo": code8, "value": _label_for(prefix, it, code8),
                           "level": {"district_final": "муниципальный / городской округ",
                                     "district": LEVEL_RU["district"],
                                     "settlement": LEVEL_RU["settlement"]}[lvl_out],
                           "level_code": lvl_out, "confidence": round(score, 2),
                           "oktmo11": it[0] if lvl == "locality" else "",
                           "matched": it[1]}
    cands = sorted(best.values(), key=lambda c: (-c["confidence"], c["oktmo"]))
    top = cands[0]
    conf = top["confidence"]
    note = ""
    if len(cands) > 1 and cands[1]["confidence"] >= conf - 0.05:
        conf = min(conf, 0.55)
        note = "несколько подходящих муниципальных образований — выберите из списка"
    if top["level_code"] == "district":
        conf = min(conf, 0.6)
        note = ("найден только район — поселение или населённый пункт в адресе "
                "не распознаны; ОКТМО района для платы обычно не используется")
    return _result(prefix, oktmo=top["oktmo"], value=top["value"], level=top["level"],
                   level_code=top["level_code"], confidence=round(conf, 2),
                   candidates=cands[:limit], oktmo11=top.get("oktmo11", ""), note=note)


def _label_for(prefix: str, it: list, code8: str) -> str:
    """Подпись кандидата: регион, район, поселение/НП."""
    names = [REGION_NAME_BY_PREFIX.get(prefix, "")]
    lvl = level_of(it[0])
    if lvl in ("settlement", "locality"):
        d = _find_item(it[0][:5] + "000")
        if d and d[1] and d[0] != code8:
            names.append(d[1])
        if lvl == "locality":
            s = _find_item(code8)
            if s and s[1] and s[1] != it[1]:
                names.append(s[1])
    names.append(it[1])
    return ", ".join(n for n in names if n)


def _find_item(code: str) -> list | None:
    for it in _items_of_region(prefix_of_oktmo(code)):
        if it[0] == code:
            return it
    return None

# ── OSM Nominatim: улица → муниципальный округ (бесплатно, без ключа) ────────
# В городах федерального значения адрес обычно «СПб, Промышленная ул., 10» —
# без муниципального округа, а ОКТМО там именно у округа (40339000 Нарвский
# округ). Классификатор улиц не знает; открытый геокодер OpenStreetMap знает и
# возвращает city_district/suburb — по нему снова ищем в классификаторе.
# Отключается ECODOC_OFFLINE=1; при отсутствии сети просто пропускается.
_OSM_URL = "https://nominatim.openstreetmap.org/search"
_OSM_UA = {"User-Agent": "EKO.DOC (ecology reporting; github.com/slavkad3107-cloud)"}


def _osm_query(address: str, timeout: float) -> list[dict]:
    """Сырые ответы Nominatim (список), [] при любой ошибке сети."""
    if os.environ.get("ECODOC_OFFLINE"):
        return []
    import urllib.parse
    q = urllib.parse.urlencode({"q": address, "format": "jsonv2", "addressdetails": 1,
                                "limit": 4, "accept-language": "ru", "countrycodes": "ru"})
    req = urllib.request.Request(f"{_OSM_URL}?{q}", headers=_OSM_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


_OSM_ABBR = [(r"\bпр-кт\b\.?|\bпр-т\b\.?|\bпросп\b\.?|\bпр\b\.", "проспект"),
             (r"\bул\b\.?", "улица"), (r"\bпер\b\.?", "переулок"), (r"\bнаб\b\.?", "набережная"),
             (r"\bш\b\.", "шоссе"), (r"\bб-р\b\.?", "бульвар"), (r"\bпл\b\.", "площадь"),
             (r"\bпр-д\b\.?", "проезд"), (r"\bд\b\.\s*(?=\d)", ""), (r"\bлит\b\.?\s*[а-яa-z]\b", ""),
             (r"\bоф\b\.?\s*\d+", ""), (r"\bпом\b\.?\s*\w+", ""), (r"\bкорп\b\.?\s*\d+", "к\\g<0>")]


def _for_osm(address: str) -> str:
    """Адрес в виде, который лучше понимает Nominatim: без индекса и офиса,
    с раскрытыми «пр.», «ул.», «ш.» (он не знает наших сокращений)."""
    s = re.sub(r"\b\d{6}\b", " ", str(address or ""))
    s = re.sub(r"(?i)^.*?по адресу\s*:?", " ", s)
    for rx, rep in _OSM_ABBR:
        s = re.sub(rx, rep, s, flags=re.I)
    s = re.sub(r"\bк\s*корп\b\.?", "к", s, flags=re.I)
    s = re.sub(r"\s*,\s*", ", ", s)
    return re.sub(r"\s+", " ", s).strip(" ,")


def _osm_addresses(address: str, timeout: float = 6) -> list[str]:
    """Адрес → варианты «регион, район, поселение/НП» по данным OSM
    (без улицы и дома), в порядке выдачи геокодера, без дублей."""
    out: list[str] = []
    prepared = _for_osm(address)
    hits = _osm_query(prepared, timeout)
    if not hits:
        # «Кировский район» внутри города геокодер не понимает — без него
        shorter = ", ".join(p for p in prepared.split(", ")
                            if not re.search(r"(?i)\bрайон\b|\bр-н\b", p))
        if shorter and shorter != prepared:
            hits = _osm_query(shorter, timeout)
    if not hits and prepared != address.strip():
        hits = _osm_query(address, timeout)
    for hit in hits:
        a = hit.get("address") or {}
        parts = []
        for key in ("state", "county", "municipality", "city", "town", "city_district",
                    "suburb", "village", "hamlet"):
            v = str(a.get(key) or "").strip()
            if v and v not in parts and not re.search(r"федеральный округ", v, re.I):
                parts.append(v)
        s = ", ".join(parts)
        if s and s not in out:
            out.append(s)
    return out


def resolve_online(address: str, timeout: float = 6) -> dict:
    """Уточнить адрес через OSM и найти ОКТМО в классификаторе. Как resolve():
    не бросает исключений; source = 'osm+oktmo_full'."""
    variants = _osm_addresses(address, timeout)
    if not variants:
        return _result("", source="osm", note="геокодер OSM не дал ответа")
    best: dict = {}
    cands: list[dict] = []
    for i, v in enumerate(variants):
        r = resolve(v)
        if not r.get("oktmo") or r.get("level_code") == "region":
            continue
        # геокодер выдаёт варианты по убыванию значимости: у первого
        # (Промышленная ул. в Нарвском округе) приоритет перед тёзкой в
        # Красном Селе — вторые и далее получают штраф
        penalty = round(0.1 * i, 2)
        r["confidence"] = round(max(0.0, r["confidence"] - penalty), 2)
        for c in r.get("candidates") or []:
            c = dict(c)
            c["confidence"] = round(max(0.0, c["confidence"] - penalty), 2)
            if all(c["oktmo"] != x["oktmo"] for x in cands):
                cands.append(c)
        if not best or r["confidence"] > best["confidence"]:
            best = r
            best["osm_address"] = v
    if not best:
        return _result("", source="osm", note="по данным OSM муниципальное образование "
                                             "в классификаторе не найдено",
                       candidates=cands[:5])
    best["source"] = "osm+oktmo_full"
    best["candidates"] = sorted(cands, key=lambda c: -c["confidence"])[:5]
    if len(best["candidates"]) > 1 and best["candidates"][1]["confidence"] >= best["confidence"] - 0.05:
        best["confidence"] = min(best["confidence"], 0.55)
        best["note"] = "геокодер нашёл несколько мест по этому адресу — выберите из списка"
    return best


def _as_hit(res: dict) -> dict:
    return {"oktmo": res["oktmo"], "okato": "", "fias": "", "value": res["value"],
            "source": res.get("source", "oktmo_full"), "level": res["level"],
            "confidence": res["confidence"], "candidates": res.get("candidates", []),
            "note": res.get("note", "")}


def by_address(address: str, timeout: int = 15) -> dict:
    """Вернуть {'oktmo', 'okato', 'fias', 'value', 'source', 'level',
    'confidence', 'candidates'} по адресу.

    Порядок: пользовательский справочник ключевых слов → полный классификатор
    → (если не уверен) геокодер OSM + классификатор → DaData при токене.
    Иначе — OktmoError с коротким текстом; кандидаты — в e.candidates."""
    hit = _lookup_offline(address)
    if hit:
        return hit
    res = resolve(address)
    if res.get("oktmo") and res.get("confidence", 0) >= 0.8:
        return _as_hit(res)
    online = resolve_online(address, timeout=min(timeout, 8))
    if online.get("oktmo") and online.get("confidence", 0) >= 0.8:
        return _as_hit(online)
    # кандидаты: оффлайн + OSM, без дублей
    cands = list(res.get("candidates") or [])
    for c in online.get("candidates") or []:
        if all(c["oktmo"] != x["oktmo"] for x in cands):
            cands.append(c)
    cands.sort(key=lambda c: -c.get("confidence", 0))
    token = os.environ.get("DADATA_TOKEN", "")
    if token:
        try:
            d = _dadata(address, token, timeout)
            d["candidates"] = cands[:5]
            return d
        except OktmoError:
            if not cands:
                raise
    if cands:
        err = OktmoError("ОКТМО по адресу определён неоднозначно — выберите из списка")
        err.candidates = cands[:5]
        raise err
    err = OktmoError("ОКТМО по адресу не найден: "
                     + (res.get("note") or "нет совпадений в классификаторе"))
    err.candidates = []
    raise err


def _lookup_offline(address: str) -> dict | None:
    """Найти ОКТМО по вхождению ключевого слова пользовательского справочника."""
    if not address:
        return None
    text = address.lower()
    ref = oktmo_ref()
    # сначала самые длинные ключи (специфичнее), чтобы «истринский» не перебивал
    for key in sorted(ref, key=len, reverse=True):
        if key.lower() in text:
            e = ref[key]
            return {"oktmo": e.get("oktmo", ""), "okato": e.get("okato", ""),
                    "fias": "", "value": e.get("value", address),
                    "source": "offline", "level": level_of(e.get("oktmo", "")),
                    "confidence": 1.0, "candidates": []}
    return None


def _dadata(address: str, token: str, timeout: int) -> dict:
    req = urllib.request.Request(
        "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address",
        data=json.dumps({"query": address, "count": 1}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": f"Token {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise OktmoError("DaData отклонил токен (проверьте DADATA_TOKEN "
                             "или суточный лимит).")
        raise OktmoError(f"DaData: HTTP {e.code}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise OktmoError(f"DaData недоступен: {e}")
    suggestions = out.get("suggestions") or []
    if not suggestions:
        raise OktmoError(f"адрес не распознан: {address}")
    d = suggestions[0].get("data") or {}
    if not d.get("oktmo"):
        raise OktmoError("ОКТМО для этого адреса не определён — уточните адрес.")
    return {"oktmo": d.get("oktmo", ""), "okato": d.get("okato", ""),
            "fias": d.get("fias_id", ""), "value": suggestions[0].get("value", ""),
            "source": "dadata", "level": level_of(d.get("oktmo", "")),
            "confidence": 1.0, "candidates": []}
