"""Экспорт печатных форм (.xlsx/.docx) в итоговый PDF.

РПН принимает XML, поэтому PDF — это «снимок» для архива, подписи и клиента.
Конвертация по цепочке: MS Office ≥2007 через COM → LibreOffice (soffice)
→ собственный текстовый снимок через PyMuPDF (точная вёрстка не гарантируется,
но содержимое и кириллица сохраняются полностью).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PDF_XLTYPE = 0        # xlTypePDF
WD_PDF = 17           # wdFormatPDF


def _find_cyr_font() -> str:
    """Найти системный TTF с кириллицей (для текстового PDF-снимка)."""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [Path(windir) / "Fonts" / n
                  for n in ("arial.ttf", "calibri.ttf", "tahoma.ttf",
                            "segoeui.ttf")]
    candidates += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                   Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


def _office_convert(src: Path, dst: Path) -> bool:
    try:
        import win32com.client  # pywin32
    except ImportError:
        return False
    src, dst = src.resolve(), dst.resolve()
    try:
        if src.suffix.lower() in (".xlsx", ".xls"):
            app = win32com.client.DispatchEx("Excel.Application")
            app.Visible = False
            app.DisplayAlerts = False        # без модальных диалогов (иначе висим)
            app.AutomationSecurity = 3       # msoAutomationSecurityForceDisable: без VBA
            try:
                wb = app.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True)
                wb.ExportAsFixedFormat(PDF_XLTYPE, str(dst))
                wb.Close(False)
                wb = None
            finally:
                app.Quit()
                app = None
            return dst.exists()
        if src.suffix.lower() in (".docx", ".doc"):
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible = False
            app.DisplayAlerts = 0            # wdAlertsNone
            app.AutomationSecurity = 3       # без исполнения макросов
            try:
                doc = app.Documents.Open(str(src), ReadOnly=True,
                                         AddToRecentFiles=False)
                doc.SaveAs(str(dst), FileFormat=WD_PDF)
                doc.Close(False)
                doc = None
            finally:
                app.Quit()
                app = None
            return dst.exists()
    except Exception:
        return False
    return False


def _soffice_convert(src: Path, dst: Path) -> bool:
    soffice = shutil.which("soffice") or shutil.which("soffice.exe")
    if not soffice:
        return False
    try:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                        "--outdir", str(dst.parent), str(src)],
                       check=True, capture_output=True, timeout=180)
    except (subprocess.SubprocessError, OSError):
        return False
    produced = dst.parent / (src.stem + ".pdf")
    if produced.exists() and produced != dst:
        produced.replace(dst)
    return dst.exists()


def _iter_lines(src: Path):
    """Содержимое xlsx/docx построчно (для текстового PDF-снимка)."""
    suf = src.suffix.lower()
    if suf in (".xlsx", ".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
        for ws in wb.worksheets:
            if len(wb.worksheets) > 1:
                yield f"═══ Лист: {ws.title} ═══"
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c) for c in row]
                while cells and not cells[-1]:
                    cells.pop()
                yield "  ".join(cells) if cells else ""
    elif suf == ".docx":
        import docx
        for para in docx.Document(str(src)).paragraphs:
            yield para.text
    else:
        raise RuntimeError(f"снимок PDF не поддерживает {suf}")


def _fitz_snapshot(src: Path, dst: Path) -> bool:
    """Текстовый PDF-снимок средствами PyMuPDF — без Office вообще."""
    try:
        import fitz
    except ImportError:
        return False
    font = _find_cyr_font()
    if not font:
        return False  # helv не умеет кириллицу — снимок был бы из «?»
    try:
        doc = fitz.open()
        page = doc.new_page()  # A4
        y, size, margin = 40.0, 9.0, 36.0
        kwargs = {"fontname": "F0", "fontfile": font}
        for line in _iter_lines(src):
            if y > page.rect.height - margin:
                page = doc.new_page()
                y = 40.0
            page.insert_text((margin, y), line[:200], fontsize=size, **kwargs)
            y += size * 1.45
        doc.save(str(dst))
        doc.close()
        return dst.exists()
    except Exception:
        return False


def to_pdf(src: str | Path, dst: str | Path | None = None) -> Path:
    """Сконвертировать .xlsx/.docx в PDF рядом с исходником (или в dst)."""
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(src)
    dst = Path(dst) if dst else src.with_suffix(".pdf")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if _office_convert(src, dst) or _soffice_convert(src, dst) \
            or _fitz_snapshot(src, dst):
        return dst
    raise RuntimeError(
        "Не удалось сконвертировать в PDF: нужен MS Office ≥2007 (pip install "
        "pywin32), LibreOffice (soffice в PATH) или PyMuPDF для снимка.")
