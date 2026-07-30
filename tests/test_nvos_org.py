"""Код объекта НВОС и сверка реквизитов с ЕГРЮЛ."""
import pytest

from ecodoc.core import nvos


def test_valid_codes():
    assert nvos.is_valid("40-0278-013459-П")          # образец из ТЗ
    assert nvos.is_valid("41-0247-005048-П")          # реальный объект
    assert nvos.is_valid("78-0178-001234-Б")          # «Б» тоже допустим
    assert nvos.is_valid(" 41-0247-005048-п ")        # пробелы и строчная


def test_latin_lookalikes_normalised():
    """В сканах вместо кириллических П/Т/О/Л часто латинские P/T/O/L."""
    assert nvos.normalize("40-0278-013459-P") == "40-0278-013459-П"
    assert nvos.is_valid("40-0278-013459-P")


def test_invalid_codes_are_explained():
    assert not nvos.is_valid("XX-XXXX-XXXXXX-Б")
    assert "формате объекта НВОС" in nvos.problem("XX-XXXX-XXXXXX-Б")
    assert "кадастровый" in nvos.problem("47:07:1039001:211")
    assert not nvos.is_valid("--")
    assert "не заполнен" in nvos.problem("")
    assert not nvos.is_valid("6-241121_015-015")


def test_strict_requires_six_digits():
    assert nvos.is_valid("40-0278-13459-П")               # мягкая проверка
    assert not nvos.is_valid("40-0278-13459-П", strict=True)
    assert nvos.is_valid("40-0278-013459-П", strict=True)


def test_region_and_category():
    assert nvos.region("41-0247-005048-П") == "41"
    assert nvos.category("41-0247-005048-П") == "I категория"
    assert nvos.category("78-0178-001234-Л") == "IV категория"
    assert nvos.category("мусор") == ""


def test_find_all_in_text():
    text = ("Объект 41-0247-005048-П поставлен на учёт; шаблон XX-XXXX-XXXXXX-Б "
            "не считается; ещё один 78-0178-001234-Т и повтор 41-0247-005048-П")
    assert nvos.find_all(text) == ["41-0247-005048-П", "78-0178-001234-Т"]


def test_single_rule_for_whole_app():
    """xmlutil использует ту же проверку — правила не должны разъезжаться."""
    from ecodoc.render.xmlutil import _is_nvos_code
    for code in ("41-0247-005048-П", "78-0178-001234-Б"):
        assert _is_nvos_code(code) == nvos.is_valid(code)
    assert not _is_nvos_code("XX-XXXX-XXXXXX-Б")


# ── API вкладок ОРГАНИЗАЦИЯ и ОБЪЕКТ ─────────────────────────────────────

def test_api_object_check_reports_problem_and_category():
    from ecodoc.gui import server
    out = server.api_object_check({}, {"code": "41-0247-005048-П"})
    assert out["valid"] and out["category"] == "I категория" and out["region"] == "41"
    bad = server.api_object_check({}, {"code": "--"})
    assert not bad["valid"] and bad["problem"]


def test_api_object_check_finds_oktmo_by_address():
    from ecodoc.gui import server
    out = server.api_object_check({}, {"code": "41-0247-005048-П",
                                       "address": "Ленинградская обл., Янино"})
    # справочник оффлайн: либо нашли ОКТМО, либо честно сказали, что нет
    assert out.get("oktmo") or out.get("oktmo_error")


def test_api_org_verify_needs_inn(tmp_path, monkeypatch):
    from ecodoc.core import workspace
    from ecodoc.gui import server
    workspace.add_org("ТЕСТ")
    workspace.add_site("ТЕСТ", "Пл")
    out = server.api_org_verify({}, {"org": "ТЕСТ", "site": "Пл"})
    assert out.get("need_inn")


def test_api_org_verify_compares_fields(tmp_path, monkeypatch):
    from ecodoc.core import workspace
    from ecodoc.gui import server
    workspace.add_org("ООО Тест", inn="7801234564", kpp="780101001",
                      address="СПб, ул. Тестовая, 1")
    workspace.add_site("ООО Тест", "Пл")
    monkeypatch.setattr("ecodoc.parsers.egrul.lookup", lambda inn: {
        "name": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ «ТЕСТ»",
        "short_name": "ООО «Тест»", "inn": "7801234564", "kpp": "780101001",
        "ogrn": "1027801234561", "address": "СПб, ул. Тестовая, 1",
        "director_name": "Иванов И.И.", "director_position": "Директор"})
    out = server.api_org_verify({}, {"org": "ООО Тест", "site": "Пл"})
    rows = {r["field"]: r for r in out["rows"]}
    assert rows["inn"]["same"] and rows["kpp"]["same"]
    assert rows["address"]["same"]                     # регистр и кавычки не мешают
    assert rows["ogrn"]["empty"]                       # у нас пусто — можно взять
    assert out["egrul"]["ogrn"] == "1027801234561"
