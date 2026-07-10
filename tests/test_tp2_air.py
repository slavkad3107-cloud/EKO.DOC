"""2-ТП (воздух) — строки 101–109 с графами потока очистки (Приказ № 661)."""
import openpyxl

from ecodoc.core import registry
from ecodoc.core.models import (Medium, Organization, Pollutant, ReportContext,
                                ReportPeriod)


def _ctx():
    return ReportContext(
        organization=Organization(name="ООО Т", inn="7801234564", okpo="12345678",
                                  oktmo="40324000"),
        period=ReportPeriod(year=2025),
        pollutants=[
            Pollutant(name="Сера диоксид", code="0330", medium=Medium.AIR, mass_norm="0.8"),
            Pollutant(name="Азота диоксид", code="0301", medium=Medium.AIR, mass_norm="1.2"),
            Pollutant(name="Углерода оксид", code="0337", medium=Medium.AIR, mass_norm="3.5"),
            Pollutant(name="Взвешенные вещества", code="2902", medium=Medium.AIR, mass_norm="0.5"),
        ])


def test_tp2_air_sections(tmp_path):
    registry.load_all()
    rep = registry.get("2tp-air")(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "air.xlsx"))
    assert wb.sheetnames == ["Титул", "Раздел 1", "Раздел 2 (специфич.)",
                             "Раздел 3 (источники)"]
    s1 = wb["Раздел 1"]
    # строки 101-109 в столбце A
    assert [s1["A" + str(r)].value for r in range(4, 13)] == \
        [101, 102, 103, 104, 105, 106, 107, 108, 109]
    # графа 6 (H): 101 Всего = 102 твёрдые + 103 газообразные; SO2/CO/NOx разнесены
    assert s1["H4"].value == 6.0            # 101 всего
    assert s1["H5"].value == 0.5            # 102 твёрдые (взвешенные)
    assert s1["H6"].value == 5.5            # 103 = 0.8+3.5+1.2
    assert s1["H7"].value == 0.8            # 104 SO2
    assert s1["H9"].value == 1.2            # 106 NOx


def test_tp2_air_no_declaration_columns(tmp_path):
    """В форме 2-ТП (воздух) не должно быть колонок норматив/лимит/сверх."""
    registry.load_all()
    rep = registry.get("2tp-air")(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "air.xlsx"))
    heads = [wb["Раздел 1"][f"{c}3"].value for c in "ABCDEFGH"]
    joined = " ".join(str(h) for h in heads)
    assert "норматив" not in joined.lower() and "лимит" not in joined.lower()
    assert "очист" in joined.lower()  # графы потока очистки
