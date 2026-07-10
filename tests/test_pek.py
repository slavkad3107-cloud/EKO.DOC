"""Отчёт по ПЭК — структура по Приказу № 173 (разделы 1–6)."""
import openpyxl

from ecodoc.core import registry
from ecodoc.core.models import (NVOSObject, Organization, Pollutant, Medium,
                                ReportContext, ReportPeriod, WasteFlow)


def _ctx(year=2025):
    return ReportContext(
        organization=Organization(name="ООО Т", inn="7801234564", kpp="780101001"),
        period=ReportPeriod(year=year),
        objects=[NVOSObject(code="40-0178-001234-П", category="III", oktmo="40908000")],
        pollutants=[Pollutant(name="Азота диоксид", code="0301", medium=Medium.AIR,
                              mass_norm="1.0")],
        wastes=[WasteFlow(fkko_code="73310001724", name="ТКО", hazard_class=4,
                          generated="5", transferred="5")],
        extra={"pek": {"program_number": "1-ПЭК", "lab": "ООО Лаб (RA.RU.21XX)"},
               "ppp": [{"name": "Шлак", "formed": "10", "used": "8"}]})


def test_pek_six_sections(tmp_path):
    registry.load_all()
    rep = registry.get("pek")(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "pek.xlsx"))
    assert wb.sheetnames == ["Титул", "Раздел 1", "Раздел 2 (воздух)",
                             "Раздел 3 (вода)", "Раздел 4 (отходы)",
                             "Раздел 5 (ППП)", "Раздел 6 (искусств. грунты)"]
    # Раздел 5 наполнен из extra.ppp
    assert wb["Раздел 5 (ППП)"]["B4"].value == "Шлак"


def test_pek_xml_has_new_sections(tmp_path):
    registry.load_all()
    rep = registry.get("pek")(_ctx())
    xml = rep.render_xml(tmp_path / "pek.xml").read_text(encoding="utf-8")
    assert "ПобочныеПродуктыПроизводства" in xml
    assert "ИскусственныеГрунтыТКО" in xml
