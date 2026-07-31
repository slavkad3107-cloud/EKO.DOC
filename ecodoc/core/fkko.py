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
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "fkko.json"

# официальные источники каталога (проверяются по порядку)
SOURCES = [
    "https://rpn.gov.ru/upload/iblock/fkko.json",
    "https://rpn.gov.ru/fkko/",
]

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
    """Каталог из файла (кэш по времени изменения файла)."""
    if not DATA_FILE.exists():
        return {}
    mtime = DATA_FILE.stat().st_mtime
    if _CACHE.get("mtime") != mtime:
        try:
            _CACHE["data"] = json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            _CACHE["data"] = {}
        _CACHE["mtime"] = mtime
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
        return Check(code=d, ok=False, verified=False,
                     problem="кода нет в действующем ФККО — проверьте по каталогу")
    chk = Check(code=d, ok=True, verified=True, name=rec.get("name", ""),
                hazard=int(rec.get("class") or 0))
    if name and chk.name:
        ours = re.sub(r"\s+", " ", name).strip().lower().replace("ё", "е")
        theirs = re.sub(r"\s+", " ", chk.name).strip().lower().replace("ё", "е")
        if ours and theirs and ours[:40] != theirs[:40]:
            chk.name_mismatch = chk.name
    return chk


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


def save(records: dict, source: str = "", partial: bool = False) -> Path:
    """Записать каталог (код → {name, class}).

    partial=True — набор заведомо неполный (встроенный минимум или выборка):
    тогда отсутствие кода не считается ошибкой."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated": date.today().isoformat(), "source": source,
               "partial": bool(partial), "codes": records}
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA_FILE)
    _CACHE.clear()
    return DATA_FILE


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
    if s.isdigit() and s in "12345":
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


def from_forms_folder() -> tuple[int, str] | None:
    """Найти каталог ФККО в папке «Формы» пользователя и загрузить его.

    Пользователь держит там бланки документов — там же лежит и выгрузка ФККО."""
    from ecodoc.core import forms_registry
    base = forms_registry.root()
    if base is None:
        return None
    for pattern in ("ФККО*", "*фкко*", "*ФККО*"):
        for f in base.rglob(pattern):
            if f.is_file() and f.suffix.lower() in (".xls", ".xlsx", ".xlsm",
                                                    ".csv", ".json", ".txt"):
                try:
                    return load_file(f)
                except Exception:
                    continue
    return None


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


def update(timeout: int = 60) -> tuple[int, str]:
    """Скачать и сохранить действующий каталог. Возвращает (сколько кодов, откуда)."""
    import urllib.request
    last = ""
    for url in SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "EcoDoc/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            text = raw.decode("utf-8", "replace")
            records = parse(text)
            if len(records) >= 100:            # похоже на настоящий каталог
                save(records, source=url)
                return len(records), url
            last = f"{url}: разобрано всего {len(records)} кодов"
        except Exception as e:
            last = f"{url}: {str(e)[:120]}"
    raise RuntimeError(
        "Не удалось получить каталог ФККО из открытых источников. "
        f"Последняя попытка — {last}. Каталог можно положить вручную: "
        f"{DATA_FILE} в виде {{\"codes\": {{\"47110101521\": "
        f"{{\"name\": \"…\", \"class\": 1}}}}}}.")
