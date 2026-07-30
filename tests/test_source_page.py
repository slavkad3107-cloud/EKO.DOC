"""Лист-источник: постраничный разбор, снимки листов, безопасная отдача.

Требование ТЗ: «показывать скан фото лист откуда данные» при том, что сами
исходники в базе не хранятся.
"""
import json
from pathlib import Path

import pytest

from ecodoc.ai.analyzer import page_chunks, page_of_quote
from ecodoc.parsers import page_image
from ecodoc.parsers.text_extract import (ExtractedDoc, _split_blocks,
                                         _split_sheets)


def _pdf(path: Path, pages: list[str]) -> Path:
    import fitz
    doc = fitz.open()
    for text in pages:
        pg = doc.new_page()
        pg.insert_text((60, 90), text, fontsize=13, fontname="china-ss")
    doc.save(path)
    doc.close()
    return path


# ── постраничные чанки и поиск листа ─────────────────────────────────────

def test_page_chunks_pack_whole_pages():
    doc = ExtractedDoc(Path("a.pdf"), "", ["x" * 6000, "y" * 6000, "z" * 6000],
                       "pdf-text")
    chunks = page_chunks(doc)
    assert [(a, b) for _t, a, b in chunks] == [(1, 2), (3, 3)]


def test_page_chunks_split_huge_page_but_keep_number():
    doc = ExtractedDoc(Path("b.pdf"), "", ["q" * 20000], "pdf-text")
    spans = [(a, b) for _t, a, b in page_chunks(doc)]
    assert spans == [(1, 1), (1, 1)]          # обе части — та же страница


def test_page_of_quote_exact_and_fallback():
    pages = ["титул", "акт № 12, масса 0,052 т", "подписи"]
    assert page_of_quote(pages, "масса 0,052 т", (1, 3)) == (2, True)
    # цитаты нет — берём первый лист чанка, помечаем как неточный
    assert page_of_quote(pages, "выдумка", (2, 3)) == (2, False)


def test_page_kind_for_excel_and_docx():
    xl = "═ Лист: Отходы ═\n1\t2\n═ Лист: Воздух ═\n3\t4"
    sheets = _split_sheets(xl)
    assert len(sheets) == 2
    doc = ExtractedDoc(Path("c.xlsx"), xl, sheets, "xlsx", "sheet")
    assert doc.page_label(1) == "лист «Отходы»"
    assert doc.page_label(2) == "лист «Воздух»"
    blocks = _split_blocks("строка\n" * 900)
    assert len(blocks) > 1
    d2 = ExtractedDoc(Path("d.docx"), "", blocks, "docx", "block")
    assert d2.page_label(1).startswith("фрагмент 1 из")


# ── снимки листов ────────────────────────────────────────────────────────

def test_capture_only_requested_pages(tmp_path):
    src = _pdf(tmp_path / "акт.pdf", ["титул", "масса 0,052 т", "подписи"])
    site = tmp_path / "site"
    made, note = page_image.capture(src, {2}, site, "a" * 40)
    assert list(made) == [2] and not note
    files = list(page_image.pages_dir(site).glob("*.jpg"))
    assert len(files) == 1 and 0 < files[0].stat().st_size < 200_000
    # повторный вызов не перерисовывает
    mtime = files[0].stat().st_mtime_ns
    page_image.capture(src, {2}, site, "a" * 40)
    assert files[0].stat().st_mtime_ns == mtime


def test_capture_limits_and_unsupported(tmp_path):
    src = _pdf(tmp_path / "том.pdf", [f"лист {i}" for i in range(1, 6)])
    site = tmp_path / "site"
    made, note = page_image.capture(src, {1, 2, 3, 4, 5}, site, "b" * 40,
                                    max_pages=2)
    assert len(made) == 2 and "сняты первые 2" in note
    made2, note2 = page_image.capture(tmp_path / "x.docx", {1}, site, "c" * 40)
    assert made2 == {} and "недоступно" in note2
    # бюджет исчерпан — не пишем и предупреждаем
    _made3, note3 = page_image.capture(src, {1}, site, "d" * 40, budget_mb=0)
    assert "лимит хранения" in note3


def test_locate_and_gc(tmp_path):
    src = _pdf(tmp_path / "акт.pdf", ["масса 0,052 т на листе"])
    assert page_image.locate(src, 1, "масса 0,052")          # нашёл прямоугольник
    assert page_image.locate(src, 1, "выдуманный текст") == []
    site = tmp_path / "site"
    page_image.capture(src, {1}, site, "e" * 40)
    assert page_image.usage_mb(site) > 0
    assert page_image.gc(site, keep=set()) == 1              # ничего не оставляем
    assert page_image.usage_mb(site) == 0


# ── интеграция с приёмом и API ───────────────────────────────────────────

@pytest.fixture()
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    from ecodoc.core import workspace
    workspace.add_org("ТЕСТ ООО")
    workspace.add_site("ТЕСТ ООО", "Площадка")
    return "ТЕСТ ООО", "Площадка"


def test_intake_snaps_page_with_found_value(tmp_path, site):
    """E2E без ИИ: ИНН на 2-м листе → снят именно 2-й лист, исходник удалён."""
    from ecodoc.core import workspace
    from ecodoc.intake import intake, sources
    org, st = site
    src = _pdf(tmp_path / "проект.pdf",
               ["титульный лист", "Заказчик ООО «Тест», ИНН 7801234564", "приложения"])
    intake.run([str(src)], org=org, site=st, use_ai=False)

    site_dir = workspace.site_dir(org, st)
    ctx = workspace.load_context(org, st)
    assert ctx.organization.inn == "7801234564"
    assert ctx.provenance["_pages"]["проект.pdf"]["inn"]["page"] == 2
    rec = next(iter(sources.load(site_dir)["docs"].values()))
    assert rec["file"] == "проект.pdf" and rec["pages_total"] == 3
    assert list(rec["images"]) == ["2"]
    assert not (site_dir / "attachments" / "проект.pdf").exists()   # исходник убран


def test_api_source_page_rejects_traversal(tmp_path, site):
    from ecodoc.gui import server
    org, st = site
    for bad in ("../../org.json", "не-хеш", "", "a" * 8):
        with pytest.raises(ValueError):
            server.api_source_page({}, {"org": org, "site": st, "doc": bad, "page": 1})
    with pytest.raises(ValueError):                       # номер листа вне диапазона
        server.api_source_page({}, {"org": org, "site": st, "doc": "a" * 40,
                                    "page": 0})


def test_api_source_page_and_meta(tmp_path, site):
    from ecodoc.gui import server
    from ecodoc.intake import intake
    org, st = site
    src = _pdf(tmp_path / "справка.pdf", ["титул", "ИНН 7801234564"])
    intake.run([str(src)], org=org, site=st, use_ai=False)
    docs = server.api_sources({"org": org, "site": st}, {})["docs"]
    assert docs and docs[0]["found"] >= 1
    sha = docs[0]["doc"]

    meta = server.api_source_meta({}, {"org": org, "site": st, "doc": sha, "page": 2})
    assert meta["file"] == "справка.pdf" and meta["has_image"]
    assert any(f["field"] == "inn" for f in meta["found"])

    out = server.api_source_page({}, {"org": org, "site": st, "doc": sha, "page": 2})
    assert isinstance(out, server.Raw) and out.ctype == "image/jpeg"
    assert out.data[:2] == b"\xff\xd8"                    # JPEG-заголовок
    # лист без картинки — понятная ошибка, не исключение
    miss = server.api_source_page({}, {"org": org, "site": st, "doc": sha, "page": 1})
    assert isinstance(miss, dict) and "не сохранён" in miss["error"]
