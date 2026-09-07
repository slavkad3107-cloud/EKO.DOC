"""Кэш извлечённого текста документов — чтобы переразобрать без исходника.

Исходники после анализа удаляются (данные уже в базе), и до сих пор новая
версия программы не могла ничего добрать из старого ООС: эколог видел
«ООС не распознан» и должен был грузить файл заново. Теперь текст (по
листам) хранится в `texts/<sha1>.json.gz` рядом с context.json — это
килобайты, а «Переразобрать» в ЗАГРУЗКЕ работает и для удалённых файлов.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

DIR = "texts"


def _dir(site_dir: str | Path) -> Path:
    return Path(site_dir) / DIR


def path_for(site_dir: str | Path, sha1: str) -> Path:
    return _dir(site_dir) / f"{sha1}.json.gz"


def has(site_dir: str | Path, sha1: str) -> bool:
    return bool(sha1) and path_for(site_dir, sha1).exists()


def save(site_dir: str | Path, sha1: str, doc) -> Path | None:
    """Сохранить текст документа (ExtractedDoc) под его sha1."""
    if not sha1 or doc is None:
        return None
    pages = list(getattr(doc, "pages", None) or [])
    text = getattr(doc, "text", "") or ""
    if not pages and text:
        pages = [text]
    if not any(p.strip() for p in pages):
        return None                         # пустой текст хранить незачем
    d = _dir(site_dir)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"file": Path(getattr(doc, "path", "документ")).name,
               "method": getattr(doc, "method", ""),
               "page_kind": getattr(doc, "page_kind", "page"),
               "pages": pages}
    p = path_for(site_dir, sha1)
    tmp = p.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    tmp.replace(p)
    return p


def load(site_dir: str | Path, sha1: str, path: str | Path | None = None):
    """ExtractedDoc из кэша (path — «виртуальный» путь исходника для имени)."""
    if not has(site_dir, sha1):
        return None
    from ecodoc.parsers.text_extract import ExtractedDoc
    try:
        with gzip.open(path_for(site_dir, sha1), "rt", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    pages = [str(x) for x in (payload.get("pages") or [])]
    name = payload.get("file") or "документ"
    virt = Path(path) if path else Path(site_dir) / "attachments" / name
    doc = ExtractedDoc(virt, "\n".join(pages), pages,
                       payload.get("method") or "cache",
                       page_kind=payload.get("page_kind") or "page")
    doc.from_cache = True
    return doc


def forget(site_dir: str | Path, sha1: str) -> bool:
    p = path_for(site_dir, sha1)
    try:
        p.unlink()
        return True
    except OSError:
        return False
