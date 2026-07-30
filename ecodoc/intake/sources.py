"""Реестр источников: какие документы разобраны и какие их листы сохранены.

Отдельный файл `sources.json` рядом с `context.json`, потому что:
  * `context.json` пересохраняется целиком при каждом «Сохранить» и на каждом
    чанке приёма — держать там служебные сведения дорого;
  * `serialize.from_json` собирает контекст заново и выбрасывает незнакомые
    ключи — данные бы молча пропали.

Здесь только «паспорт» документа (имя, sha1, метод, число листов, снятые
картинки листов). Сами найденные значения и их выбор пользователем — уровнем
выше (кандидаты, следующий этап).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

FILE = "sources.json"
_LOCK = threading.Lock()        # сервер многопоточный


def path_for(site_dir: str | Path) -> Path:
    return Path(site_dir) / FILE


def load(site_dir: str | Path) -> dict:
    p = path_for(site_dir)
    if not p.exists():
        return {"version": 1, "docs": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        data.setdefault("docs", {})
        return data
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "docs": {}}


def save(site_dir: str | Path, data: dict) -> Path:
    p = path_for(site_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(p)
    return p


def remember(site_dir: str | Path, sha1: str, *, file: str, method: str = "",
             page_kind: str = "page", pages_total: int = 0,
             images: dict | None = None, doc_type: str = "",
             origin: str = "", size: int = 0) -> None:
    """Записать/дополнить паспорт документа (дозаписи не затирают снятые листы)."""
    if not sha1:
        return
    with _LOCK:
        data = load(site_dir)
        rec = data["docs"].setdefault(sha1, {})
        rec.update({k: v for k, v in (
            ("file", file), ("method", method), ("page_kind", page_kind),
            ("pages_total", pages_total), ("doc_type", doc_type),
            ("origin", origin), ("size", size)) if v})
        if images:
            rec.setdefault("images", {}).update({str(k): v for k, v in images.items()})
        save(site_dir, data)


def doc_by_sha(site_dir: str | Path, sha1: str) -> dict | None:
    return load(site_dir)["docs"].get(sha1)


def sha_by_name(site_dir: str | Path, name: str) -> str:
    """sha1 документа по имени файла (последний с таким именем)."""
    for sha, rec in load(site_dir)["docs"].items():
        if rec.get("file") == name:
            return sha
    return ""


def kept_images(site_dir: str | Path) -> set[str]:
    """Имена всех картинок листов, на которые ссылается реестр (для чистки)."""
    out: set[str] = set()
    for rec in load(site_dir)["docs"].values():
        out.update((rec.get("images") or {}).values())
    return out
