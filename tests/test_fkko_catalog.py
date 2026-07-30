"""Каталог ФККО: структура кода, сверка с каталогом, обновление."""
import json
from decimal import Decimal

import pytest

from ecodoc.core import fkko
from ecodoc.core.models import ReportContext, WasteAct, WasteFlow


@pytest.fixture(autouse=True)
def _own_catalog(tmp_path, monkeypatch):
    """Каждый тест — со своим файлом каталога, реальный не трогаем."""
    monkeypatch.setattr(fkko, "DATA_FILE", tmp_path / "fkko.json")
    fkko._CACHE.clear()
    yield
    fkko._CACHE.clear()


def test_structure_checked_without_catalog():
    """Без каталога проверяем структуру и НЕ объявляем код неверным."""
    ok = fkko.check("4 71 101 01 52 1")
    assert ok.ok and not ok.verified and "не загружен" in ok.note
    assert not fkko.check("13000030000").ok        # класс 0 — групповой заголовок
    assert "11 цифр" in fkko.check("123").problem
    assert "не заполнен" in fkko.check("").problem
    assert "с нуля" in fkko.check("01041612155").problem


def test_catalog_confirms_code_and_name():
    fkko.save({"47110101521": {"name": "Лампы ртутные", "class": 1}},
              source="тест")
    good = fkko.check("4 71 101 01 52 1", "Лампы ртутные")
    assert good.ok and good.verified and good.hazard == 1
    assert not good.name_mismatch
    other = fkko.check("47110101521", "Совершенно другое наименование отхода")
    assert other.name_mismatch == "Лампы ртутные"


def test_missing_code_in_full_catalog_is_error():
    fkko.save({"47110101521": {"name": "Лампы", "class": 1}}, partial=False)
    bad = fkko.check("73310001724")
    assert not bad.ok and "нет в действующем ФККО" in bad.problem


def test_missing_code_in_partial_catalog_is_only_note():
    fkko.save({"47110101521": {"name": "Лампы", "class": 1}}, partial=True)
    unknown = fkko.check("73310001724")
    assert unknown.ok and not unknown.verified and "частичном" in unknown.note


def test_seed_builtin_from_reference():
    assert fkko.seed_builtin() > 0
    assert fkko.catalog()["partial"] is True
    assert fkko.seed_builtin() == 0            # второй раз не перезаписывает


def test_parse_json_and_text():
    from_json = fkko.parse(json.dumps([
        {"code": "4 71 101 01 52 1", "name": "Лампы ртутные"},
        {"fkko": "73310001724", "наименование": "Мусор офисный"}]))
    assert set(from_json) == {"47110101521", "73310001724"}
    assert from_json["47110101521"]["class"] == 1
    from_text = fkko.parse("4 71 101 01 52 1  Лампы ртутные\n"
                           "7 33 100 01 72 4;Мусор от офисных помещений")
    assert set(from_text) == {"47110101521", "73310001724"}
    assert "Мусор" in from_text["73310001724"]["name"]


def test_load_file(tmp_path):
    src = tmp_path / "cat.json"
    src.write_text(json.dumps([{"code": "47110101521", "name": "Лампы"}]),
                   encoding="utf-8")
    n, where = fkko.load_file(src)
    assert n == 1 and str(src) == where
    assert fkko.codes()["47110101521"]["name"] == "Лампы"
    with pytest.raises(FileNotFoundError):
        fkko.load_file(tmp_path / "нет.json")
    empty = tmp_path / "empty.csv"
    empty.write_text("ничего полезного", encoding="utf-8")
    with pytest.raises(ValueError):
        fkko.load_file(empty)


def test_check_context_covers_movement_and_acts():
    fkko.save({"47110101521": {"name": "Лампы ртутные", "class": 1}}, partial=False)
    ctx = ReportContext()
    ctx.wastes = [WasteFlow(fkko_code="47110101521", name="Лампы ртутные",
                            hazard_class=4)]                    # класс разошёлся
    ctx.waste_acts = [WasteAct(fkko_code="73310001724", name="Мусор",
                               mass=Decimal("1"))]              # нет в каталоге
    rows = {r["code"]: r for r in fkko.check_context(ctx)}
    assert rows["47110101521"]["verified"] and rows["47110101521"]["class_mismatch"]
    assert not rows["73310001724"]["ok"]


def test_api_fkko_check_and_update(tmp_path, monkeypatch):
    from ecodoc.core import workspace
    from ecodoc.gui import server
    workspace.add_org("ТЕСТ")
    workspace.add_site("ТЕСТ", "Пл")
    ctx = workspace.load_context("ТЕСТ", "Пл")
    ctx.wastes = [WasteFlow(fkko_code="47110101521", name="Лампы")]
    workspace.save_context("ТЕСТ", "Пл", ctx)

    out = server.api_fkko_check({"org": "ТЕСТ", "site": "Пл"}, {})
    assert out["rows"] and out["size"] > 0          # встроенный минимум подхватился

    src = tmp_path / "cat.json"
    src.write_text(json.dumps([{"code": "47110101521", "name": "Лампы ртутные"}]),
                   encoding="utf-8")
    upd = server.api_fkko_update({}, {"path": str(src)})
    assert upd["ok"] and upd["codes"] == 1
    bad = server.api_fkko_update({}, {"path": str(tmp_path / "нет.json")})
    assert "error" in bad                            # ошибка в ответе, не исключение
