"""Новые документы: инвентаризации, ПНООЛР, 4-ОС, ТУ."""
from decimal import Decimal

import openpyxl
import pytest

from ecodoc.core.models import (Medium, NVOSObject, Pollutant, ReportContext,
                                WasteAct, WasteFlow)


@pytest.fixture()
def ctx():
    c = ReportContext()
    c.organization.name = "ИП Миних Елена Анатольевна"
    c.organization.inn = "780600114472"
    c.organization.ogrn = "307784705100221"
    c.period.year = 2025
    c.objects = [NVOSObject(code="41-0247-005048-П", address="Промзона Янино")]
    c.wastes = [
        WasteFlow(fkko_code="47110101521", name="Лампы ртутные", hazard_class=1,
                  generated=Decimal("0.052"), transferred=Decimal("0.052")),
        WasteFlow(fkko_code="73310001724", name="Мусор офисный", hazard_class=4,
                  generated=Decimal("1.9"), transferred=Decimal("1.9"),
                  placed_norm=Decimal("1.9")),
    ]
    c.waste_acts = [WasteAct(fkko_code="47110101521", name="Лампы ртутные",
                             mass=Decimal("0.052"), operation="обезвреживание",
                             receiver="ООО «Меркурий»", date="15.02.2025")]
    c.extra["waste_passports"] = [{
        "fkko": "47110101521", "name": "Лампы ртутные", "hazard_class": 1,
        "components": [{"name": "стекло", "percent": "92"}]}]
    c.extra["emission_sources"] = [{
        "number": "0001", "name": "Котельная", "kind": "организованный",
        "_src": "ООС.pdf",
        "pollutants": [{"code": "0301", "name": "Азота диоксид",
                        "g_s": "0.05", "t_year": "0.412"}]}]
    air = Pollutant(code="0301", name="Азота диоксид", mass_norm=Decimal("0.412"))
    air.medium = Medium.AIR
    c.pollutants = [air]
    return c


def _cells(path, sheet):
    ws = openpyxl.load_workbook(path)[sheet]
    return [[c.value for c in row] for row in ws.iter_rows()]


# ── инвентаризация отходов ───────────────────────────────────────────────

def test_waste_inventory_collects_from_all_sources(ctx):
    from ecodoc.development.waste_inventory import collect
    rows = {r["fkko"]: r for r in collect(ctx)}
    lamp = rows["47110101521"]
    assert lamp["hazard"] == 1 and lamp["generated"] == pytest.approx(0.052)
    assert lamp["operations"] == ["обезвреживание"]      # из акта
    assert lamp["receivers"] == ["ООО «Меркурий»"]
    assert "стекло" in lamp["composition"] and lamp["passport"]
    assert not rows["73310001724"]["passport"]           # паспорта нет


def test_waste_inventory_reports_gaps(ctx):
    from ecodoc.development.waste_inventory import gaps
    text = " | ".join(gaps(ctx))
    assert "нет паспорта отхода" in text                 # для мусора IV класса
    assert "Мусор офисный" in text


def test_waste_inventory_document(ctx, tmp_path):
    from ecodoc.development.waste_inventory import generate
    out = generate(ctx, tmp_path / "инв.xlsx")
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Титул", "Перечень отходов", "Чего не хватает"]
    flat = [str(v) for row in _cells(out, "Перечень отходов") for v in row if v]
    assert "47110101521" in flat and "Лампы ртутные" in flat
    assert "ООО «Меркурий»" in flat


# ── инвентаризация выбросов ──────────────────────────────────────────────

def test_air_inventory_sources_and_substances(ctx, tmp_path):
    from ecodoc.development.air_inventory import generate, gaps, sources
    assert sources(ctx)[0]["number"] == "0001"
    out = generate(ctx, tmp_path / "инв_воздух.xlsx")
    flat = [str(v) for row in _cells(out, "Источники") for v in row if v]
    assert "Котельная" in flat and "0.412 т/год" in " ".join(flat)
    subs = [str(v) for row in _cells(out, "Вещества") for v in row if v]
    assert "0301" in subs and "Азота диоксид" in subs
    assert gaps(ctx) == []                               # всё заполнено


def test_air_inventory_complains_without_sources(tmp_path):
    from ecodoc.development.air_inventory import gaps
    empty = ReportContext()
    text = " | ".join(gaps(empty))
    assert "не найдены источники выбросов" in text
    assert "не заданы вещества" in text


# ── ПНООЛР ───────────────────────────────────────────────────────────────

def test_pnoolr_norms_and_limits(ctx, tmp_path):
    from ecodoc.development.pnoolr import generate, rows
    data = {r["fkko"]: r for r in rows(ctx)}
    assert data["73310001724"]["norm"] == pytest.approx(1.9)
    assert data["73310001724"]["limit"] == pytest.approx(1.9)   # размещено
    assert data["47110101521"]["limit"] is None                 # не размещался
    out = generate(ctx, tmp_path / "пноолр.xlsx")
    flat = [str(v) for row in _cells(out, "Нормативы и лимиты") for v in row if v]
    assert "ИТОГО" in flat and "Лампы ртутные" in flat
    gaps_text = " ".join(str(v) for row in _cells(out, "Чего не хватает")
                         for v in row if v)
    assert "пишется экологом" in gaps_text                # честно про разделы


# ── 4-ОС ────────────────────────────────────────────────────────────────

def test_oos4_registered_and_validates(ctx):
    from ecodoc.core import registry
    registry.load_all()
    rep = registry.get("4-oos")(ctx)
    msgs = " | ".join(i.message for i in rep.validate())
    assert "не заданы текущие затраты" in msgs            # extra.oos4 пуст


def test_oos4_print_matches_blank(ctx, tmp_path):
    """Форма № 4-ОС: бланк ред. 22.07.2025 (приказ № 346), платы за НВОС нет."""
    from ecodoc.core import registry
    registry.load_all()
    ctx.extra["oos4"] = {"costs": {"air": "120.5", "waste": "340", "water": 0,
                                   "noise": "7.7"}}
    rep = registry.get("4-oos")(ctx)
    assert rep.title.startswith("4-ОС")            # официальный индекс формы
    out = rep.render_print(tmp_path / "4oos.xlsx")
    rows = _cells(out, "Форма")
    flat = [str(v) for row in rows for v in row if v is not None]
    # строки бланка, а не выдуманные 101-106
    assert "01" in flat and "02" in flat and "10" in flat
    assert not any(v in ("101", "106") for v in flat)
    assert "120.5" in flat and "340" in flat
    # строка 01 — контрольная сумма 02-10 (460.5 + 7.7 шума)
    assert "468.2" in flat
    # раздела о плате за НВОС в действующей форме нет
    assert not any("Плата за негативное" in v for v in flat)
    # бланк ред. 22.07.2025: заголовок таблицы и блоки граф
    joined = " ".join(flat)
    assert "Выполнение работ по охране окружающей среды" in joined
    assert "Для собственных нужд" in joined
    assert "Специализированные природоохранные услуги" in joined
    # два блока по 8 граф: нумерация А, Б, 3–10, 11–18
    num_row = next(r for r in rows if r and str(r[0]) == "А")
    nums = [str(v) for v in num_row if v is not None]
    assert nums == ["А", "Б"] + [str(i) for i in range(3, 19)]
    # строки 06/07 — как в действующем бланке (06 шум, 07 биоразнообразие);
    # затраты по шуму (7.7) должны встать именно в строку 06
    by_code = {}
    for r in rows:
        vals = [v for v in r if v is not None]
        if len(vals) >= 2 and str(vals[1]) in {f"{i:02d}" for i in range(2, 11)}:
            by_code[str(vals[1])] = (str(vals[0]), vals[2] if len(vals) > 2 else None)
    assert "шумового и вибрационного" in by_code["06"][0]
    assert by_code["06"][1] == 7.7
    assert "биоразнообразия" in by_code["07"][0]
    # дословные формулировки строк действующего бланка
    assert "обращение со сточными водами" in by_code["03"][0]
    assert "экологическая реабилитация земель" in by_code["05"][0]
    assert "за исключением мер по предотвращению аварий" in by_code["08"][0]
    assert "в области охраны окружающей среды" in by_code["09"][0]
    titul = " ".join(str(v) for row in _cells(out, "Титул") for v in row if v)
    assert "4-ОС" in titul and "0609030" in titul
    assert "346" in titul and "1-го рабочего дня" in titul


# ── ТУ ───────────────────────────────────────────────────────────────────

def test_tu_letter(ctx, tmp_path):
    from docx import Document

    from ecodoc.development.tu_waste import generate
    out = generate(ctx, tmp_path / "ту.docx", receiver="ООО «Полигон»",
                   purpose="размещения на полигоне")
    doc = Document(out)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "ООО «Полигон»" in text and "размещения на полигоне" in text
    assert "780600114472" in text and "41-0247-005048-П" in text
    table = doc.tables[0]
    cells = [c.text for row in table.rows for c in row.cells]
    assert "47110101521" in cells and "Лампы ртутные" in cells


# ── реестр и API ─────────────────────────────────────────────────────────

def test_all_new_documents_registered():
    from ecodoc.core import registry
    registry.load_all()
    reports = registry.all_reports()
    for code in ("waste-inventory", "air-inventory", "pnoolr", "tu-waste",
                 "waste-passport", "4-oos"):
        assert code in reports, code
    for code in ("waste-inventory", "air-inventory", "pnoolr", "tu-waste"):
        assert getattr(reports[code], "devdoc", False), code


def test_api_devdoc_generates_new_documents(ctx, tmp_path, monkeypatch):
    from ecodoc.core import workspace
    from ecodoc.gui import server
    monkeypatch.setenv("ECODOC_RESULTS", str(tmp_path / "res"))
    workspace.add_org("ТЕСТ")
    workspace.add_site("ТЕСТ", "Пл")
    workspace.save_context("ТЕСТ", "Пл", ctx)
    for kind in ("waste-inventory", "air-inventory", "pnoolr", "tu-waste"):
        out = server.api_devdoc({}, {"org": "ТЕСТ", "site": "Пл", "kind": kind})
        assert "path" in out, (kind, out)
        assert out["path"]
