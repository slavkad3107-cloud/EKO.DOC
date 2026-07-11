"""Первичный ввод по отходам — справки-акты → движение (агрегация)."""
import json

from ecodoc.core import serialize
from ecodoc.core.models import WasteAct
from ecodoc.core.waste_agg import aggregate_acts


def test_aggregate_by_fkko():
    acts = [
        WasteAct(name="Лампы", fkko_code="47110101521", hazard_class=1, mass="0.1",
                 operation="обезвреживание", receiver="ЭП Меркурий"),
        WasteAct(name="Лампы", fkko_code="47110101521", hazard_class=1, mass="0.05",
                 operation="обезвреживание", receiver="ЭП Меркурий"),
        WasteAct(name="Мусор", fkko_code="73310001724", hazard_class=4, mass="16",
                 operation="размещение", receiver="полигон ТБО"),
    ]
    wastes, recv = aggregate_acts(acts)
    assert len(wastes) == 2
    lamps = next(w for w in wastes if w.fkko_code == "47110101521")
    assert float(lamps.generated) == 0.15 and float(lamps.transferred) == 0.15
    trash = next(w for w in wastes if w.fkko_code == "73310001724")
    assert float(trash.transferred_burial) == 16.0   # размещение → захоронение
    # получатели уникальны по (код, получатель)
    assert len(recv) == 2


def test_from_json_computes_wastes_from_acts(tmp_path):
    data = {
        "organization": {"name": "Т", "inn": "7814167570"},
        "period": {"year": 2025},
        "waste_acts": [
            {"name": "Мусор", "fkko_code": "73310001724", "hazard_class": 4,
             "mass": "16", "operation": "размещение", "receiver": "полигон"},
        ],
    }
    p = tmp_path / "ctx.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ctx = serialize.from_json(p)
    # движение рассчитано из актов
    assert len(ctx.waste_acts) == 1
    assert len(ctx.wastes) == 1
    assert float(ctx.wastes[0].generated) == 16.0
    assert ctx.extra.get("waste_receivers")


def test_acts_are_authoritative(tmp_path):
    """Акты первичны: заданы акты → движение считается из них (перетирает)."""
    data = {
        "organization": {"name": "Т", "inn": "7814167570"},
        "period": {"year": 2025},
        "wastes": [{"fkko_code": "73310001724", "name": "М", "hazard_class": 4,
                    "generated": "5"}],
        "waste_acts": [{"fkko_code": "73310001724", "name": "М", "hazard_class": 4,
                        "mass": "16", "operation": "размещение"}],
    }
    p = tmp_path / "ctx.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ctx = serialize.from_json(p)
    assert float(ctx.wastes[0].generated) == 16.0   # пересчитано из актов


def test_analyzer_extracts_acts():
    """ИИ-анализатор кладёт disposal_acts в ctx.waste_acts (с дедупом)."""
    from ecodoc.core.models import ReportContext, Organization, ReportPeriod
    from ecodoc.ai.analyzer import _merge_acts, ExtractionReport
    ctx = ReportContext(organization=Organization(name="Т", inn="7814167570"),
                        period=ReportPeriod(year=2025))
    data = {"disposal_acts": [
        {"date": "15.03.2025", "counterparty": "Меркурий", "carrier": "Спецтранс",
         "fkko": "4 71 101 01 52 1", "waste_name": "Лампы", "mass_t": "0.1",
         "hazard_class": 1, "operation": "обезвреживание"},
    ]}
    _merge_acts(ctx, data, "справка.pdf", ExtractionReport())
    _merge_acts(ctx, data, "справка.pdf", ExtractionReport())   # дедуп
    assert len(ctx.waste_acts) == 1
    a = ctx.waste_acts[0]
    assert a.fkko_code == "47110101521" and float(a.mass) == 0.1
    assert a.operation == "обезвреживание" and a.carrier == "Спецтранс"


def test_no_acts_keeps_manual(tmp_path):
    """Актов нет — заполненное вручную движение сохраняется."""
    data = {
        "organization": {"name": "Т", "inn": "7814167570"},
        "period": {"year": 2025},
        "wastes": [{"fkko_code": "73310001724", "name": "М", "hazard_class": 4,
                    "generated": "5"}],
    }
    p = tmp_path / "ctx.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ctx = serialize.from_json(p)
    assert float(ctx.wastes[0].generated) == 5.0
