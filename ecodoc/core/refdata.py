"""Загрузка справочников (ставки платы, коэффициенты) из data/*.json.

Справочники вынесены в JSON, чтобы эколог правил действующие ставки и
коэффициент индексации без правки кода.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Справочник не найден: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def rates_nvos() -> dict:
    """Ставки платы за НВОС (выбросы, сбросы, отходы) + коэффициент индексации."""
    return _load("rates_nvos.json")


def coefficients() -> dict:
    """Коэффициенты к ставкам (по нормативным корзинам, по классам отходов и т.п.)."""
    return _load("coefficients.json")


def substances() -> list[dict]:
    """Справочник веществ (код, наименование, среда, ПДК). Для автоподстановки."""
    try:
        return _load("substances.json").get("substances", [])
    except FileNotFoundError:
        return []


def common_wastes() -> list[dict]:
    """Частые отходы (ФККО, наименование, класс) — для автоподстановки."""
    try:
        return _load("substances.json").get("common_wastes", [])
    except FileNotFoundError:
        return []
