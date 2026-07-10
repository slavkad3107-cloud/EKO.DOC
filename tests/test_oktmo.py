"""Оффлайн-резолвер ОКТМО (бесплатная замена DaData, без токена)."""
import os

import pytest

from ecodoc.parsers.oktmo import OktmoError, by_address


def test_offline_hit(monkeypatch):
    monkeypatch.delenv("DADATA_TOKEN", raising=False)
    r = by_address("197348, г Санкт-Петербург, Богатырский пр., д. 2")
    assert r["oktmo"] == "40324000"
    assert r["source"] == "offline"


def test_offline_janino(monkeypatch):
    monkeypatch.delenv("DADATA_TOKEN", raising=False)
    r = by_address("Ленинградская обл., Всеволожский р-н, Янино, промзона")
    assert r["oktmo"] == "41612155"


def test_miss_without_token_raises(monkeypatch):
    monkeypatch.delenv("DADATA_TOKEN", raising=False)
    with pytest.raises(OktmoError):
        by_address("г. Владивосток, ул. Светланская, 1")
