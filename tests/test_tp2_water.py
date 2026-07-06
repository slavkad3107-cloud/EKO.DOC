"""Тесты формы 2-ТП (водхоз) и коэрции типов из формы."""
import tempfile
from pathlib import Path

from ecodoc.core import registry, serialize
from ecodoc.core.models import Organization, ReportContext, ReportPeriod


def _ctx():
    ctx = ReportContext(
        organization=Organization(name="Т", inn="7801234564", okpo="12345678"),
        period=ReportPeriod(year=2024))
    ctx.extra["water"] = {
        "intake": [{"name": "Скв.1", "type": "подземный", "volume": "12.5"}],
        "discharge": [{"receiver": "р. Нева", "quality": "нормативно-чистые",
                       "volume": "8.0"}],
        "recycled": "40"}
    return ctx


def test_tp2_water_implemented():
    registry.load_all()
    cls = registry.get("2tp-water")
    assert getattr(cls, "implemented", True)


def test_tp2_water_generates(tmp_path):
    registry.load_all()
    rep = registry.get("2tp-water")(_ctx())
    assert not [i for i in rep.validate() if i.level == "error"]
    xml = rep.render_xml(tmp_path / "w.xml")
    xlsx = rep.render_print(tmp_path / "w.xlsx")
    assert xml.exists() and xlsx.exists()
    assert "Забор" in xml.read_text(encoding="utf-8") or \
           "ЗаборВоды" in xml.read_text(encoding="utf-8")


def test_period_year_coerced_from_string():
    """Год/квартал/класс из формы приходят строками — сериализация чинит тип."""
    ctx = _ctx()
    ctx.period.year = 2024
    serialize.to_json(ctx, Path(tempfile.mkdtemp()) / "c.json")
    # смоделируем строковый год в JSON (как из формы)
    import json
    p = Path(tempfile.mkdtemp()) / "c.json"
    data = {"organization": {"inn": "7801234564"},
            "period": {"year": "2024", "quarter": "2"},
            "wastes": [{"fkko_code": "47110101521", "hazard_class": "1",
                        "generated": "0.05"}]}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    loaded = serialize.from_json(p)
    assert loaded.period.year == 2024 and isinstance(loaded.period.year, int)
    assert loaded.period.quarter == 2
    assert loaded.wastes[0].hazard_class == 1
