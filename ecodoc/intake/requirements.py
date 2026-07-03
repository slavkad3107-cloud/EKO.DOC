"""Требования форм к данным и документам: что нужно, чтобы форма собралась.

Декларативный реестр. Для каждой формы:
  fields — какие поля контекста обязательны (путь + человекочитаемое имя);
  docs   — какие входящие документы обычно нужны (для подсказки «что донести»).

Используется командой `ecodoc intake` для отчёта о полноте.
"""
from __future__ import annotations

from decimal import Decimal

from ecodoc.core.models import ReportContext

# Общие реквизиты, без которых не собирается ни одна форма
_BASE_FIELDS = [
    ("organization.name", "наименование организации"),
    ("organization.inn", "ИНН"),
    ("organization.oktmo", "ОКТМО"),
    ("period.year", "отчётный год"),
]
_BASE_DOCS = ["карточка организации / выписка ЕГРЮЛ",
              "свидетельство о постановке объекта НВОС на учёт"]

REQUIREMENTS: dict[str, dict] = {
    "declaration-nvos": {
        "fields": _BASE_FIELDS + [("objects", "объект(ы) НВОС"),
                                  ("pollutants|wastes", "массы выбросов/сбросов/отходов")],
        "docs": _BASE_DOCS + [
            "разрешительные документы (НДВ/НДС/лимиты) или декларация о воздействии",
            "данные учёта выбросов/сбросов за год",
            "акты передачи отходов на размещение (полигон)",
            "платёжные поручения по авансовым платежам (для зачёта)",
        ],
    },
    "waste-movement": {
        "fields": _BASE_FIELDS + [("wastes", "позиции отходов (ФККО) с массами")],
        "docs": _BASE_DOCS + [
            "паспорта отходов I–IV класса",
            "акты/справки об утилизации, обезвреживании, размещении",
            "договоры с транспортировщиками и операторами",
        ],
    },
    "waste-report-iii": {
        "fields": _BASE_FIELDS + [("wastes", "позиции отходов (ФККО) с массами")],
        "docs": _BASE_DOCS + [
            "акты/справки о передаче отходов (с ИНН и лицензией получателя)",
        ],
    },
    "pek": {
        "fields": _BASE_FIELDS + [("objects", "объект(ы) НВОС"),
                                  ("extra.pek", "программа/результаты ПЭК")],
        "docs": _BASE_DOCS + [
            "программа ПЭК (утверждённая)",
            "протоколы КХА аккредитованной лаборатории за год",
        ],
    },
    "2tp-waste": {
        "fields": _BASE_FIELDS + [("wastes", "движение отходов за год")],
        "docs": _BASE_DOCS + ["журнал учёта отходов (пр. №1028)",
                              "акты передачи отходов"],
    },
    "2tp-air": {
        "fields": _BASE_FIELDS + [("pollutants", "выбросы за год")],
        "docs": _BASE_DOCS + ["инвентаризация выбросов / том НДВ",
                              "данные учёта работы ГОУ"],
    },
    "2tp-water": {
        "fields": _BASE_FIELDS + [("extra.water", "блок водоучёта")],
        "docs": _BASE_DOCS + ["журналы учёта водопотребления/водоотведения",
                              "договор водопользования / решение"],
    },
    "cadastre-spb": {
        "fields": _BASE_FIELDS + [("wastes", "движение отходов за год")],
        "docs": _BASE_DOCS + ["акты передачи отходов (по каждому получателю)"],
    },
}


def _get_path(ctx: ReportContext, path: str):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def _filled(val) -> bool:
    if val is None:
        return False
    if isinstance(val, (list, dict, str)):
        return bool(val)
    if isinstance(val, (int, Decimal)):
        return val != 0
    return True


def check(ctx: ReportContext, form: str) -> tuple[list[str], list[str]]:
    """Вернуть (чего не хватает в данных, какие документы обычно нужны)."""
    req = REQUIREMENTS.get(form)
    if not req:
        return [], []
    missing = []
    for path, label in req["fields"]:
        # "a|b" — достаточно любого из
        if any(_filled(_get_path(ctx, p)) for p in path.split("|")):
            continue
        missing.append(label)
    return missing, req["docs"]


def check_all(ctx: ReportContext) -> dict[str, list[str]]:
    """{форма: [чего не хватает]} по всем формам сразу."""
    return {form: check(ctx, form)[0] for form in REQUIREMENTS}
