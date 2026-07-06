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
import tempfile
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


_ARCHIVE_EXTS = {".zip", ".rar", ".7z"}
# типы, которые умеет анализировать text_extract (для отбора из архивов)
_DOC_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg",
             ".png", ".tif", ".tiff", ".txt", ".xml", ".rtf"}
_MAX_INNER = 100 * 1024 * 1024        # предел одного файла внутри архива
_MAX_TOTAL = 2 * 1024 * 1024 * 1024   # предел суммарной распаковки (анти-zip-бомба)
_MAX_FILES = 5000                     # предел числа извлечённых файлов
_MAX_DEPTH = 2                        # глубина вложенных архивов


def _zip_name(info) -> str:
    """Имя файла из zip с починкой кириллицы (Windows-архивы пишут cp866)."""
    name = info.filename
    if not (info.flag_bits & 0x800):        # нет флага UTF-8
        try:
            name = name.encode("cp437").decode("cp866")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def _seven_zip() -> str | None:
    for cand in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe",
                 r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if cand and Path(cand).exists():
            return cand
    return None


class _Budget:
    """Общий бюджет распаковки на одну операцию store (анти-zip-бомба)."""
    def __init__(self):
        self.bytes = 0
        self.files = 0
        self.seq = 0

    def allow(self, size: int) -> bool:
        if self.bytes + size > _MAX_TOTAL or self.files >= _MAX_FILES:
            return False
        self.bytes += size
        self.files += 1
        return True

    def unique(self, tmpdir: Path, stem: str, base: str) -> Path:
        """Уникальное имя в tmpdir (одинаковые basename не затирают друг друга),
        гарантированно внутри tmpdir (защита от path traversal)."""
        self.seq += 1
        safe = Path(base).name or f"file_{self.seq}"
        target = (tmpdir / f"{stem}__{self.seq}__{safe}").resolve()
        if not str(target).startswith(str(tmpdir.resolve())):
            return tmpdir / f"{stem}__{self.seq}__file"   # перестраховка
        return target


def _extract_archive(src: Path, tmpdir: Path, log: list[str],
                     budget: "_Budget", depth: int = 0) -> list[Path]:
    """Достать поддерживаемые документы из архива. Вложенные — до _MAX_DEPTH."""
    out: list[Path] = []
    skipped = 0
    if depth >= _MAX_DEPTH:
        log.append(f"  ⚠ {src.name}: слишком глубокая вложенность архивов — пропущен")
        return out
    if src.suffix.lower() == ".zip":
        import zipfile
        try:
            zf = zipfile.ZipFile(src)
        except (zipfile.BadZipFile, OSError):
            log.append(f"  ✖ {src.name}: повреждённый zip")
            return out
        with zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                base = Path(_zip_name(info).replace("\\", "/")).name
                ext = Path(base).suffix.lower()
                if ext not in _ARCHIVE_EXTS and ext not in _DOC_EXTS:
                    skipped += 1
                    continue
                if info.file_size > _MAX_INNER or not budget.allow(info.file_size):
                    skipped += 1
                    continue
                target = budget.unique(tmpdir, src.stem, base)
                try:
                    target.write_bytes(zf.read(info))
                except (RuntimeError, zipfile.BadZipFile, OSError):
                    skipped += 1                # зашифровано/битая запись
                    continue
                if ext in _ARCHIVE_EXTS:
                    out += _extract_archive(target, tmpdir, log, budget, depth + 1)
                else:
                    out.append(target)
    else:  # .rar / .7z — через установленный 7-Zip
        seven = _seven_zip()
        if not seven:
            log.append(f"  ⚠ {src.name}: для rar/7z установите 7-Zip "
                       f"(https://7-zip.org) — архив пропущен")
            return out
        import subprocess
        ex_dir = tmpdir / f"_{src.stem}_{budget.seq}"
        ex_dir.mkdir(parents=True, exist_ok=True)
        budget.seq += 1
        try:
            subprocess.run([seven, "x", "-y", "-snl-", f"-o{ex_dir}", str(src)],
                           capture_output=True, timeout=600)
        except (subprocess.SubprocessError, OSError) as e:
            log.append(f"  ✖ {src.name}: 7-Zip не смог распаковать ({e})")
            # ниже всё равно заберём то, что успело распаковаться
        for p in sorted(ex_dir.rglob("*")):
            if not p.is_file() or p.is_symlink():
                continue
            ext = p.suffix.lower()
            if ext not in _ARCHIVE_EXTS and ext not in _DOC_EXTS:
                skipped += 1
                continue
            size = p.stat().st_size
            if size > _MAX_INNER or not budget.allow(size):
                skipped += 1
                continue
            if ext in _ARCHIVE_EXTS:
                out += _extract_archive(p, tmpdir, log, budget, depth + 1)
            else:
                out.append(p)
    if budget.files >= _MAX_FILES or budget.bytes >= _MAX_TOTAL:
        log.append(f"  ⚠ достигнут предел распаковки "
                   f"({_MAX_FILES} файлов / {_MAX_TOTAL // (1024*1024)} МБ) — остальное в архивах пропущено")
    log.append(f"  📦 {src.name}: извлечено документов {len(out)}"
               + (f", пропущено {skipped}" if skipped else ""))
    return out


def store(files: list[str], org: str, site: str) -> tuple[list[str], list[str]]:
    """Сохранить файлы в attachments площадки (без анализа).

    Архивы (zip; rar/7z при наличии 7-Zip) распаковываются, документы из
    них принимаются как обычные файлы с префиксом «имя-архива__».
    Возвращает (имена сохранённых файлов, строки лога).
    """
    att = workspace.site_dir(org, site) / "attachments"
    names, lines = [], []
    tmpdir = Path(tempfile.mkdtemp(prefix="ecodoc_arc_"))
    budget = _Budget()
    try:
        queue: list[Path] = []
        for f in files:
            src = Path(f)
            if not src.exists():
                lines.append(f"✖ нет файла: {src}")
            elif src.suffix.lower() in _ARCHIVE_EXTS:
                queue += _extract_archive(src, tmpdir, lines, budget)
            else:
                queue.append(src)
        for src in queue:
            dest, is_new = _register(att, src)
            lines.append(f"{'＋ принят' if is_new else '= уже был'}: {dest.name}")
            names.append(dest.name)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
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
