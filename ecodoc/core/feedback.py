"""Замечания пользователя из интерфейса — в файл, который читает Claude.

Эколог правит замечания в .txt и присылает в чат; не всегда понятно, где
именно и что он видел. Кнопка «Замечание» в шапке сохраняет вместе с
текстом контекст: вкладка/подвкладка, площадка, версия, видимый текст
вкладки, ошибки консоли, и (по желанию) снимок данных площадки. Файл
кладётся в очередь автозадач — следующая сессия его увидит.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

DEFAULT_DIR = Path(r"C:\Users\veter\OneDrive\II\АВТОЗАДАЧИ\ЗАМЕЧАНИЯ_ЭКОДОК")


def feedback_dir() -> Path:
    import os
    d = Path(os.environ.get("ECODOC_FEEDBACK_DIR") or DEFAULT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", str(s or ""), flags=re.U).strip("_")
    return s[:40] or "x"


def save(payload: dict, site_dir: Path | None = None) -> Path:
    """Записать замечание (.md) и, если просили, снимок данных (.json)."""
    now = datetime.now()
    tab = payload.get("tab") or "-"
    sub = payload.get("subtab") or ""
    name = f"{now:%Y-%m-%d_%H%M%S}_{_slug(tab)}{('_' + _slug(sub)) if sub else ''}.md"
    d = feedback_dir()
    path = d / name
    text = str(payload.get("text") or "").strip()
    lines = [f"# Замечание из ЭКО.DOC — {now:%d.%m.%Y %H:%M}",
             "",
             f"- Версия: {payload.get('version') or '?'}",
             f"- Организация / площадка: {payload.get('org') or '—'} / {payload.get('site') or '—'}",
             f"- Вкладка: {tab}" + (f" → {sub}" if sub else ""),
             f"- Статус: ОЖИДАЕТ (Claude: разобрать, исправить, отметить ГОТОВО)",
             "",
             "## Что не так (слова пользователя)",
             "",
             text or "(текст не введён)",
             ""]
    errs = payload.get("console_errors") or []
    if errs:
        lines += ["## Ошибки в консоли браузера", ""] + [f"- {str(e)[:300]}" for e in errs[:30]] + [""]
    page = str(payload.get("page_text") or "").strip()
    if page:
        lines += ["## Что было на экране (текст вкладки)", "", "```", page[:20000], "```", ""]
    if payload.get("with_data") and site_dir and (Path(site_dir) / "context.json").exists():
        snap = d / (path.stem + "_данные.json")
        try:
            snap.write_bytes((Path(site_dir) / "context.json").read_bytes())
            lines += [f"- Снимок данных площадки: {snap.name}", ""]
        except OSError:
            pass
    path.write_text("\n".join(lines), encoding="utf-8")
    # индекс для быстрого просмотра
    idx = d / "ИНДЕКС.md"
    with idx.open("a", encoding="utf-8") as f:
        f.write(f"- {now:%Y-%m-%d %H:%M} — {tab}{(' → ' + sub) if sub else ''} — "
                f"{(text[:80] + '…') if len(text) > 80 else text} → {name}\n")
    return path


def pending() -> list[dict]:
    """Незакрытые замечания (для сводки при старте сессии)."""
    out = []
    for p in sorted(feedback_dir().glob("*.md")):
        if p.name == "ИНДЕКС.md":
            continue
        try:
            head = p.read_text(encoding="utf-8")[:600]
        except OSError:
            continue
        if "Статус: ОЖИДАЕТ" in head:
            out.append({"file": p.name, "path": str(p)})
    return out
