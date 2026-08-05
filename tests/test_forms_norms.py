"""Сверка бланков-образцов с НПА: признаки формы, давность, интернет."""
import os
import time
from pathlib import Path

import openpyxl
import pytest

from ecodoc.core import forms_norms


def _blank(path: Path, cells: list[str]):
    wb = openpyxl.Workbook()
    ws = wb.active
    for i, text in enumerate(cells, start=1):
        ws.cell(row=i, column=1, value=text)
    wb.save(path)
    return path


def test_marks_found_in_good_blank(tmp_path):
    p = _blank(tmp_path / "журнал.xlsx",
               ["Обобщенные данные учета в области обращения с отходами",
                "Код ФККО"])
    v = forms_norms.check_blank("waste-movement", p)
    assert v.ok and v.level == "ok"
    assert "1028" in v.npa


def test_wrong_blank_flagged(tmp_path):
    p = _blank(tmp_path / "не_то.xlsx", ["Совсем другой документ про рыбалку"])
    v = forms_norms.check_blank("waste-movement", p)
    assert not v.ok and v.level == "error"
    assert any("не найдены обязательные признаки" in n for n in v.notes)


def test_old_blank_warns_about_redaction(tmp_path):
    p = _blank(tmp_path / "декларация.xlsx", ["Декларация о плате за НВОС"])
    old = time.mktime((2021, 1, 15, 0, 0, 0, 0, 0, -1))
    os.utime(p, (old, old))                      # файл 2021 года
    v = forms_norms.check_blank("declaration-nvos", p)   # редакция 2023
    assert v.ok and v.level == "warn"
    assert any("действующая редакция" in n for n in v.notes)


def test_html_blank_from_lkpp_is_read(tmp_path):
    """Бланки из ЛКПП сохраняются страницей — теги снимаем сами."""
    p = tmp_path / "декларация.html"
    p.write_text("<html><head><style>b{}</style></head><body>"
                 "<h1>Декларация о плате за негативное воздействие</h1>"
                 "</body></html>", encoding="utf-8")
    v = forms_norms.check_blank("declaration-nvos", p)
    assert v.ok and v.level == "ok" and not v.notes


def test_scan_without_text_layer_is_warn_not_error(tmp_path):
    """У скана PyMuPDF отдаёт одни переносы строк — это не «чужой бланк»."""
    p = tmp_path / "скан.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    monkey = getattr(forms_norms, "_blank_text")
    forms_norms._blank_text = lambda path, limit=20000: "\n\n\n\n"
    try:
        v = forms_norms.check_blank("waste-passport", p)
    finally:
        forms_norms._blank_text = monkey
    assert v.ok and v.level == "warn"
    assert any("нет текстового слоя" in n for n in v.notes)


def test_unknown_form_is_honest(tmp_path):
    p = _blank(tmp_path / "х.xlsx", ["что-то"])
    v = forms_norms.check_blank("nds", p)
    assert v.level == "warn"
    assert any("НПА в реестре не описан" in n for n in v.notes)


def test_check_all_scans_forms_folder(tmp_path, monkeypatch):
    forms = tmp_path / "Формы"
    d = forms / "Отчетность" / "Движение отходов 1028"
    d.mkdir(parents=True)
    _blank(d / "журнал.xlsx", ["Обобщенные данные учета", "отходы"])
    monkeypatch.setenv("ECODOC_FORMS", str(forms))
    out = forms_norms.check_all(online=False)
    assert out["checked_online"] is False
    codes = [v["code"] for v in out["verdicts"]]
    assert "waste-movement" in codes
    good = next(v for v in out["verdicts"] if v["code"] == "waste-movement")
    assert good["ok"]


def test_check_all_online_reports_changes(tmp_path, monkeypatch):
    forms = tmp_path / "Формы"
    d = forms / "Отчетность" / "Движение отходов 1028"
    d.mkdir(parents=True)
    _blank(d / "журнал.xlsx", ["учет отходов"])
    monkeypatch.setenv("ECODOC_FORMS", str(forms))

    from ecodoc.watch import watcher
    monkeypatch.setattr(watcher, "load_sources", lambda: [
        {"id": "fkko", "name": "ФККО", "url": "http://х",
         "forms": ["waste-movement"]},
        {"id": "чужой", "name": "не наш", "url": "http://y", "forms": ["pek"]}])
    seen = []

    def fake_check(src, save=True):
        seen.append((src["id"], save))
        return {"id": src["id"], "name": src["name"], "status": "changed",
                "detail": "снимок от 2026-07-01 отличается"}
    monkeypatch.setattr(watcher, "check_source", fake_check)

    out = forms_norms.check_all(online=True)
    assert out["checked_online"] and out["changed"]
    assert seen == [("fkko", False)]         # чужие не дёргаем; снимок не едим
    assert "отличается" in out["changed"][0]


def test_api_forms_norms(tmp_path, monkeypatch):
    forms = tmp_path / "Формы"
    forms.mkdir()
    monkeypatch.setenv("ECODOC_FORMS", str(forms))
    from ecodoc.gui import server
    out = server.api_forms_norms({}, {})
    assert out["verdicts"] == [] and not out["checked_online"]
