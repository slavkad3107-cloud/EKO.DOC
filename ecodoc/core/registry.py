"""Реестр форм отчётности.

Каждая форма регистрируется декоратором @register и становится доступной
в CLI по своему коду. Так новую форму можно добавить одним файлом, не трогая
остальной код.
"""
from __future__ import annotations

from typing import Callable, Type

_REGISTRY: dict[str, Type] = {}


def register(report_cls: Type) -> Type:
    code = getattr(report_cls, "code", None)
    if not code:
        raise ValueError(f"{report_cls.__name__}: не задан атрибут `code`")
    if code in _REGISTRY:
        raise ValueError(f"Форма с кодом {code!r} уже зарегистрирована")
    _REGISTRY[code] = report_cls
    return report_cls


def get(code: str):
    if code not in _REGISTRY:
        raise KeyError(code)
    return _REGISTRY[code]


def all_reports() -> dict[str, Type]:
    return dict(_REGISTRY)


def load_all() -> None:
    """Импортировать все пакеты форм, чтобы сработали декораторы @register."""
    import importlib

    for mod in (
        "ecodoc.reports.declaration_nvos.report",
        "ecodoc.reports.waste_movement.report",
        "ecodoc.reports.pek.report",
        "ecodoc.reports.cadastre_spb.report",
        "ecodoc.reports.tp2_waste.report",
        "ecodoc.reports.tp2_air.report",
        "ecodoc.reports.tp2_water.report",
        "ecodoc.reports.waste_report_iii.report",
        "ecodoc.reports.scaffolds",
    ):
        importlib.import_module(mod)
