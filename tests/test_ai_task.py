"""Доп. задание ИИ по разделу: срез данных, применение ответа, защита базы."""
import json
from decimal import Decimal

from ecodoc.ai import task
from ecodoc.core.models import (Medium, NVOSObject, Pollutant, ReportContext,
                                WasteAct, WasteFlow)


def _ctx():
    ctx = ReportContext()
    ctx.organization.name = "ИП Миних Елена Анатольевна"
    ctx.organization.inn = "780600114472"
    ctx.period.year = 2025
    ctx.objects = [NVOSObject(code="41-0247-005048-П", name="Промзона Янино")]
    ctx.wastes = [WasteFlow(fkko_code="73310001724", name="Мусор офисный",
                            hazard_class=4, generated=Decimal("1.9"))]
    ctx.waste_acts = [WasteAct(name="Мусор офисный", fkko_code="73310001724",
                               mass=Decimal("1.9"), date="20.03.2025")]
    air = Pollutant(code="0301", name="Азота диоксид", mass_norm=Decimal("0.412"))
    air.medium = Medium.AIR
    wat = Pollutant(code="0007", name="Взвешенные вещества",
                    mass_norm=Decimal("0.05"))
    wat.medium = Medium.WATER
    ctx.pollutants = [air, wat]
    return ctx


def test_slice_gives_only_section_data():
    ctx = _ctx()
    waste = task.slice_context(ctx, "waste")
    assert set(waste) == {"wastes", "waste_acts", "period"}
    assert waste["wastes"][0]["generated"] == "1.9"       # Decimal → строка
    air = task.slice_context(ctx, "air")
    assert [p["code"] for p in air["pollutants_air"]] == ["0301"]
    assert "pollutants_water" not in air                  # чужая среда не уходит
    org = task.slice_context(ctx, "org")
    assert org["organization"]["inn"] == "780600114472"
    assert "wastes" not in org


def test_slice_is_json_serialisable():
    json.dumps(task.slice_context(_ctx(), "all"), ensure_ascii=False)


def test_apply_data_types_and_merge():
    ctx = _ctx()
    changes = task.apply_data(ctx, {"wastes": [
        {"fkko_code": "73310001724", "name": "Мусор офисный",
         "hazard_class": "4", "generated": "2,5"}]})
    assert ctx.wastes[0].generated == Decimal("2.5")      # запятая и строка → Decimal
    assert ctx.wastes[0].hazard_class == 4                # строка → int
    assert any("движение" in c for c in changes)


def test_apply_data_replaces_only_given_medium():
    ctx = _ctx()
    task.apply_data(ctx, {"pollutants_air": [
        {"code": "0337", "name": "Углерод оксид", "mass_norm": "1.205"}]})
    air = [p for p in ctx.pollutants if p.medium == Medium.AIR]
    water = [p for p in ctx.pollutants if p.medium == Medium.WATER]
    assert [p.code for p in air] == ["0337"]             # воздух заменён
    assert [p.code for p in water] == ["0007"]           # вода не тронута
    assert air[0].mass_norm == Decimal("1.205")


def test_apply_data_ignores_unknown_sections():
    ctx = _ctx()
    assert task.apply_data(ctx, {"мусор": [1, 2], "answer": "текст"}) == []
    assert ctx.wastes[0].generated == Decimal("1.9")


def test_run_task_without_apply_does_not_touch_context(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    ctx = _ctx()
    monkeypatch.setattr("ecodoc.ai.detect.ensure_configured",
                        lambda: __import__("ecodoc.ai.config", fromlist=["AIConfig"])
                        .AIConfig(provider="mistral", model="m"))
    monkeypatch.setattr("ecodoc.ai.providers.chat_with_fallback",
                        lambda *a, **k: ('{"answer":"готово","data":{"wastes":'
                                         '[{"fkko_code":"73310001724",'
                                         '"generated":"9"}]}}', "mistral/m"))
    res = task.run_task(ctx, "waste", "просуммируй", apply_changes=False)
    assert res["answer"] == "готово"
    assert res["applied"] == []
    assert ctx.wastes[0].generated == Decimal("1.9")      # база не изменилась


def test_run_task_applies_when_asked(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    ctx = _ctx()
    monkeypatch.setattr("ecodoc.ai.detect.ensure_configured",
                        lambda: __import__("ecodoc.ai.config", fromlist=["AIConfig"])
                        .AIConfig(provider="mistral", model="m"))
    monkeypatch.setattr("ecodoc.ai.providers.chat_with_fallback",
                        lambda *a, **k: ('{"answer":"ок","data":{"wastes":'
                                         '[{"fkko_code":"73310001724",'
                                         '"generated":"9"}]},"warnings":["проверьте"]}',
                                         "mistral/m"))
    res = task.run_task(ctx, "waste", "поставь 9", apply_changes=True)
    assert ctx.wastes[0].generated == Decimal("9")
    assert res["applied"] and res["warnings"] == ["проверьте"]


def test_run_task_survives_non_json_answer(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path))
    monkeypatch.setattr("ecodoc.ai.detect.ensure_configured",
                        lambda: __import__("ecodoc.ai.config", fromlist=["AIConfig"])
                        .AIConfig(provider="mistral", model="m"))
    monkeypatch.setattr("ecodoc.ai.providers.chat_with_fallback",
                        lambda *a, **k: ("Данные выглядят корректно.", "mistral/m"))
    res = task.run_task(_ctx(), "waste", "проверь", apply_changes=True)
    assert "корректно" in res["answer"] and res["applied"] == []
