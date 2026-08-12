"""Каталог ФККО: проверка кодов отходов по действующему классификатору.

Требование ТЗ: «нужно проверить данные по ФККО, взятые из ДАННЫХ, по
действующему ФККО по внешним официальным источникам автоматом».

Как устроено:
  * оффлайн-справочник `data/fkko.json` — то, с чем сверяемся всегда;
  * обновление — командой/кнопкой: качаем открытые данные ФККО (Росприроднадзор
    публикует каталог; ссылки настраиваются в `SOURCES`), разбираем и
    перезаписываем справочник;
  * если каталога нет или кода в нём нет — не выдумываем: говорим «в каталоге
    не найден», а формат проверяем структурно (11 цифр, класс 1–5).

Структура файла:
    {"updated": "2026-07-31", "source": "…", "codes":
        {"47110101521": {"name": "…", "class": 1}, …}}
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

BUILTIN_FILE = Path(__file__).resolve().parents[1] / "data" / "fkko.json"


def user_file() -> Path:
    """Куда пишется каталог, загруженный пользователем.

    В общую базу, а не в папку программы: базой пользуются все компьютеры, и
    при переходе на новую версию каталог не теряется вместе со старой папкой.
    Путь берётся функцией (не константой), иначе тесты писали бы в живую базу."""
    import os
    env = os.environ.get("ECODOC_FKKO", "")
    if env:
        return Path(env)
    from ecodoc.core import workspace
    return workspace.root() / "справочники" / "fkko.json"


def data_file() -> Path:
    """Действующий файл каталога — более СВЕЖИЙ из двух.

    Пользовательский каталог лежит в общей базе и живёт дольше программы;
    встроенный обновляется с новой версией. Если в поставку пришёл каталог
    новее того, что в базе, работать надо по нему — иначе обновление
    программы не доносило бы до пользователя новые коды ФККО."""
    u = user_file()
    if not u.exists():
        return BUILTIN_FILE
    if not BUILTIN_FILE.exists():
        return u
    return u if _stamp_of(u) >= _stamp_of(BUILTIN_FILE) else BUILTIN_FILE


def _stamp_of(path: Path) -> str:
    """Дата снимка каталога («updated») — по ней сравниваем свежесть."""
    try:
        head = path.read_text(encoding="utf-8-sig")[:200]
        m = re.search(r'"updated"\s*:\s*"([^"]*)"', head)
        return m.group(1) if m else ""
    except OSError:
        return ""

# Каталог берём с сайта Росприроднадзора: открытых данных (xlsx/csv/json) он не
# публикует, но каталог отдаётся постранично — это единственный машиночитаемый
# путь получить действующую редакцию целиком.
RPN_PAGE = "https://rpn.gov.ru/fkko/"
RPN_MORE = "https://rpn.gov.ru/fkko/nav-more-fkko/page-{n}/"
SOURCES = [RPN_PAGE]

# Действующая редакция — для реквизитов в документах и проверки свежести файла.
CURRENT_EDITION = ("приказ Росприроднадзора от 22.05.2017 № 242 "
                   "(в ред. приказа от 08.06.2026 № 341)")
# Коды, введённые последними приказами: если их нет — каталог устарел.
FRESH_MARKERS = ("31211471201",   # приказ № 723 от 20.12.2024
                 "22241112205",   # приказ № 341 от 08.06.2026
                 "31313411313")   # приказ № 341 от 08.06.2026

_CACHE: dict = {}


@dataclass
class Check:
    code: str                 # нормализованный код (11 цифр)
    ok: bool                  # код годен (структура верна и каталог не против)
    verified: bool = False    # подтверждён действующим каталогом
    name: str = ""            # наименование по каталогу
    hazard: int = 0           # класс опасности по каталогу
    problem: str = ""         # что не так, если не ok
    note: str = ""            # пояснение, когда проверить нечем
    name_mismatch: str = ""   # наше наименование разошлось с каталогом


def catalog() -> dict:
    """Каталог из файла (кэш по пути и времени изменения)."""
    path = data_file()
    if not path.exists():
        return {}
    key = (str(path), path.stat().st_mtime)
    if _CACHE.get("key") != key:
        try:
            _CACHE["data"] = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            _CACHE["data"] = {}
        _CACHE["key"] = key
    return _CACHE.get("data") or {}


def codes() -> dict:
    return catalog().get("codes") or {}


def updated() -> str:
    return catalog().get("updated", "")


def norm(code) -> str:
    return re.sub(r"\D", "", str(code or ""))


def structure_problem(code: str) -> str:
    """Структурная проверка кода — работает и без каталога."""
    d = norm(code)
    if not d:
        return "код ФККО не заполнен"
    if len(d) != 11:
        return f"в коде ФККО должно быть 11 цифр, а здесь {len(d)}"
    if d[0] == "0":
        return "код ФККО не может начинаться с нуля"
    if d[-1] not in "12345":
        return ("последняя цифра — класс опасности (1–5); «0» бывает только у "
                "групповых заголовков каталога, в отчётность они не идут")
    return ""


def check(code, name: str = "") -> Check:
    """Проверить код по действующему каталогу (и наименование, если задано)."""
    d = norm(code)
    problem = structure_problem(d)
    if problem:
        return Check(code=d, ok=False, problem=problem)
    cat = codes()
    if not cat:
        # каталога нет — код не виноват: структура верна, сверить просто нечем
        return Check(code=d, ok=True, verified=False,
                     note="каталог ФККО не загружен — нажмите «Обновить каталог ФККО»")
    rec = cat.get(d)
    if not rec:
        if catalog().get("partial"):
            # частичный каталог: отсутствие кода ещё ничего не доказывает
            return Check(code=d, ok=True, verified=False,
                         note="кода нет в загруженном (частичном) каталоге — "
                              "загрузите полный ФККО, чтобы проверить")
        # каталог — снимок на дату: код, внесённый в ФККО позже, здесь не
        # найдётся, поэтому дату называем и подсказываем обновление
        when = catalog().get("updated", "")
        return Check(code=d, ok=False, verified=False,
                     problem="кода нет в каталоге ФККО"
                             + (f" (снимок от {when})" if when else "")
                             + " — проверьте код; если он новый, обновите "
                               "каталог кнопкой «Обновить каталог ФККО»")
    chk = Check(code=d, ok=True, verified=True, name=rec.get("name", ""),
                hazard=int(rec.get("class") or 0))
    if name and chk.name:
        ours = re.sub(r"\s+", " ", name).strip().lower().replace("ё", "е")
        theirs = re.sub(r"\s+", " ", chk.name).strip().lower().replace("ё", "е")
        if ours and theirs and ours[:40] != theirs[:40]:
            chk.name_mismatch = chk.name
    return chk


def _words(text: str) -> set:
    s = str(text or "").lower().replace("ё", "е")
    s = re.sub(r"\([^)]*\)", " ", s)
    return {w for w in re.findall(r"[а-яa-z0-9]+", s) if len(w) > 3}


def suggest_by_name(name: str, limit: int = 3) -> list[dict]:
    """Подобрать код ФККО по наименованию отхода.

    Когда код из документа не найден в каталоге, чаще всего наименование
    написано верно — по нему и ищем. Возвращаем несколько вариантов с мерой
    совпадения: выбирает всё равно пользователь, программа не подставляет
    код молча."""
    target = _words(name)
    if not target:
        return []
    out = []
    for code, rec in codes().items():
        if code[-1] == "0":                 # групповые заголовки не предлагаем
            continue
        cand = _words(rec.get("name", ""))
        if not cand:
            continue
        common = target & cand
        if not common:
            continue
        score = len(common) / max(len(target | cand), 1)
        out.append({"code": code, "name": rec.get("name", ""),
                    "class": rec.get("class", 0), "score": round(score, 3)})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def check_context(ctx) -> list[dict]:
    """Проверить все отходы объекта: движение и справки-акты."""
    seen, out = set(), []
    for w in list(ctx.wastes) + list(ctx.waste_acts):
        code = norm(getattr(w, "fkko_code", ""))
        if not code or code in seen:
            continue
        seen.add(code)
        c = check(code, getattr(w, "name", ""))
        row = {"code": code, "ok": c.ok, "verified": c.verified,
               "problem": c.problem, "note": c.note,
               "catalog_name": c.name, "our_name": getattr(w, "name", ""),
               "name_mismatch": c.name_mismatch,
               "catalog_class": c.hazard,
               "our_class": int(getattr(w, "hazard_class", 0) or 0)}
        row["class_mismatch"] = bool(c.ok and c.hazard
                                     and row["our_class"]
                                     and c.hazard != row["our_class"])
        out.append(row)
    return out


def save(records: dict, source: str = "", partial: bool = False,
         stamp: str = "", origin: str = "manual") -> Path:
    """Записать каталог (код → {name, class}).

    partial=True — набор заведомо неполный (встроенный минимум или выборка):
    тогда отсутствие кода не считается ошибкой.
    stamp — отпечаток файла-источника, чтобы не перечитывать его каждый запуск.
    origin — «forms» (подхвачен автоматически из папки «Формы») или «manual»
    (пользователь загрузил файл/скачал сам). Автосинхронизация ручной каталог
    не трогает: явное действие пользователя автоматика отменять не должна."""
    path = user_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated": date.today().isoformat(), "source": source,
               "partial": bool(partial), "stamp": stamp, "origin": origin,
               "codes": records}
    # временный файл уникален на процесс: сохранение может идти одновременно
    # из фонового потока запуска и из обработчика кнопки
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    _CACHE.clear()
    return path


def parse(text: str) -> dict:
    """Разобрать каталог из открытых данных: JSON-массив либо текст/CSV.

    Форматы публикации меняются, поэтому берём общее: пары «11-значный код +
    наименование» в любой структуре."""
    records: dict = {}
    text = (text or "").strip()
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        rows = data if isinstance(data, list) else (
            data.get("codes") or data.get("data") or [] if isinstance(data, dict) else [])
        if isinstance(rows, dict):                    # уже готовый {код: {...}}
            for code, rec in rows.items():
                d = norm(code)
                if len(d) == 11:
                    records[d] = {"name": (rec or {}).get("name", "") if isinstance(rec, dict) else str(rec),
                                  "class": int(d[-1]) if d[-1].isdigit() else 0}
            return records
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            code = norm(row.get("code") or row.get("fkko") or row.get("КОД") or "")
            name = (row.get("name") or row.get("наименование")
                    or row.get("НАИМЕНОВАНИЕ") or "")
            if len(code) == 11:
                records[code] = {"name": str(name).strip(),
                                 "class": int(code[-1]) if code[-1].isdigit() else 0}
        if records:
            return records
    # текст/CSV/HTML: «4 71 101 01 52 1  Лампы ртутные…»
    for m in re.finditer(r"(\d[\d\s]{9,15}\d)[\s|;,\t]+([^\n\r|;]{5,300})", text):
        code = norm(m.group(1))
        if len(code) != 11:
            continue
        name = re.sub(r"\s+", " ", m.group(2)).strip(" ;|,\t")
        records.setdefault(code, {"name": name,
                                  "class": int(code[-1]) if code[-1].isdigit() else 0})
    return records


_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}


def _hazard_from(value, code: str) -> int:
    """Класс опасности: римская цифра из каталога, иначе последняя цифра кода."""
    s = str(value or "").strip().upper().replace("КЛАСС", "").strip(" .")
    if s in _ROMAN:
        return _ROMAN[s]
    if s in ("1", "2", "3", "4", "5"):     # именно одна цифра, не подстрока
        return int(s)
    return int(code[-1]) if code and code[-1] in "12345" else 0


def _code_from(value) -> str:
    """Код ФККО из ячейки: числа приходят как 11101011495.0."""
    s = str(value or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return re.sub(r"\D", "", s)


def parse_table(path: Path) -> dict:
    """Каталог из таблицы Excel: колонки «Код», «Наименование», «Класс опасности».

    Читаем ячейки напрямую, а не текстовое представление: в выгрузках ФККО
    коды хранятся числами (11101011495.0), а класс — римскими цифрами, и по
    тексту это разбирается ненадёжно."""
    rows: list[list] = []
    suffix = path.suffix.lower()
    if suffix == ".xls":
        import xlrd
        book = xlrd.open_workbook(str(path))
        for sh in book.sheets():
            rows += [[sh.cell_value(r, c) for c in range(sh.ncols)]
                     for r in range(sh.nrows)]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows += [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()

    records: dict = {}
    col_code = col_name = col_class = None
    for row in rows:
        cells = [str(c or "").strip() for c in row]
        low = [c.lower() for c in cells]
        # строка заголовков — запоминаем, где какая колонка
        if col_code is None and any(c.startswith("код") for c in low):
            for i, c in enumerate(low):
                if c.startswith("код"):
                    col_code = i
                elif c.startswith("наимен"):
                    col_name = i
                elif "класс" in c:
                    col_class = i
            continue
        if col_code is None or col_code >= len(row):
            continue
        code = _code_from(row[col_code])
        if len(code) != 11:
            continue
        name = cells[col_name] if col_name is not None and col_name < len(cells) else ""
        hazard = _hazard_from(row[col_class] if col_class is not None
                              and col_class < len(row) else "", code)
        rec = {"name": name, "class": hazard}
        if code[-1] == "0":            # групповой заголовок каталога, не позиция
            rec["group"] = True
        records[code] = rec
    return records


def load_file(path: str | Path) -> tuple[int, str]:
    """Загрузить каталог из файла пользователя (xls/xlsx/csv/json/txt).

    Открытого машиночитаемого ФККО в сети нет (Росприроднадзор публикует
    каталог страницей и файлами), поэтому это основной путь получить полный
    справочник: скачали файл — указали его здесь."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Файл не найден: {p}")
    if p.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        records = parse_table(p)
        if not records:                       # вдруг это не таблица, а текст
            from ecodoc.parsers.text_extract import extract
            records = parse(extract(p, ocr=False).text)
    else:
        records = parse(p.read_text(encoding="utf-8-sig", errors="replace"))
    if not records:
        raise ValueError("В файле не найдено ни одной пары «код ФККО + наименование»")
    # в справочник пишем только имя файла: сам справочник лежит в публичном
    # репозитории, полные пути с диска пользователя туда попадать не должны
    save(records, source=p.name, partial=len(records) < 1000)
    return len(records), str(p)


def find_in_forms() -> Path | None:
    """Файл каталога ФККО в папке «Формы» пользователя (если он там есть).

    Пользователь держит там бланки документов — там же лежит и выгрузка ФККО."""
    from ecodoc.core import forms_registry
    base = forms_registry.root()
    if base is None:
        return None
    exts = (".xls", ".xlsx", ".xlsm", ".csv", ".json", ".txt")
    hits = [f for f in base.rglob("*")
            if f.is_file() and f.suffix.lower() in exts
            and "фкко" in f.name.lower()]
    if not hits:
        return None
    # файлов может быть несколько (старая выгрузка + свежая) — берём свежайший
    return max(hits, key=lambda f: f.stat().st_mtime)


def from_forms_folder() -> tuple[int, str] | None:
    """Загрузить каталог из папки «Формы», если файл там нашёлся."""
    f = find_in_forms()
    if f is None:
        return None
    n = sync_from_forms(force=True)
    return (n, str(f)) if n else None


def sync_from_forms(force: bool = False) -> int:
    """Подхватить каталог из «Форм», если он новее загруженного.

    Вызывается при запуске: пользователь кладёт свежую выгрузку ФККО в папку
    с бланками, и она должна применяться сама, без кнопок. Возвращает число
    загруженных кодов (0 — если перечитывать нечего).

    Каталог, загруженный пользователем вручную (кнопкой или из сети), сама
    не трогает — иначе свежий справочник затирался бы старым файлом из
    «Форм» при каждом запуске. Кнопка «Обновить каталог» зовёт с force=True."""
    f = find_in_forms()
    if f is None:
        return 0
    cat = catalog()
    if not force and cat.get("codes") and cat.get("origin", "forms") != "forms":
        return 0                       # ручной каталог автоматом не заменяем
    try:
        st = f.stat()
        # в отпечатке и размер: подменённый в ту же секунду файл тоже должен
        # считаться новым
        stamp = f"{f.name}@{int(st.st_mtime)}@{st.st_size}"
    except OSError:
        return 0
    if not force and cat.get("stamp") == stamp:
        return 0                       # тот же файл — уже загружен
    try:
        records = parse_table(f) if f.suffix.lower() in (".xls", ".xlsx", ".xlsm") \
            else parse(f.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return 0
    if not records:
        return 0
    save(records, source=f.name, partial=len(records) < 1000, stamp=stamp,
         origin="forms")
    return len(records)


def seed_builtin() -> int:
    """Подготовить каталог, если его ещё нет.

    Сначала ищем полную выгрузку ФККО в папке «Формы» пользователя (он держит
    её там вместе с бланками), и только если не нашли — ставим встроенный
    минимум из справочника частых отходов (помечается как частичный)."""
    if codes():
        return 0
    try:
        found = from_forms_folder()
        if found:
            return found[0]
    except Exception:
        pass
    try:
        from ecodoc.core.refdata import common_wastes
        records = {norm(w["fkko"]): {"name": w.get("name", ""),
                                     "class": int(w.get("class") or 0)}
                   for w in common_wastes() if norm(w.get("fkko", ""))}
    except Exception:
        records = {}
    if records:
        save(records, source="встроенный справочник частых отходов", partial=True)
    return len(records)


def is_stale(cat: dict | None = None) -> str:
    """Признаки того, что каталог — старая редакция. Пустая строка = свежий.

    Каталог из файла пользователя может быть снимком отменённой редакции:
    дата файла свежая, а содержимое — многолетней давности. Смотрим на суть:
    объём, маркеры последних приказов и строки «Исключен» (так помечали
    позиции в ФККО, отменённом приказом № 242)."""
    cat = catalog() if cat is None else cat
    rec = cat.get("codes") or {}
    if not rec:
        return "каталог не загружен"
    if cat.get("partial"):
        return ""                       # частичный — про свежесть не судим
    missing = [c for c in FRESH_MARKERS if c not in rec]
    excluded = sum(1 for v in rec.values()
                   if "исключен" in str(v.get("name", "")).lower()[:12])
    if excluded:
        return (f"это снимок ОТМЕНЁННОГО каталога: в нём {excluded} позиций "
                f"помечены «Исключен. — Приказ …». Действующий — "
                f"{CURRENT_EDITION}")
    if len(rec) < 9000:
        return (f"в каталоге {len(rec)} кодов, а в действующем ФККО их около "
                f"9150 — похоже на устаревшую или неполную выгрузку")
    if missing:
        return (f"нет кодов из последних приказов ({', '.join(missing)}) — "
                f"каталог старее редакции {CURRENT_EDITION}")
    return ""


def fetch_rpn(timeout: int = 30, progress=None) -> dict:
    """Выкачать действующий каталог с сайта Росприроднадзора.

    Каталог отдаётся постранично по 20 позиций (~460 страниц). Открытых
    данных РПН не публикует, поэтому это единственный способ получить
    действующую редакцию машиной."""
    import urllib.parse
    import urllib.request

    hdr = {"User-Agent": "Mozilla/5.0 (compatible; EcoDoc)",
           "X-Requested-With": "XMLHttpRequest",
           "Content-Type": "application/x-www-form-urlencoded"}

    def get(url: str, post: bool = False) -> str:
        data = urllib.parse.urlencode({"AJAX": "Y"}).encode() if post else None
        req = urllib.request.Request(url, data=data, headers=hdr)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")

    first = get(RPN_PAGE)
    total = 0
    m = re.search(r"Показано\s*\d+\s*-\s*\d+\s*из\s*(\d+)", first)
    if m:
        total = int(m.group(1))
    records: dict = {}

    # на первой странице каталог отдан готовым JSON-списком в инициализаторе
    for code, name in re.findall(
            r"'CODE'\s*:\s*'(\d{11})'\s*,\s*'NAME'\s*:\s*'((?:[^'\\]|\\.)*)'",
            first):
        records[code] = _rec(code, name.replace("\\'", "'"))

    pages = (total + 19) // 20 if total else 500
    row = re.compile(r'href="/fkko/(\d{11})/"[^>]*>(.*?)</a>', re.S)
    empty = 0
    for n in range(1, pages + 1):
        try:
            html = get(RPN_MORE.format(n=n), post=True)
        except Exception:
            empty += 1
            if empty >= 3:
                break
            continue
        found = row.findall(html)
        if not found:
            empty += 1
            if empty >= 3:               # три пустые подряд — каталог кончился
                break
            continue
        empty = 0
        for code, name in found:
            name = re.sub(r"<[^>]+>", " ", name)
            records[code] = _rec(code, name)
        if progress and n % 25 == 0:
            progress(len(records), total)
    return records


def _rec(code: str, name: str) -> dict:
    """Запись каталога: наименование чистим от разметки, класс — из кода."""
    name = re.sub(r"&[a-z]+;", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    rec = {"name": name,
           "class": int(code[-1]) if code[-1] in "12345" else 0}
    if code[-1] == "0":
        rec["group"] = True
    return rec


def update(timeout: int = 30, progress=None) -> tuple[int, str]:
    """Скачать действующий каталог с сайта РПН и сохранить."""
    try:
        records = fetch_rpn(timeout=timeout, progress=progress)
    except Exception as e:
        raise RuntimeError(
            f"Не удалось скачать каталог ФККО с сайта Росприроднадзора "
            f"({RPN_PAGE}): {str(e)[:160]}. Проверьте интернет или положите "
            f"выгрузку ФККО в папку «Формы» — программа подхватит её сама.")
    if len(records) < 1000:
        raise RuntimeError(
            f"С сайта Росприроднадзора получено всего {len(records)} кодов — "
            f"похоже, изменилась разметка страницы каталога. Загрузите "
            f"каталог файлом или сообщите разработчику.")
    save(records, source=f"rpn.gov.ru ({CURRENT_EDITION})",
         partial=False, stamp=f"rpn@{date.today().isoformat()}")
    return len(records), RPN_PAGE
