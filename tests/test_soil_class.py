"""Грунт: категория почвы по СанПиН + класс отхода по № 536 — двойная оценка."""
from pathlib import Path

import pytest
from docx import Document

from ecodoc.development.soil_class import SoilComponent, assess, generate


def test_clean_soil_needs_background():
    """Без фона «чистую» не присваиваем — только «допустимая» с оговоркой."""
    r = assess([SoilComponent("свинец", ci=20, norm=130)])
    assert r.category == "допустимая"
    assert r.zc is None
    assert any("Zc не считается" in w for w in r.warnings)


def test_clean_soil_with_background():
    r = assess([SoilComponent("свинец", ci=10, norm=130, background=15)])
    assert r.category == "чистая" and r.zc == 0.0


def test_exceedance_moves_category():
    r = assess([SoilComponent("нефтепродукты", ci=2500, norm=1000)])
    assert r.category == "умеренно опасная"
    assert r.exceedances[0][0] == "нефтепродукты"
    big = assess([SoilComponent("нефтепродукты", ci=8000, norm=1000)])
    assert big.category == "опасная"                # кратность > 5


def test_zc_thresholds():
    # Zc = 20/1 − 0 = 20 → умеренно опасная (16 ≤ Zc < 32)
    r = assess([SoilComponent("цинк", ci=20, norm=220, background=1)])
    assert r.zc == 20 and r.category == "умеренно опасная"
    # Zc = 140 → чрезвычайно опасная
    x = assess([SoilComponent("цинк", ci=140, norm=100000, background=1)])
    assert x.category == "чрезвычайно опасная"


def test_hazard_class_from_wi_with_mineral_rest():
    """Wi заданы → считается и класс отхода; остаток массы — мин. основа."""
    r = assess([SoilComponent("нефтепродукты", ci=50000, norm=1000, wi=100)])
    # K = 50000/100 + 950000/1e6 = 500.95 → IV класс
    assert r.hazard_class == 4
    assert 500 < r.k_total < 502


def test_unknown_norm_warns():
    r = assess([SoilComponent("неведомое вещество", ci=100)])
    assert any("нет ПДК/ОДК" in w for w in r.warnings)


def test_document_contains_both_assessments(tmp_path):
    p = generate([SoilComponent("нефтепродукты", ci=2500, norm=1000,
                                background=100, wi=100)],
                 tmp_path / "грунт.docx", site_label="скв. 1, 0,0–0,2 м",
                 basis="протокол КХА № 77-26")
    text = "\n".join(par.text for par in Document(str(p)).paragraphs)
    assert "СанПиН 1.2.3685-21" in text and "№ 536" in text
    assert "КАТЕГОРИЯ ЗАГРЯЗНЕНИЯ" in text
    assert "КЛАСС ОПАСНОСТИ ОТХОДА" in text
    assert "скв. 1" in text and "77-26" in text


def test_api_soil_class(tmp_path, monkeypatch):
    monkeypatch.setenv("ECODOC_RESULTS", str(tmp_path / "res"))
    from ecodoc.gui import server
    out = server.api_soil_class({}, {
        "components": [{"name": "свинец", "ci": 300, "norm": 130,
                        "background": 15}],
        "save": 1, "site_label": "проба/1"})
    assert out["category"] in ("умеренно опасная", "опасная")
    assert Path(out["path"]).exists()
    err = server.api_soil_class({}, {"components": []})
    assert "error" in err and "norms" in err
