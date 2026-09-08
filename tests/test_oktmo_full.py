"""Резолвер ОКТМО по полному классификатору (data/oktmo_full.json.gz) и
фолбэк через геокодер OSM (сеть подменяется). Замечание эколога 08.09.2026:
ОКТМО по адресу «надо находить»."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecodoc.parsers import oktmo
from ecodoc.parsers.oktmo import OktmoError, by_address, resolve

TEHNOSTROY_SITE = ("Проектирование строительства здания общеобразовательной школы по "
                   "адресу: Санкт-Петербург, Муниципальный округ Новоизмайловское, "
                   "Варшавская ул., участок 16")
TEHNOSTROY_ORG = ("198516, г.Санкт-Петербург, г.Петергоф, Санкт-Петербургский пр-кт, "
                  "д.60, лит.Ф, оф.214")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Тесты не ходят в сеть: OSM отключён, DaData без токена."""
    monkeypatch.setenv("ECODOC_OFFLINE", "1")
    monkeypatch.delenv("DADATA_TOKEN", raising=False)


def test_catalog_loaded_fast():
    cat = oktmo.full_catalog()
    assert cat.get("count", 0) > 150_000 and len(cat["items"]) == cat["count"]
    # индекс по регионам: СПб — 111 внутригородских МО
    assert len(oktmo._items_of_region("40")) >= 111
    assert oktmo.level_of("40375000") == "district"
    assert oktmo.level_of("41612155") == "settlement"
    assert oktmo.level_of("41612100") == "group"        # «Городские поселения … района»
    assert oktmo.level_of("41612155001") == "locality"
    assert oktmo.level_of("41000000") == "region"


def test_prefix_subject_translation():
    assert oktmo.subject_of_prefix("40") == "78"        # СПб
    assert oktmo.subject_of_prefix("41") == "47"        # ЛО
    assert oktmo.subject_of_prefix("78") == "76"        # 78 в ОКТМО — Ярославль!
    assert oktmo.subject_of_prefix("71800000") == "86"  # ХМАО
    assert oktmo.prefix_of_oktmo("71826000") == "718"
    assert oktmo.prefix_of_oktmo("40375000") == "40"


def test_tehnostroy_site_address():
    r = resolve(TEHNOSTROY_SITE)
    assert r["oktmo"] == "40375000" and r["confidence"] >= 0.9
    assert "Новоизмайловское" in r["value"]
    assert r["subject"] == "78" and r["region"] == "40"
    hit = by_address(TEHNOSTROY_SITE)
    assert hit["oktmo"] == "40375000" and hit["source"] == "oktmo_full"


def test_tehnostroy_org_address_petergof():
    hit = by_address(TEHNOSTROY_ORG)
    assert hit["oktmo"] == "40395000"
    assert "Петергоф" in hit["value"]


def test_janino_full_catalog_without_user_ref(monkeypatch):
    # без пользовательского справочника — только классификатор
    monkeypatch.setattr(oktmo, "oktmo_ref", lambda: {})
    hit = by_address("Ленинградская область, Всеволожский район, Янино-1")
    assert hit["oktmo"] == "41612155" and hit["source"] == "oktmo_full"
    assert "Заневское" in hit["value"]
    hit2 = by_address("188689, Ленинградская область, Всеволожский р-н, дер. Янино-1, "
                      "Промышленный пр., 10")
    assert hit2["oktmo"] == "41612155"


def test_district_town_and_street_abbreviations():
    # «Колтушское ш.» — улица, а не поселение Колтушское
    r = resolve("Ленинградская обл., г. Всеволожск, Колтушское ш., 1")
    assert r["oktmo"] == "41612101" and r["confidence"] >= 0.9
    r = resolve("Московская обл., г. Истра, ул. Ленина, 1")
    assert r["oktmo"] == "46533000"          # муниципальный округ Истра (с 2025)
    r = resolve("г. Владивосток, ул. Светланская, 1")   # регион не указан — уникальный город
    assert r["oktmo"] == "05701000" and r["subject"] == "25"
    r = resolve("Санкт-Петербург, п. Шушары, Московское ш., 10")
    assert r["oktmo"] == "40901000"
    r = resolve("Москва, район Хамовники, ул. Льва Толстого, 16")
    assert r["oktmo"] == "45383000"


def test_federal_city_street_only_needs_geocoder():
    """«СПб, Промышленная ул., 10» — округ в адресе не назван; оффлайн только
    регион, кандидатов нет, ошибка короткая (без инструкций про DaData/json)."""
    r = resolve("Санкт-Петербург, Промышленная ул., 10")
    assert r["oktmo"] == "40000000" and r["level_code"] == "region" and r["confidence"] < 0.5
    with pytest.raises(OktmoError) as ei:
        by_address("Санкт-Петербург, Промышленная ул., 10")
    msg = str(ei.value)
    assert msg.startswith("ОКТМО по адресу не найден")
    assert "DaData" not in msg and "json" not in msg and len(msg) < 200
    assert ei.value.candidates == []


def test_no_region_ambiguous_or_empty():
    r = resolve("")
    assert r["oktmo"] == "" and r["note"]
    r = resolve("ул. Ленина, 5")
    assert r["oktmo"] == "" and "регион" in r["note"]


def _fake_osm(hits):
    def q(address, timeout):
        return hits
    return q


def test_osm_fallback_spb_street(monkeypatch):
    """Геокодер вернул округ — берём ОКТМО округа; тёзка в Красном Селе —
    вторым кандидатом со штрафом."""
    monkeypatch.delenv("ECODOC_OFFLINE", raising=False)
    monkeypatch.setattr(oktmo, "_osm_query", _fake_osm([
        {"address": {"road": "Промышленная улица", "city_district": "Нарвский округ",
                     "city": "Санкт-Петербург", "state": "Санкт-Петербург",
                     "region": "Северо-Западный федеральный округ"}},
        {"address": {"road": "Промышленная улица", "suburb": "Дудергоф",
                     "town": "Красное Село", "state": "Санкт-Петербург"}},
    ]))
    hit = by_address("Санкт-Петербург, Промышленная ул., 10")
    assert hit["oktmo"] == "40339000" and hit["source"] == "osm+oktmo_full"
    assert hit["confidence"] >= 0.9
    codes = [c["oktmo"] for c in hit["candidates"]]
    assert codes[0] == "40339000" and "40353000" in codes
    assert hit["candidates"][1]["confidence"] < hit["candidates"][0]["confidence"]


def test_osm_fallback_moscow(monkeypatch):
    monkeypatch.delenv("ECODOC_OFFLINE", raising=False)
    monkeypatch.setattr(oktmo, "_osm_query", _fake_osm([
        {"address": {"road": "Тверская улица", "suburb": "Тверской район",
                     "city": "Москва", "state": "Москва"}}]))
    hit = by_address("Москва, ул. Тверская, 1")
    assert hit["oktmo"] == "45382000"


def test_osm_unavailable_gives_short_error(monkeypatch):
    monkeypatch.delenv("ECODOC_OFFLINE", raising=False)
    monkeypatch.setattr(oktmo, "_osm_query", _fake_osm([]))
    with pytest.raises(OktmoError) as ei:
        by_address("Москва, ул. Тверская, 1")
    assert len(str(ei.value)) < 200


def test_for_osm_expands_abbreviations():
    assert oktmo._for_osm("192007, Санкт-Петербург, Лиговский пр., 150") == \
        "Санкт-Петербург, Лиговский проспект, 150"
    s = oktmo._for_osm(TEHNOSTROY_ORG)
    assert "проспект" in s and not re.search(r"\bоф\b", s) and "198516" not in s


def test_api_oktmo_shape(monkeypatch):
    from ecodoc.gui import server
    out = server.api_oktmo({}, {"address": TEHNOSTROY_SITE})
    assert out["result"]["oktmo"] == "40375000"
    assert out["candidates"] and out["candidates"][0]["oktmo"] == "40375000"
    out = server.api_oktmo({}, {"address": "Санкт-Петербург, Промышленная ул., 10"})
    assert out["error"].startswith("ОКТМО по адресу не найден") and out["candidates"] == []
    assert "DaData" not in out["error"]
    # неоднозначность — кандидаты на выбор
    monkeypatch.delenv("ECODOC_OFFLINE", raising=False)
    monkeypatch.setattr(oktmo, "_osm_query", _fake_osm([
        {"address": {"city_district": "Нарвский округ", "state": "Санкт-Петербург"}},
        {"address": {"city_district": "Нарвский округ", "state": "Санкт-Петербург"}},
        {"address": {"town": "Красное Село", "state": "Санкт-Петербург"}},
    ]))
    monkeypatch.setattr(oktmo, "resolve_online", lambda a, timeout=6: {
        "oktmo": "40339000", "value": "x", "level": "округ", "level_code": "district_final",
        "confidence": 0.55, "source": "osm+oktmo_full", "note": "",
        "candidates": [{"oktmo": "40339000", "value": "x", "level": "округ", "confidence": 0.55},
                       {"oktmo": "40353000", "value": "y", "level": "округ", "confidence": 0.55}]})
    out = server.api_oktmo({}, {"address": "Санкт-Петербург, Промышленная ул., 10"})
    assert "неоднозначно" in out["error"]
    assert [c["oktmo"] for c in out["candidates"]] == ["40339000", "40353000"]
