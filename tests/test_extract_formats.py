"""Чтение Excel/XML/RTF и сведение ошибок приёма."""
import openpyxl

from ecodoc.parsers.text_extract import extract
from ecodoc.intake.intake import _err_reason
from pathlib import Path


def test_xlsx_read(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ИНН", "7801234564"])
    ws.append(["ФККО", "47110101521"])
    wb.save(tmp_path / "t.xlsx")
    doc = extract(tmp_path / "t.xlsx")
    assert "7801234564" in doc.text and "47110101521" in doc.text
    assert doc.method == "xlsx"


def test_xml_read(tmp_path):
    (tmp_path / "t.xml").write_text(
        '<Файл><СведНП ИННЮЛ="7801234564"/></Файл>', encoding="utf-8")
    assert "7801234564" in extract(tmp_path / "t.xml").text


def test_rtf_read(tmp_path):
    (tmp_path / "t.rtf").write_text(r"{\rtf1 ИНН 7801234564 договор}",
                                    encoding="utf-8")
    assert "7801234564" in extract(tmp_path / "t.rtf").text


def test_err_reason_grouping():
    assert "Tesseract" in _err_reason("tesseract is not installed", Path("a.jpg"))
    assert "не поддерживается" in _err_reason("Неподдерживаемый формат: .zzz",
                                              Path("a.zzz"))
    assert ".doc" in _err_reason("Не удалось прочитать .doc (Word ...)",
                                 Path("a.doc"))
