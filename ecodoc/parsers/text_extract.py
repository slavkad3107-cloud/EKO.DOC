"""Извлечение текста из приложенных документов: pdf / docx / doc / jpg / png.

Все «тяжёлые» библиотеки импортируются лениво, чтобы отсутствие, например,
Tesseract не ломало работу с PDF/DOCX.
"""
from __future__ import annotations

from pathlib import Path


class ExtractedDoc:
    def __init__(self, path: Path, text: str, pages: list[str], method: str):
        self.path = Path(path)
        self.text = text
        self.pages = pages          # текст постранично (для провенанса)
        self.method = method        # как извлекли: pdf-text / pdf-ocr / docx / ocr

    def __repr__(self) -> str:
        return f"<ExtractedDoc {self.path.name} method={self.method} chars={len(self.text)}>"


def extract(path: str | Path, ocr: bool = True) -> ExtractedDoc:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(p, ocr=ocr)
    if suffix in (".docx",):
        return _extract_docx(p)
    if suffix in (".doc",):
        return _extract_doc(p)
    if suffix in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"):
        return _extract_image(p)
    if suffix in (".txt",):
        text = p.read_text(encoding="utf-8", errors="replace")
        return ExtractedDoc(p, text, [text], "txt")
    raise ValueError(f"Неподдерживаемый формат: {suffix}")


def _extract_pdf(p: Path, ocr: bool) -> ExtractedDoc:
    import fitz  # PyMuPDF

    doc = fitz.open(p)
    pages = [page.get_text("text") for page in doc]
    text = "\n".join(pages)
    method = "pdf-text"
    # скан без текстового слоя -> OCR постранично
    if ocr and len(text.strip()) < 40:
        ocr_pages = []
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            ocr_pages.append(_ocr_pixmap(pix))
        pages = ocr_pages
        text = "\n".join(pages)
        method = "pdf-ocr"
    doc.close()
    return ExtractedDoc(p, text, pages, method)


def _extract_docx(p: Path) -> ExtractedDoc:
    from docx import Document

    d = Document(str(p))
    parts = [par.text for par in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            parts.append("\t".join(cell.text for cell in row.cells))
    text = "\n".join(parts)
    return ExtractedDoc(p, text, [text], "docx")


def _extract_doc(p: Path) -> ExtractedDoc:
    # старый .doc: пробуем через Word COM (Windows), иначе подсказываем конвертацию
    try:
        import win32com.client  # type: ignore

        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(str(p))
        text = doc.Content.Text
        doc.Close(False)
        word.Quit()
        return ExtractedDoc(p, text, [text], "doc-com")
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            f"Не удалось прочитать .doc ({exc}). "
            f"Сконвертируйте {p.name} в .docx или .pdf."
        ) from exc


def _extract_image(p: Path) -> ExtractedDoc:
    from PIL import Image

    text = _ocr_image(Image.open(p))
    return ExtractedDoc(p, text, [text], "ocr")


def _ocr_image(img) -> str:
    import pytesseract

    return pytesseract.image_to_string(img, lang="rus+eng")


def _ocr_pixmap(pix) -> str:
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(pix.tobytes("png")))
    return _ocr_image(img)
