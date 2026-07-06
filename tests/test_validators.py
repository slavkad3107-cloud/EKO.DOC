"""Проверки контрольных сумм реквизитов и подсказки о сроке."""
from datetime import date

from ecodoc.core.validators import inn_valid, ogrn_valid
from ecodoc.calendar.engine import deadline_note


def test_inn_checksum():
    assert inn_valid("7707083893")      # ПАО Сбербанк (реальный)
    assert inn_valid("7801234564")      # валидная контрольная сумма
    assert not inn_valid("7801234567")  # неверная контрольная цифра
    assert not inn_valid("123")         # не та длина
    assert not inn_valid("абвгдежзик")  # не цифры


def test_ogrn_checksum():
    assert ogrn_valid("1027700132195")   # Сбербанк
    assert not ogrn_valid("1027700132196")
    assert not ogrn_valid("")


def test_deadline_overdue():
    note = deadline_note("declaration-nvos", 2025, date(2026, 7, 5))
    assert "истёк" in note


def test_deadline_soon():
    note = deadline_note("declaration-nvos", 2025, date(2026, 3, 1))
    assert "осталось" in note or "—" in note


def test_deadline_far_is_silent():
    assert deadline_note("declaration-nvos", 2025, date(2026, 1, 1)) == ""
    assert deadline_note("declaration-nvos", 0, date(2026, 1, 1)) == ""
