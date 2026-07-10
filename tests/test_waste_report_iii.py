"""Отчётность по отходам III кат./МСП — общие сведения + баланс масс."""
import openpyxl

from ecodoc.core import registry
from ecodoc.core.models import (NVOSObject, Organization, ReportContext,
                                ReportPeriod, WasteFlow)


def _ctx():
    return ReportContext(
        organization=Organization(name="ООО Т", inn="7801234564", ogrn="1157847008219",
                                  okpo="12345678", oktmo="40324000"),
        period=ReportPeriod(year=2025),
        objects=[NVOSObject(code="40-0178-001234-П", category="III", address="СПб",
                            oktmo="40908000")],
        wastes=[WasteFlow(fkko_code="73310001724", name="ТКО", hazard_class=4,
                          generated="5", transferred="5")])


def test_msp_general_and_movement(tmp_path):
    registry.load_all()
    rep = registry.get("waste-report-iii")(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "msp.xlsx"))
    assert wb.sheetnames == ["Общие сведения", "Движение отходов", "Получатели"]
    # объект НВОС в общих сведениях
    assert "40-0178-001234-П" in str(wb["Общие сведения"]["B9"].value)
    # полный баланс: наличие на начало и конец присутствуют
    heads = [wb["Движение отходов"][f"{c}1"].value for c in "ABCDEFGHIJK"]
    assert "Нач. года, т" in heads and "Кон. года, т" in heads


def test_msp_xml_balance(tmp_path):
    registry.load_all()
    rep = registry.get("waste-report-iii")(_ctx())
    xml = rep.render_xml(tmp_path / "msp.xml").read_text(encoding="utf-8")
    assert "<НаличиеНачало>" in xml and "<НаличиеКонец>" in xml
    assert "<ОбъектНВОС" in xml
