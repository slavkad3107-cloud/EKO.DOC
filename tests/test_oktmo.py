"""Оффлайн-резолвер ОКТМО (бесплатная замена DaData, без токена)."""
import os

import pytest

from ecodoc.parsers.oktmo import OktmoError, by_address


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv("DADATA_TOKEN", raising=False)
    monkeypatch.setenv("ECODOC_OFFLINE", "1")      # без геокодера OSM


def test_offline_hit():
    r = by_address("197348, г Санкт-Петербург, Богатырский пр., д. 2")
    assert r["oktmo"] == "40324000"
    assert r["source"] == "offline"


def test_offline_janino():
    r = by_address("Ленинградская обл., Всеволожский р-н, Янино, промзона")
    assert r["oktmo"] == "41612155"


def test_full_catalog_resolves_city_without_region():
    # раньше — OktmoError; теперь полный классификатор знает Владивосток
    r = by_address("г. Владивосток, ул. Светланская, 1")
    assert r["oktmo"] == "05701000" and r["source"] == "oktmo_full"


def test_miss_without_token_raises():
    # только улица в городе федерального значения: оффлайн округ не узнать
    with pytest.raises(OktmoError):
        by_address("Санкт-Петербург, Промышленная ул., 10")
