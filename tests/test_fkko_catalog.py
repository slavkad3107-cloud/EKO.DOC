"""Каталог ФККО: структура кода, сверка с каталогом, обновление."""
import json
from decimal import Decimal

import pytest

from ecodoc.core import fkko
from ecodoc.core.models import ReportContext, WasteAct, WasteFlow


@pytest.fixture(autouse=True)
def _own_catalog(tmp_path, monkeypatch):
    """Каждый тест — со своим файлом каталога, реальный не трогаем."""
    monkeypatch.setenv("ECODOC_FKKO", str(tmp_path / "fkko.json"))
    monkeypatch.setattr(fkko, "BUILTIN_FILE", tmp_path / "встроенный.json")
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
    assert not bad.ok and "нет в каталоге ФККО" in bad.problem
    assert "обновите" in bad.problem       # каталог — снимок, подсказываем путь


def test_missing_code_in_partial_catalog_is_only_note():
    fkko.save({"47110101521": {"name": "Лампы", "class": 1}}, partial=True)
    unknown = fkko.check("73310001724")
    assert unknown.ok and not unknown.verified and "частичном" in unknown.note


def test_seed_builtin_from_reference():
    assert fkko.seed_builtin() > 0
    assert fkko.catalog()["partial"] is True
    assert fkko.seed_builtin() == 0            # второй раз не перезаписывает


def test_catalog_from_forms_folder(tmp_path, monkeypatch):
    """Полный ФККО пользователь держит в папке «Формы» — берём его оттуда."""
    openpyxl = pytest.importorskip("openpyxl")
    forms = tmp_path / "Формы"
    forms.mkdir()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Код", "Наименование", "Агрегатное состояние", "Класс опасности"])
    ws.append([47110101521, "лампы ртутные", "изделие", "I"])
    ws.append([73310001724, "мусор от офисных помещений", "смесь", "IV"])
    ws.append([73310000000, "отходы коммунальные (группа)", "", "-"])
    wb.save(forms / "ФККО.xlsx")
    monkeypatch.setenv("ECODOC_FORMS", str(forms))

    n = fkko.seed_builtin()
    assert n == 3
    assert "ФККО" in fkko.catalog()["source"]
    assert fkko.check("47110101521").hazard == 1    # римская I разобрана
    assert fkko.codes()["73310000000"]["group"] is True
    assert not fkko.check("73310000000").ok         # групповой код в отчёт не идёт


def test_manual_catalog_survives_startup_sync(tmp_path, monkeypatch):
    """Загруженный пользователем каталог автосинхронизация не затирает."""
    openpyxl = pytest.importorskip("openpyxl")
    forms = tmp_path / "Формы"
    forms.mkdir()
    monkeypatch.setenv("ECODOC_FORMS", str(forms))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Код", "Наименование", "Класс опасности"])
    ws.append([47110101521, "лампы", "I"])
    wb.save(forms / "ФККО.xlsx")
    assert fkko.sync_from_forms() == 1              # старый файл в «Формах»

    свежий = tmp_path / "свежий.json"
    свежий.write_text(json.dumps([{"code": "47110101521", "name": "лампы"},
                                  {"code": "73310001724", "name": "мусор"}]),
                      encoding="utf-8")
    fkko.load_file(свежий)                          # пользователь загрузил свой
    assert fkko.catalog()["origin"] == "manual"

    assert fkko.sync_from_forms() == 0              # старт не трогает ручной
    assert len(fkko.codes()) == 2
    # кнопка «Обновить каталог» — явное действие, берёт файл из «Форм»
    assert fkko.sync_from_forms(force=True) == 1
    assert fkko.catalog()["origin"] == "forms"


def test_catalog_without_origin_field_still_syncs(tmp_path, monkeypatch):
    """Каталог, записанный прошлой версией (без origin), не залипает."""
    openpyxl = pytest.importorskip("openpyxl")
    forms = tmp_path / "Формы"
    forms.mkdir()
    monkeypatch.setenv("ECODOC_FORMS", str(forms))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Код", "Наименование", "Класс опасности"])
    ws.append([47110101521, "лампы", "I"])
    ws.append([73310001724, "мусор", "IV"])
    wb.save(forms / "ФККО.xlsx")
    # так писала версия 0.53.0: ни origin, ни stamp
    fkko.user_file().parent.mkdir(parents=True, exist_ok=True)
    fkko.user_file().write_text(json.dumps(
        {"updated": "2026-07-31", "source": "старый.xls", "partial": False,
         "codes": {"47110101521": {"name": "лампы", "class": 1}}}),
        encoding="utf-8")
    fkko._CACHE.clear()
    assert "origin" not in fkko.catalog()
    assert fkko.sync_from_forms() == 2          # подхватился, а не залип


def test_api_fkko_update_without_path_takes_forms_folder(tmp_path, monkeypatch):
    """Кнопка «Обновить каталог» без файла берёт ФККО из «Форм», не из сети."""
    openpyxl = pytest.importorskip("openpyxl")
    forms = tmp_path / "Формы"
    forms.mkdir()
    monkeypatch.setenv("ECODOC_FORMS", str(forms))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Код", "Наименование", "Класс опасности"])
    ws.append([73310001724, "мусор офисный", "IV"])
    wb.save(forms / "ФККО новый.xlsx")

    def _no_network(timeout=60):
        raise AssertionError("в сеть ходить не должны — каталог есть в «Формах»")
    monkeypatch.setattr(fkko, "update", _no_network)

    from ecodoc.gui import server
    out = server.api_fkko_update({}, {})
    assert out["ok"] and out["codes"] == 1
    assert "ФККО" in out["source"]


def test_forms_catalog_reloaded_when_file_changes(tmp_path, monkeypatch):
    """Положили в «Формы» свежий ФККО — при следующем старте он подхватится."""
    openpyxl = pytest.importorskip("openpyxl")
    forms = tmp_path / "Формы"
    forms.mkdir()
    monkeypatch.setenv("ECODOC_FORMS", str(forms))

    def write(rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Код", "Наименование", "Класс опасности"])
        for code, name, cls in rows:
            ws.append([code, name, cls])
        wb.save(forms / "ФККО.xlsx")

    write([(47110101521, "лампы", "I")])
    assert fkko.sync_from_forms() == 1
    assert fkko.sync_from_forms() == 0              # тот же файл — не перечитываем
    write([(47110101521, "лампы", "I"), (73310001724, "мусор", "IV")])
    assert fkko.sync_from_forms() == 2              # файл изменился — перечитали


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
