"""«Табличка по отходам» (бланк пользователя): т/м³, группировка по классам."""
from decimal import Decimal

import openpyxl
import pytest

from ecodoc.core import waste_table
from ecodoc.core.models import ReportContext, WasteAct, WasteFlow


@pytest.fixture()
def ctx():
    c = ReportContext()
    c.organization.short_name = "ООО «Тест»"
    c.period.year = 2025
    c.wastes = [
        WasteFlow(fkko_code="73310001724", name="Мусор офисный", hazard_class=4,
                  generated=Decimal("6.39")),
        WasteFlow(fkko_code="81290101724", name="Мусор от сноса", hazard_class=4,
                  generated=Decimal("280.3")),
        WasteFlow(fkko_code="92175112395", name="Осадок мойки", hazard_class=5,
                  generated=Decimal("4.66")),
    ]
    c.waste_acts = [WasteAct(fkko_code="81290101724", name="Мусор от сноса",
                             mass=Decimal("280.3"), density=Decimal("0.647"),
                             operation="размещение", date="01.03.2025")]
    return c


def _cells(path):
    ws = openpyxl.load_workbook(path)["расчет"]
    return [[c.value for c in row] for row in ws.iter_rows()]


def test_rows_grouped_and_volume_from_density(ctx):
    rows = waste_table.rows(ctx)
    assert [r["hazard"] for r in rows] == [4, 4, 5]
    demo = next(r for r in rows if r["fkko"] == "81290101724")
    assert demo["density"] == pytest.approx(0.647)
    assert demo["volume"] == pytest.approx(280.3 / 0.647, rel=1e-6)
    office = next(r for r in rows if r["fkko"] == "73310001724")
    assert office["volume"] == 0            # плотности нет — м³ не выдумываем
    assert office["note"] == "делаем паспорт"


def test_xlsx_layout_matches_user_blank(ctx, tmp_path):
    grid = _cells(waste_table.build_xlsx(ctx, tmp_path / "т.xlsx"))
    flat = [str(v) for row in grid for v in row if v is not None]
    assert "ООО «Тест»" in flat
    assert "Код ФККО" in flat and "т" in flat and "м³" in flat
    assert "7 33 100 01 72 4" in flat        # код с пробелами, как в бланке
    assert "ИТОГО 4 класс опасности" in flat
    assert "ИТОГО 5 класс опасности" in flat
    assert "ВСЕГО" in flat
    # итог 4 класса = 6.39 + 280.3
    for row in grid:
        if row[0] == "ИТОГО 4 класс опасности":
            assert row[2] == pytest.approx(286.69)
        if row[0] == "ВСЕГО":
            assert row[2] == pytest.approx(291.35)


def test_api_waste_table(tmp_path, monkeypatch):
    from ecodoc.core import workspace
    from ecodoc.gui import server
    monkeypatch.setenv("ECODOC_RESULTS", str(tmp_path / "res"))
    workspace.add_org("Т")
    workspace.add_site("Т", "Пл")
    c = workspace.load_context("Т", "Пл")
    c.wastes = [WasteFlow(fkko_code="73310001724", name="Мусор",
                          hazard_class=4, generated=Decimal("1.5"))]
    workspace.save_context("Т", "Пл", c)
    out = server.api_waste_table({}, {"org": "Т", "site": "Пл"})
    assert out["rows"] == 1 and out["no_density"] == 1
    assert out["path"].endswith(".xlsx")

    # пустая площадка отвечает ошибкой, а не пустым файлом
    workspace.add_site("Т", "Пл2")
    err = server.api_waste_table({}, {"org": "Т", "site": "Пл2"})
    assert "error" in err
