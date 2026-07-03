"""Денежная и числовая арифметика без ошибок плавающей точки.

Все суммы платы за НВОС считаются в Decimal и округляются по правилам
бухгалтерского/налогового округления (ROUND_HALF_UP) до 2 знаков.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Union

Number = Union[int, float, str, Decimal, None]

CENT = Decimal("0.01")


def D(value: Number) -> Decimal:
    """Безопасно привести значение к Decimal.

    Принимает строки в т.ч. с запятой («663,2») и пробелами-разделителями.
    Пустое/None -> 0.
    """
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, float):
        # через str, чтобы не тащить двоичный шум 0.1 -> 0.1000000000000000055
        return Decimal(str(value))
    s = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as exc:  # pragma: no cover - защита от мусора
        raise ValueError(f"Не число: {value!r}") from exc


def money(value: Number) -> Decimal:
    """Округлить до копеек (2 знака, half-up)."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt_money(value: Number) -> str:
    """«1 234 567.89» — для печатных форм."""
    q = money(value)
    sign = "-" if q < 0 else ""
    digits, _, frac = f"{abs(q):.2f}".partition(".")
    groups = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return f"{sign}{' '.join(groups)}.{frac}"
