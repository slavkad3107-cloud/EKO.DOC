"""Приём пакета входящих документов в площадку.

Сценарий `ecodoc intake <файлы> --org O --site S [--ai] [--form F]`:
  1) файлы копируются в attachments/ площадки (реестр intake.json);
  2) regex-парсер + (опционально) ИИ-анализ сливают значения в контекст;
  3) печатается отчёт: что принято и откуда взято, конфликты,
     чего не хватает и какие документы ещё нужны (по требуемым формам).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

from ecodoc.core import workspace
from ecodoc.core.models import ReportContext
from ecodoc.intake import requirements
from ecodoc.parsers import extractor
from ecodoc.parsers.text_extract import extract


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _register(att_dir: Path, src: Path) -> tuple[Path, bool]:
    """Скопировать файл в attachments/, вести реестр. False — уже был."""
    att_dir.mkdir(parents=True, exist_ok=True)
    reg_path = att_dir / "intake.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else []
    digest = _sha1(src)
    for row in reg:
        if row["sha1"] == digest:
            return att_dir / row["file"], False
    dest = att_dir / src.name
    n = 1
    while dest.exists() and _sha1(dest) != digest:
        dest = att_dir / f"{src.stem}_{n}{src.suffix}"
        n += 1
    if not dest.exists():
        shutil.copy2(src, dest)
    reg.append({"file": dest.name, "sha1": digest,
                "received": date.today().isoformat()})
    reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return dest, True


def store(files: list[str], org: str, site: str) -> tuple[list[str], list[str]]:
    """Сохранить файлы в attachments площадки (без анализа).

    Возвращает (имена сохранённых файлов, строки лога). Позволяет грузить
    большие папки партиями, а анализ запускать один раз в конце.
    """
    att = workspace.site_dir(org, site) / "attachments"
    names, lines = [], []
    for f in files:
        src = Path(f)
        if not src.exists():
            lines.append(f"✖ нет файла: {src}")
            continue
        dest, is_new = _register(att, src)
        lines.append(f"{'＋ принят' if is_new else '= уже был'}: {dest.name}")
        names.append(dest.name)
    return names, lines


def analyze_stored(names: list[str], org: str, site: str,
                   use_ai: bool = False, forms: list[str] | None = None,
                   ocr: bool = True) -> str:
    """Проанализировать уже сохранённые в attachments файлы (по именам)."""
    att = workspace.site_dir(org, site) / "attachments"
    ctx = workspace.load_context(org, site)
    paths = [att / n for n in names if (att / n).exists()]
    return _analyze(paths, ctx, org=org, site=site, use_ai=use_ai,
                    forms=forms, ocr=ocr,
                    lines=[f"Файлов к анализу: {len(paths)}"])


def run(files: list[str], org: str = "", site: str = "",
        ctx: ReportContext | None = None, use_ai: bool = False,
        forms: list[str] | None = None, ocr: bool = True) -> str:
    """Принять файлы; вернуть текстовый отчёт. Контекст сохраняется сам."""
    lines: list[str] = []
    in_workspace = bool(org and site)
    if ctx is None:
        ctx = workspace.load_context(org, site) if in_workspace else ReportContext()

    # 1. регистрация файлов
    stored: list[Path] = []
    if in_workspace:
        names, log = store(files, org, site)
        lines += log
        att = workspace.site_dir(org, site) / "attachments"
        stored = [att / n for n in names]
        ctx = workspace.load_context(org, site)
    else:
        stored = [Path(f) for f in files if Path(f).exists()]
        lines += [f"✖ нет файла: {f}" for f in files if not Path(f).exists()]
    return _analyze(stored, ctx, org=org if in_workspace else "",
                    site=site if in_workspace else "", use_ai=use_ai,
                    forms=forms, ocr=ocr, lines=lines)


def _analyze(stored: list[Path], ctx: ReportContext, org: str, site: str,
             use_ai: bool, forms: list[str] | None, ocr: bool,
             lines: list[str]) -> str:
    in_workspace = bool(org and site)
    # 2. извлечение текста + regex-парсер (быстрый, консервативный)
    docs = []
    for p in stored:
        try:
            docs.append(extract(p, ocr=ocr))
        except Exception as e:
            lines.append(f"✖ не читается {p.name}: {e}")
    for doc in docs:
        extractor._fill_from_doc(ctx, doc)
    if docs:
        from ecodoc.intake import classify
        lines.append("")
        lines.append(classify.render(docs))
    lines.append("")
    lines.append(extractor.summary(ctx))

    # 3. ИИ-анализ (семантика: акты, массы, протоколы) — по флагу
    if use_ai and docs:
        from ecodoc.ai.analyzer import analyze_docs
        rep = analyze_docs(docs, ctx)
        lines.append("")
        lines.append(rep.render())

    # 4. контроль полноты: чего не хватает и что донести
    target_forms = forms or list(requirements.REQUIREMENTS)
    unknown = [f for f in target_forms if f not in requirements.REQUIREMENTS]
    target_forms = [f for f in target_forms if f in requirements.REQUIREMENTS]
    lines.append("")
    lines.append("── Полнота данных по формам ──")
    for f in unknown:
        lines.append(f"  ✖ неизвестная форма «{f}» — список: python -m ecodoc list")
    need_docs: list[str] = []
    for form in target_forms:
        missing, docs_hint = requirements.check(ctx, form)
        if missing:
            lines.append(f"  ○ {form}: не хватает — {', '.join(missing)}")
            need_docs.extend(docs_hint)
        else:
            lines.append(f"  ✓ {form}: данных достаточно, можно генерировать")
    if need_docs:
        lines.append("")
        lines.append("── Какие документы ещё нужны ──")
        for d in dict.fromkeys(need_docs):
            lines.append(f"  • {d}")

    if in_workspace:
        workspace.save_context(org, site, ctx)
        lines.append(f"\nКонтекст сохранён: {workspace.site_dir(org, site) / 'context.json'}")
    return "\n".join(lines)
