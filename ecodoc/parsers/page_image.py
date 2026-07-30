"""Скан листа-источника: «откуда взяты данные».

Требование ТЗ: «При загрузке надо показывать скан фото лист откуда данные».
Исходные файлы в базе не хранятся (это отдельное требование пользователя),
поэтому сохраняем только КАРТИНКУ ЛИСТА, на котором нашлись данные:
JPEG в оттенках серого, ~60–90 КБ на лист против мегабайтов у исходника.

Снимок делается во время приёма — пока файл ещё не удалён (см.
`ecodoc/intake/intake.py`, шаг перед `_purge_sources`).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PAGES_DIR = "pages"          # подпапка площадки с картинками листов
MAX_PAGES_PER_DOC = 30       # страховка от 500-страничных томов
BUDGET_MB = 300              # предел на площадку; дальше картинки не пишем

_PDF = {".pdf"}
_IMG = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


@dataclass(frozen=True)
class Opts:
    dpi: int = 100           # разборчиво для чтения, но лист ~70 КБ
    quality: int = 58
    gray: bool = True        # сканы почти всегда ч/б — цвет не нужен
    max_px: int = 1400


def supported(src: str | Path) -> bool:
    """Умеем ли снять лист этого файла (docx/xls рендерить нечем)."""
    return Path(src).suffix.lower() in _PDF | _IMG


def pages_dir(site_dir: str | Path) -> Path:
    return Path(site_dir) / PAGES_DIR


def image_name(sha1: str, page: int) -> str:
    # 16 знаков хватает для различения и экономит длину пути Windows
    return f"{(sha1 or 'nohash')[:16]}_p{page}.jpg"


def usage_mb(site_dir: str | Path) -> float:
    d = pages_dir(site_dir)
    if not d.exists():
        return 0.0
    return sum(f.stat().st_size for f in d.glob("*.jpg")) / (1024 * 1024)


def _save_jpeg(pix, path: Path, opts: Opts) -> None:
    """Pixmap PyMuPDF → JPEG. Через Pillow, если PyMuPDF без поддержки jpg."""
    try:
        path.write_bytes(pix.tobytes("jpg", jpg_quality=opts.quality))
        return
    except (TypeError, ValueError, RuntimeError):
        pass
    from io import BytesIO

    from PIL import Image
    img = Image.open(BytesIO(pix.tobytes("png")))
    if opts.gray:
        img = img.convert("L")
    img.save(path, "JPEG", quality=opts.quality, optimize=True)


def _capture_pdf(src: Path, pages: set[int], out: Path, sha1: str,
                 opts: Opts) -> dict[int, str]:
    import fitz

    made: dict[int, str] = {}
    doc = fitz.open(src)
    try:
        gray = fitz.csGRAY if opts.gray else None
        for page_no in sorted(pages):
            if not 1 <= page_no <= doc.page_count:
                continue
            dst = out / image_name(sha1, page_no)
            if dst.exists():                     # уже снимали — не переделываем
                made[page_no] = dst.name
                continue
            page = doc[page_no - 1]
            pix = (page.get_pixmap(dpi=opts.dpi, colorspace=gray) if gray
                   else page.get_pixmap(dpi=opts.dpi))
            if max(pix.width, pix.height) > opts.max_px:      # ужать крупный лист
                scale = opts.max_px / max(pix.width, pix.height)
                pix = page.get_pixmap(dpi=int(opts.dpi * scale) or 40,
                                      colorspace=gray) if gray else \
                    page.get_pixmap(dpi=int(opts.dpi * scale) or 40)
            _save_jpeg(pix, dst, opts)
            made[page_no] = dst.name
    finally:
        doc.close()
    return made


def _capture_image(src: Path, out: Path, sha1: str, opts: Opts) -> dict[int, str]:
    from PIL import Image

    dst = out / image_name(sha1, 1)
    if dst.exists():
        return {1: dst.name}
    img = Image.open(src)
    if opts.gray:
        img = img.convert("L")
    img.thumbnail((opts.max_px, opts.max_px))
    img.save(dst, "JPEG", quality=opts.quality, optimize=True)
    return {1: dst.name}


def capture(src: str | Path, pages: set[int], site_dir: str | Path, sha1: str,
            opts: Opts | None = None, budget_mb: float = BUDGET_MB,
            max_pages: int = MAX_PAGES_PER_DOC) -> tuple[dict[int, str], str]:
    """Снять указанные листы документа. Возвращает ({лист: имя файла}, примечание).

    Примечание непустое, если что-то не сняли (лимит листов, бюджет, формат) —
    его показывают пользователю в отчёте загрузки.
    """
    src, opts = Path(src), (opts or Opts())
    if not pages:
        return {}, ""
    if not supported(src):
        return {}, f"{src.name}: изображение листа недоступно для {src.suffix}"
    if not src.exists():
        return {}, f"{src.name}: исходник уже удалён — лист не снят"
    if usage_mb(site_dir) >= budget_mb:
        return {}, (f"{src.name}: лимит хранения сканов {budget_mb:.0f} МБ исчерпан "
                    f"(Сервис → Хранение)")
    out = pages_dir(site_dir)
    out.mkdir(parents=True, exist_ok=True)
    note = ""
    wanted = sorted(pages)
    if len(wanted) > max_pages:
        note = (f"{src.name}: сняты первые {max_pages} листов из {len(wanted)} "
                f"с находками")
        wanted = wanted[:max_pages]
    try:
        if src.suffix.lower() in _PDF:
            return _capture_pdf(src, set(wanted), out, sha1, opts), note
        return _capture_image(src, out, sha1, opts), note
    except Exception as e:                       # рендер не должен рушить приём
        return {}, f"{src.name}: лист не снят ({str(e)[:80]})"


def locate(src: str | Path, page: int, quote: str) -> list[tuple]:
    """Прямоугольники цитаты на листе (в пунктах PDF) — для подсветки.

    У сканов текстового слоя нет, поэтому список будет пустым: тогда в
    интерфейсе показывается лист целиком, а цитата — подписью под ним."""
    src = Path(src)
    q = (quote or "").split("⚠")[0].strip()
    if not q or src.suffix.lower() not in _PDF or not src.exists():
        return []
    import fitz

    doc = fitz.open(src)
    try:
        if not 1 <= page <= doc.page_count:
            return []
        p = doc[page - 1]
        words = q.split()
        for needle in (" ".join(words[:8]), " ".join(words[:4]), q[:40]):
            if not needle.strip():
                continue
            found = p.search_for(needle)
            if found:
                return [tuple(r) for r in found]
        return []
    except Exception:
        return []
    finally:
        doc.close()


def gc(site_dir: str | Path, keep: set[str]) -> int:
    """Удалить картинки листов, которые больше не нужны. Возвращает число удалённых."""
    d = pages_dir(site_dir)
    if not d.exists():
        return 0
    removed = 0
    for f in d.glob("*.jpg"):
        if f.name not in keep:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed
