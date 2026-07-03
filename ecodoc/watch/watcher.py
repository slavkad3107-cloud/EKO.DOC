"""Слежение за изменениями форм: снимки страниц-источников и сравнение.

`ecodoc watch check` скачивает каждую страницу из sources.json, приводит
к тексту (без тегов/пробелов), считает хэш и сравнивает со снимком в
~/.ecodoc/watch/. Изменение хэша = сигнал «форму/ставки/схему могли
поменять — проверьте вручную». Это сторожок, а не парсер права: он не
интерпретирует изменения, он их замечает.

Дополнительно `--xsd <папка>`: следит за локальной папкой XSD-схем ЛКПП
(появление новых версий файлов).
"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.request
from datetime import date
from pathlib import Path

from ecodoc.ai.config import CONFIG_DIR

SOURCES_PATH = Path(__file__).parent / "sources.json"
SNAP_DIR = CONFIG_DIR / "watch"

_UA = {"User-Agent": "Mozilla/5.0 (compatible; EcoDoc form-watcher)"}


def load_sources() -> list[dict]:
    data = json.loads(SOURCES_PATH.read_text(encoding="utf-8-sig"))
    return data.get("sources", [])


def _fetch_text(url: str, timeout: int = 20,
                allow_insecure: bool = False) -> str:
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.URLError as e:
        # госсайты РФ с сертификатами Минцифры: без проверки сертификата —
        # только если источник явно помечен "allow_insecure": true
        if not allow_insecure or "SSL" not in str(e):
            raise
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read()
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        html = raw.decode("cp1251", "replace")
    # выкинуть скрипты/стили/теги и лишние пробелы — остаётся содержимое
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _snap_path(source_id: str) -> Path:
    return SNAP_DIR / f"{source_id}.json"


def check_source(src: dict) -> dict:
    """Вернуть {'id', 'status': new|same|changed|error, 'detail'}."""
    out = {"id": src["id"], "name": src["name"], "status": "same", "detail": ""}
    try:
        text = _fetch_text(src["url"],
                           allow_insecure=bool(src.get("allow_insecure")))
    except Exception as e:
        out["status"], out["detail"] = "error", str(e)
        return out
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    snap_file = _snap_path(src["id"])
    prev = json.loads(snap_file.read_text(encoding="utf-8")) \
        if snap_file.exists() else None
    if prev is None:
        out["status"] = "new"
    elif prev["sha256"] != digest:
        out["status"] = "changed"
        out["detail"] = f"снимок от {prev['date']} отличается"
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    snap_file.write_text(json.dumps(
        {"sha256": digest, "date": date.today().isoformat(),
         "url": src["url"], "length": len(text)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def check_xsd_dir(xsd_dir: Path) -> list[str]:
    """Следить за папкой с XSD ЛКПП: новые/изменённые файлы с прошлого раза."""
    reg_file = SNAP_DIR / "xsd_local.json"
    prev = json.loads(reg_file.read_text(encoding="utf-8")) \
        if reg_file.exists() else {}
    cur, changes = {}, []
    for f in sorted(Path(xsd_dir).glob("**/*.xsd")):
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        cur[str(f)] = digest
        if str(f) not in prev:
            changes.append(f"новый XSD: {f.name}")
        elif prev[str(f)] != digest:
            changes.append(f"изменён XSD: {f.name}")
    for old in prev:
        if old not in cur:
            changes.append(f"удалён XSD: {Path(old).name}")
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    reg_file.write_text(json.dumps(cur, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return changes


def run_check(xsd_dir: str | None = None) -> str:
    lines = ["── Проверка изменений форм и источников ──"]
    changed = 0
    for src in load_sources():
        r = check_source(src)
        mark = {"same": "=", "new": "＋ снимок создан",
                "changed": "⚠ ИЗМЕНИЛОСЬ", "error": "✖"}[r["status"]]
        note = f" — {r['detail']}" if r["detail"] else ""
        lines.append(f"  {mark:<16} {r['name']}{note}")
        if r["status"] == "changed":
            changed += 1
            forms = ", ".join(src.get("forms", []))
            lines.append(f"      затрагивает формы: {forms}")
            lines.append(f"      проверьте: {src['url']}")
    if xsd_dir:
        xsd_changes = check_xsd_dir(Path(xsd_dir))
        lines.append("  XSD (локальная папка):")
        lines += [f"    ⚠ {c}" for c in xsd_changes] or ["    = без изменений"]
    lines.append("")
    lines.append("⚠ Обнаружены изменения — сверьте формы перед сдачей!"
                 if changed else "Изменений не обнаружено.")
    return "\n".join(lines)
