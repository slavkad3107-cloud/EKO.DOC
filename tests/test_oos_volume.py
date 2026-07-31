"""Раздел ООС (ПП РФ № 87, п. 25): состав, пропуск лишних сред, пробелы."""
from decimal import Decimal

import pytest
from docx import Document

from ecodoc.core.models import (Medium, NVOSObject, Pollutant, ReportContext,
                                WasteFlow)
from ecodoc.development import oos


@pytest.fixture()
def ctx():
    c = ReportContext()
    c.organization.name = "ООО «Тест»"
    c.organization.inn = "7806001144"
    c.organization.address = "СПб, ул. Тестовая, 1"
    c.period.year = 2025
    c.objects = [NVOSObject(code="41-0247-005048-П", category="III",
                            address="Промзона Янино")]
    c.wastes = [WasteFlow(fkko_code="73310001724", name="Мусор офисный",
                          hazard_class=4, generated=Decimal("1.9"),
                          transferred=Decimal("1.9"))]
    air = Pollutant(code="0301", name="Азота диоксид", mass_norm=Decimal("0.412"))
    air.medium = Medium.AIR
    c.pollutants = [air]
    return c


def _text(path):
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return "\n".join(parts)


def test_media_detected_from_data(ctx):
    assert oos.media(ctx) == {"air", "waste"}       # сбросов нет


def test_document_has_all_required_sections(ctx, tmp_path):
    text = _text(oos.generate(ctx, tmp_path / "оос.docx"))
    for _key, title, medium in oos.SECTIONS:
        if medium == "water":
            continue
        assert title in text, title
    assert "ООО «Тест»" in text and "41-0247-005048-П" in text
    assert "Азота диоксид" in text and "0.412" in text
    assert "Мусор офисный" in text and "73310001724" in text
    assert "постановлением Правительства РФ" in text


def test_section_skipped_when_no_such_impact(ctx, tmp_path):
    """Сбросов нет — пункт по воде в содержании помечен, мероприятий нет."""
    text = _text(oos.generate(ctx, tmp_path / "оос.docx"))
    assert "не требуется" in text
    assert "оборотному" not in text
    assert "централизованную систему" not in text   # мероприятия по воде


def test_water_section_appears_when_discharges_exist(ctx, tmp_path):
    w = Pollutant(code="1000", name="Взвешенные вещества",
                  mass_norm=Decimal("0.3"))
    w.medium = Medium.WATER
    ctx.pollutants.append(w)
    text = _text(oos.generate(ctx, tmp_path / "оос.docx"))
    assert "Взвешенные вещества" in text
    assert "централизованную систему" in text


def test_gaps_name_external_data(ctx):
    gaps = oos.gaps(ctx)
    assert any("рассеивания" in g for g in gaps)         # УПРЗА не подменяем
    assert any("изыскания" in g for g in gaps)
    assert not any("наименование организации" in g for g in gaps)


def test_gaps_report_empty_object():
    empty = ReportContext()
    gaps = oos.gaps(empty)
    assert any("наименование организации" in g for g in gaps)
    assert any("не заведён объект" in g for g in gaps)
    assert any("нечем наполнять" in g for g in gaps)


def test_document_generated_even_without_data(tmp_path):
    """Пустой объект: документ всё равно собирается, но с явными пометками."""
    text = _text(oos.generate(ReportContext(), tmp_path / "пустой.docx"))
    assert "[требуется" in text
    assert oos.TITLE.split("(")[0].strip() in text


def test_registered_as_dev_document():
    from ecodoc.core import registry
    registry.load_all()
    form = registry.all_reports()["oos"]
    assert form.domain == "development" and form.devdoc is True
