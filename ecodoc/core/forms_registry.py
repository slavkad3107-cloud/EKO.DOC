"""Реестр форм-образцов: какие бланки есть у пользователя и чего не хватает.

Требование ТЗ: «Все формы используемых и генерируемых документов лежат в
OneDrive\\Формы. Нужно проверять все формы: если есть — хорошо, если нет —
поискать по папкам/архивам в D: и в интернете и положить найденное в
соответствующую папку… проверять на наличие новых форм при запуске
приложения».

Здесь — учёт и поиск. Проверка бланка на соответствие НПА и решение
«принимать ли его как образец» остаётся за пользователем: программа готовит
отчёт, но сама форму не утверждает.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

def roots() -> list[Path]:
    """Где искать бланки: env ECODOC_FORMS → OneDrive\\Формы → D:\\S\\Формы.

    Путь не зашит под конкретный компьютер: на другой машине сработает свой
    OneDrive, а в тестах — временная папка из ECODOC_FORMS."""
    env = os.environ.get("ECODOC_FORMS", "")
    if env:
        # папка задана явно — она и есть единственный источник бланков
        # (иначе при опечатке в пути молча использовались бы чужие бланки)
        return [Path(env)]
    return [Path.home() / "OneDrive" / "Формы", Path("D:/S/Формы")]


def search_roots() -> list[Path]:
    """Где искать недостающие бланки (архивы не вскрываем)."""
    env = os.environ.get("ECODOC_FORMS_SEARCH", "")
    if env:
        return [Path(env)]
    return [Path("D:/S"), Path("D:/S/Формы")]

DOC_EXTS = {".xlsx", ".xls", ".xlsm", ".doc", ".docx", ".pdf", ".html", ".htm"}
STATE_FILE = "реестр-форм.json"     # рядом с папкой форм: снимок прошлой проверки


@dataclass
class FormSlot:
    """Документ программы и его бланк-образец."""
    code: str                  # код формы в реестре программы (или "")
    title: str                 # как называется у пользователя (папка)
    kind: str                  # reporting | development
    folder: str = ""           # подпапка в «Формы»
    files: list = field(default_factory=list)   # найденные бланки
    keywords: tuple = ()       # по чему искать на диске

    @property
    def has_sample(self) -> bool:
        return bool(self.files)


# сопоставление «папка пользователя → документ программы»
SLOTS: list[FormSlot] = [
    FormSlot("2tp-air", "2-ТП воздух", "reporting", "Отчетность/2-ТП воздух",
             keywords=("2-тп", "воздух")),
    FormSlot("2tp-waste", "2-ТП отходы", "reporting", "Отчетность/2-ТП отходы",
             keywords=("2-тп", "отход")),
    FormSlot("4-oos", "4-ОС", "reporting", "Отчетность/4-ООС",
             keywords=("4-оос", "4 оос")),
    FormSlot("waste-movement", "Движение отходов 1028", "reporting",
             "Отчетность/Движение отходов 1028", keywords=("1028", "журнал учета отход")),
    FormSlot("declaration-nvos", "Декларация", "reporting", "Отчетность/ДЕкларация",
             keywords=("деклараци", "нвос")),
    FormSlot("cadastre-spb", "КАДАСТР", "reporting", "Отчетность/КАДАСТР",
             keywords=("кадастр",)),
    FormSlot("pek", "Отчёт ПЭК", "reporting", "Отчетность/ОТчет ПЭК",
             keywords=("пэк", "производственн")),
    FormSlot("waste-passport", "ПОО (паспорта отходов)", "development",
             "Разработка/ПОО", keywords=("паспорт отход", "поо")),
    FormSlot("waste-inventory", "Инвентаризация отходов", "development",
             "Разработка/ИНВЕНТАРИЗАЦИЯ ОТХОДОВ",
             keywords=("инвентаризац", "отход")),
    FormSlot("air-inventory", "Инвентаризация выбросов", "development",
             "Разработка/ИНВЕНТАРИЗАЦИЯ ВЫБРОСОВ",
             keywords=("инвентаризац", "выброс")),
    FormSlot("nmu", "НМУ", "development", "Разработка/НМУ", keywords=("нму",)),
    FormSlot("pnoolr", "ПНООЛР", "development", "Разработка/ПНООЛР",
             keywords=("пноолр",)),
    FormSlot("pek-program", "Программа ПЭК", "development", "Разработка/ПЭК",
             keywords=("программа пэк",)),
    FormSlot("hazard-class", "Расчёт класса опасности", "development",
             "Разработка/РАСЧЕТ КЛАССА ОПАСНОСТИ",
             keywords=("класс опасност", "расчет класса")),
    FormSlot("tu-waste", "ТУ", "development", "Разработка/ТУ",
             keywords=("технические услови",)),
    FormSlot("nds", "НДС", "development", "Разработка/НДС", keywords=("ндс",)),
    FormSlot("ndv", "НДВ", "development", "Разработка/НДВ", keywords=("ндв",)),
    FormSlot("oos", "ООС", "development", "Разработка/ООС",
             keywords=("оос", "охрана окружающей")),
    FormSlot("waste-table", "Табличка отходов", "reporting", "",
             keywords=("таблич", "отход")),
    FormSlot("", "Перечень для контроля (воздух)", "reporting", "",
             keywords=("перечень для контроля",)),
    FormSlot("fkko-catalog", "Каталог ФККО", "reporting", "",
             keywords=("фкко",)),
]


def root() -> Path | None:
    for r in roots():
        if r.is_dir():
            return r
    return None


def scan() -> list[FormSlot]:
    """Что лежит в папке форм: для каждого документа — найденные бланки."""
    base = root()
    slots = [FormSlot(s.code, s.title, s.kind, s.folder, [], s.keywords)
             for s in SLOTS]
    if base is None:
        return slots
    for slot in slots:
        if slot.folder:
            d = base / slot.folder
            if d.is_dir():
                slot.files = [str(f.relative_to(base)) for f in sorted(d.iterdir())
                              if f.is_file() and f.suffix.lower() in DOC_EXTS]
        else:                                  # файлы в корне «Формы»
            for f in sorted(base.glob("*")):
                if f.is_file() and f.suffix.lower() in DOC_EXTS and \
                        any(k in f.name.lower() for k in slot.keywords):
                    slot.files.append(f.name)
    return slots


def sample_for(code: str) -> Path | None:
    """Путь к бланку-образцу документа (первый xlsx/xls, иначе первый файл)."""
    base = root()
    if base is None:
        return None
    slot = next((s for s in scan() if s.code == code and s.files), None)
    if not slot:
        return None
    files = [base / f for f in slot.files]
    xls = [f for f in files if f.suffix.lower() in (".xlsx", ".xlsm", ".xls")]
    return (xls or files)[0]


def find_missing(slots: list[FormSlot] | None = None, limit: int = 5) -> dict:
    """Поискать бланки для пустых папок на диске D: (архивы не вскрываем)."""
    slots = slots or scan()
    out: dict[str, list[str]] = {}
    dirs = [r for r in search_roots() if r.is_dir()]
    if not dirs:
        return out
    for slot in slots:
        if slot.has_sample or not slot.keywords:
            continue
        hits: list[str] = []
        for r in dirs:
            for f in r.rglob("*"):
                if len(hits) >= limit:
                    break
                if not f.is_file() or f.suffix.lower() not in DOC_EXTS:
                    continue
                name = f.name.lower()
                if all(k in name for k in slot.keywords):
                    hits.append(str(f))
            if len(hits) >= limit:
                break
        if hits:
            out[slot.title] = hits
    return out


def state_path() -> Path | None:
    base = root()
    return (base / STATE_FILE) if base else None


def check_new() -> dict:
    """Сравнить с прошлой проверкой: что появилось/исчезло с прошлого запуска."""
    slots = scan()
    now = {s.title: sorted(s.files) for s in slots}
    p = state_path()
    prev = {}
    if p and p.exists():
        try:
            prev = json.loads(p.read_text(encoding="utf-8-sig")).get("forms", {})
        except (OSError, json.JSONDecodeError):
            prev = {}
    added, removed = {}, {}
    for title, files in now.items():
        was = set(prev.get(title, []))
        new_files = [f for f in files if f not in was]
        gone = [f for f in was if f not in files]
        if new_files:
            added[title] = new_files
        if gone:
            removed[title] = gone
    if p:
        # запись через временный файл: снимок лежит в общей папке OneDrive,
        # и его могут писать одновременно проверка при запуске и кнопка
        tmp = p.with_suffix(f".tmp{os.getpid()}")
        try:
            tmp.write_text(json.dumps({"checked": date.today().isoformat(),
                                       "forms": now}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return {"added": added, "removed": removed, "first_run": not prev}


def summary() -> str:
    """Текстовый отчёт: какие бланки есть, каких нет."""
    base = root()
    if base is None:
        return ("Папка с формами не найдена. Ожидается "
                f"{roots()[0]} — положите туда бланки документов.")
    slots = scan()
    have = [s for s in slots if s.has_sample]
    miss = [s for s in slots if not s.has_sample]
    lines = [f"── Бланки документов ({base}) ──",
             f"есть образцы: {len(have)} из {len(slots)}"]
    for s in have:
        lines.append(f"  ✓ {s.title}: {len(s.files)} файл(ов) — {s.files[0]}")
    if miss:
        lines.append("нет образцов:")
        for s in miss:
            lines.append(f"  ○ {s.title}"
                         + (f" (папка {s.folder})" if s.folder else ""))
    return "\n".join(lines)
