"""Загрузка справочников (ставки платы, коэффициенты) из data/*.json.

Справочники вынесены в JSON, чтобы эколог правил действующие ставки и
коэффициент индексации без правки кода.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# кэш по mtime: эколог правит ставки/коэффициенты в data/*.json на живом
# приложении — изменения подхватываются без перезапуска (lru_cache навсегда
# замораживал старые значения)
_CACHE: dict = {}


def _load(name: str) -> dict:
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Справочник не найден: {path}")
    mtime = path.stat().st_mtime
    hit = _CACHE.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    _CACHE[name] = (mtime, data)
    return data


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


_OKTMO_CACHE: dict = {"mtime": None, "entries": {}}


def oktmo_ref() -> dict:
    """Оффлайн-справочник ОКТМО по ключевым словам адреса (правится экологом).

    Перечитывается при изменении файла (по mtime) — без перезапуска приложения:
    эколог дописал строку в oktmo_ref.json → кнопка «Определить ОКТМО» сразу
    видит новую запись."""
    path = DATA_DIR / "oktmo_ref.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _OKTMO_CACHE["mtime"] != mtime:
        try:
            with path.open(encoding="utf-8") as f:
                _OKTMO_CACHE["entries"] = json.load(f).get("entries", {})
            _OKTMO_CACHE["mtime"] = mtime
        except (json.JSONDecodeError, OSError):
            return _OKTMO_CACHE["entries"]
    return _OKTMO_CACHE["entries"]
