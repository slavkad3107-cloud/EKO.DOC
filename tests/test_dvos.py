"""ДВОС (ст. 31.2 ФЗ-7, приказ МПР от 19.03.2025 № 117): состав, данные, пробелы."""
from decimal import Decimal

import pytest
from docx import Document

from ecodoc.core.models import (Medium, NVOSObject, Pollutant, ReportContext,
                                WasteFlow)
from ecodoc.development import dvos


@pytest.fixture()
def ctx():
    c = ReportContext()
    c.organization.name = "ООО «Тест»"
    c.organization.inn = "7806001144"
    c.organization.ogrn = "1047855175785"
    c.organization.okved = "38.11 Сбор неопасных отходов"
    c.organization.address = "СПб, ул. Тестовая, 1"
    c.period.year = 2026
    c.objects = [NVOSObject(code="40-0178-001234-П", category="II",
                            address="Промзона Парнас")]
    air = Pollutant(code="0301", name="Азота диоксид",
                    mass_norm=Decimal("0.412"))
    air.medium = Medium.AIR
    water = Pollutant(code="1000", name="Взвешенные вещества",
                      mass_norm=Decimal("0.3"), mass_over=Decimal("0.05"))
    water.medium = Medium.WATER
    c.pollutants = [air, water]
    c.wastes = [WasteFlow(fkko_code="73310001724", name="Мусор офисный",
                          hazard_class=4, generated=Decimal("1.9"),
                          transferred=Decimal("1.9"))]
    c.extra["dvos"] = {
        "products": [{"name": "Изделия пластмассовые", "volume": 120,
                      "unit": "т"}],
        "measures": [{"name": "Установка циклона", "start": "2024",
                      "end": "2025", "cost": 500, "result": "снижение выбросов"}],
        "accidents": [],
    }
    c.extra["pek"] = {"approved_date": "10.01.2026",
                      "points": [{"medium": "воздух", "point": "ИЗАВ № 1",
                                  "indicators": "NO2", "frequency": "1 раз/год"}]}
    return c


def _text(path):
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return "\n".join(parts)


def test_all_form_sections_present(ctx, tmp_path):
    """Все разделы формы приказа № 117 и реквизиты НПА — в документе."""
    text = _text(dvos.generate(ctx, tmp_path / "двос.docx"))
    for _key, title in dvos.SECTIONS:
        assert title in text, title
    assert "19.03.2025 № 117" in text          # действующая форма
    assert "31.2" in text and "7-ФЗ" in text   # закон-основание
    assert "11.10.2018 № 509" in text          # явно помечен как заменённый


def test_tables_filled_from_context(ctx, tmp_path):
    text = _text(dvos.generate(ctx, tmp_path / "двос.docx"))
    assert "ООО «Тест»" in text and "40-0178-001234-П" in text
    assert "38.11" in text                                   # ОКВЭД на титуле
    assert "Азота диоксид" in text and "0.412" in text       # раздел IV
    assert "Взвешенные вещества" in text and "0.35" in text  # раздел V, сумма
    assert "Мусор офисный" in text and "73310001724" in text # раздел VI
    assert "Изделия пластмассовые" in text                   # раздел I
    assert "Установка циклона" in text                       # раздел II
    assert "ИЗАВ № 1" in text and "10.01.2026" in text       # раздел VII


def test_period_is_seven_years(ctx, tmp_path):
    assert dvos.declared_period(ctx) == (2026, 2032)
    text = _text(dvos.generate(ctx, tmp_path / "двос.docx"))
    assert "2026–2032" in text
    assert "один раз в семь лет" in text


def test_accidents_empty_list_means_none_happened(ctx, tmp_path):
    """Пустой список аварий — подтверждённое «не было», не пробел."""
    text = _text(dvos.generate(ctx, tmp_path / "двос.docx"))
    assert "не зафиксировано" in text
    assert not any("авариях и инцидентах" in g for g in dvos.gaps(ctx))


def test_accidents_absent_is_a_gap(ctx, tmp_path):
    del ctx.extra["dvos"]["accidents"]
    assert dvos.accidents(ctx) is None
    assert any("авариях и инцидентах" in g for g in dvos.gaps(ctx))
    text = _text(dvos.generate(ctx, tmp_path / "двос.docx"))
    assert "авариях и инцидентах" in text and "[требуется:" in text


def test_gaps_markers_match_document(ctx, tmp_path):
    """Каждый пробел «требуется: …» продублирован пометкой в тексте."""
    text = _text(dvos.generate(ctx, tmp_path / "двос.docx"))
    for g in dvos.gaps(ctx):
        if g.startswith("требуется:"):
            assert f"[{g}]" in text, g


def test_wrong_category_reported(ctx):
    ctx.objects[0].category = "III"
    assert any("II категории" in g for g in dvos.gaps(ctx))


def test_empty_context_still_generates_with_markers(tmp_path):
    empty = ReportContext()
    text = _text(dvos.generate(empty, tmp_path / "пусто.docx"))
    assert "[требуется" in text
    assert dvos.TITLE.upper() in text
    gaps = dvos.gaps(empty)
    assert any("наименование организации" in g for g in gaps)
    assert any("объект НВОС" in g for g in gaps)
    assert any("нечем наполнять" in g for g in gaps)
