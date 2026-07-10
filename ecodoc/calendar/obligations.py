"""Каталог экологических обязанностей предприятия.

Каждая обязанность знает: к кому применяется (предикат по профилю), когда
исполняется (сроки) и на каком основании. Данные декларативные — добавление
новой обязанности не требует правки движка.

ВНИМАНИЕ: сроки и применимость основаны на действующих НПА (ФЗ-7, приказы
Минприроды). Сверяйте перед сезоном — даты и пороги периодически меняются;
для кадастра отходов срок региональный.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class OrgProfile:
    """Профиль природопользователя — вход для расчёта обязанностей."""
    categories: set[str] = field(default_factory=set)  # {"I","II","III","IV"}
    has_air: bool = False        # есть выбросы (стационарные источники)
    has_water: bool = False      # есть сбросы в водные объекты
    has_waste: bool = False      # образуются отходы
    has_hazardous_waste: bool = False  # отходы I-IV класса (для паспортов)
    is_msp: bool = False         # субъект малого/среднего предпринимательства
    region_codes: set[str] = field(default_factory=set)  # {"78","47",...}

    def cat_in(self, *allowed: str) -> bool:
        return bool(self.categories & set(allowed))


@dataclass
class Obligation:
    code: str
    title: str
    domain: str               # "reporting" | "development"
    kind: str                 # "periodic" | "possession"
    periodicity: str          # "год" | "квартал" | "постоянно" | "по наличию"
    basis: str                # нормативное основание
    applies: Callable[[OrgProfile], bool]
    where: str = "ЛКПП РПН"
    coverage: str = ""        # что покрывает срок (для periodic)
    due: list[tuple[int, int]] = field(default_factory=list)  # (месяц, день) в календарном году


# --- предикаты применимости (читаемые) ---
def _I_III(p: OrgProfile) -> bool: return p.cat_in("I", "II", "III")
def _I_II(p: OrgProfile) -> bool: return p.cat_in("I", "II")
def _any_object(p: OrgProfile) -> bool: return bool(p.categories)


OBLIGATIONS: list[Obligation] = [
    # ─────────────── Контур «Отчётность» (периодическая) ───────────────
    Obligation(
        "2tp-air", "2-ТП (воздух)", "reporting", "periodic", "год",
        "Приказ Росстата № 661 от 08.11.2018 (ОКУД 0609012); ст. 67 ФЗ-7",
        lambda p: p.has_air and _I_III(p),
        coverage="за предыдущий год", due=[(1, 22)]),
    Obligation(
        "2tp-water", "2-ТП (водхоз)", "reporting", "periodic", "год",
        "Приказ Росстата № 445 от 02.10.2024 (ОКУД 0609060)",
        lambda p: p.has_water,
        where="территориальное Бассейновое водное управление (Модуль респондента / ГИС ЦП «Вода»)",
        coverage="за предыдущий год", due=[(1, 22)]),
    Obligation(
        "waste-report-iii",
        "Отчётность об образовании, утилизации… отходов (III кат./МСП)",
        "reporting", "periodic", "год",
        "III кат. (федеральный надзор) — в составе отчёта ПЭК (Приказ №109); "
        "МСП регионального надзора — региональный НПА. Приказ №30 отменён с 01.01.2021",
        lambda p: p.cat_in("III") or p.is_msp,
        coverage="за предыдущий год; III кат. — со сроком ПЭК (25 марта); "
                 "МСП — региональный срок (сверить)", due=[(3, 25)]),
    Obligation(
        "2tp-waste", "2-ТП (отходы)", "reporting", "periodic", "год",
        "Приказ Росстата № 614 от 06.11.2025 (заменил № 627; ОКУД 0609013)",
        lambda p: p.has_waste,
        coverage="за предыдущий год", due=[(2, 1)]),
    Obligation(
        "declaration-nvos", "Декларация о плате за НВОС", "reporting",
        "periodic", "год",
        "ст. 16.4 ФЗ-7; Приказ Минприроды № 1043 от 10.12.2020 (ред. № 241 от 29.04.2025)",
        _I_III,  # IV категория плату не вносит
        coverage="за предыдущий год", due=[(3, 10)]),
    Obligation(
        "pek-report", "Отчёт об организации и о результатах ПЭК", "reporting",
        "periodic", "год",
        "ст. 67 ФЗ-7; форма — Приказ Минприроды № 173 от 15.03.2024 (ред. № 262 "
        "от 12.05.2025); сроки/программа — Приказ № 109 от 18.02.2022",
        _I_III, coverage="за предыдущий год", due=[(3, 25)]),
    Obligation(
        "cadastre", "Региональный кадастр отходов", "reporting", "periodic",
        "год",
        "СПб: Распоряжение Комитета по природопользованию № 87-р от 26.04.2023 "
        "(ред. № 28-р от 14.02.2025); ЛО/иные регионы — свой НПА",
        lambda p: p.has_waste and bool(p.region_codes & {"78", "47", "40"}),
        where="подсистема «Ведение регионального кадастра отходов» ГИС СПб (УКЭП) "
              "или kadastr@kpoos.gov.spb.ru",
        coverage="за предыдущий год; СПб — не позднее 31 марта по каждому "
                 "обособленному подразделению (ЛО/иные регионы — сверить срок)",
        due=[(3, 31)]),
    Obligation(
        "nvos-advance", "Авансовый платёж за НВОС", "reporting", "periodic",
        "квартал", "ст. 16.4 ФЗ-7",
        lambda p: _I_III(p) and not p.is_msp,
        where="платёж в бюджет",
        coverage="за 1/2/3 кв. текущего года (МСП авансы не платят)",
        due=[(4, 20), (7, 20), (10, 20)]),
    Obligation(
        "waste-accounting", "Учёт в области обращения с отходами (данные учёта)",
        "reporting", "periodic", "квартал",
        "Приказ Минприроды № 1028 от 08.12.2020 (ред. № 825 от 13.12.2023; "
        "с 01.09.2026 — Приказ № 227 от 16.04.2026)",
        lambda p: p.has_waste, where="ведётся и хранится на предприятии",
        coverage="обобщение данных по итогам квартала",
        due=[(1, 10), (4, 10), (7, 10), (10, 10)]),

    # ─────────────── Контур «Разработка» (наличие/актуализация) ───────────────
    Obligation(
        "nvos-registration", "Постановка объекта на учёт НВОС (актуализация)",
        "development", "possession", "по наличию", "ст. 69.2 ФЗ-7",
        _any_object),
    Obligation(
        "waste-passport", "Паспорта отходов I–IV класса", "development",
        "possession", "по наличию", "ст. 14 ФЗ-89; Приказ Минприроды №1026",
        lambda p: p.has_hazardous_waste, where="разработка + хранение"),
    Obligation(
        "pek-program", "Программа ПЭК", "development", "possession",
        "по наличию", "ст. 67 ФЗ-7; Приказ Минприроды №109",
        _I_III, where="разработка + хранение"),
    Obligation(
        "ndv-project", "Проект нормативов допустимых выбросов (НДВ)",
        "development", "possession", "по наличию", "ст. 22 ФЗ-7",
        lambda p: _I_II(p) and p.has_air, where="разработка (расчёт рассеивания)"),
    Obligation(
        "nds-project", "Проект нормативов допустимых сбросов (НДС)",
        "development", "possession", "по наличию", "ст. 22 ФЗ-7",
        lambda p: p.has_water, where="разработка"),
    Obligation(
        "szz-project", "Проект санитарно-защитной зоны (СЗЗ)", "development",
        "possession", "по наличию", "СанПиН; ПП РФ №222",
        lambda p: _I_II(p) or p.has_air, where="разработка (рассеивание+физфакторы)"),
    Obligation(
        "nool", "Нормативы образования отходов и лимиты (НООЛР)", "development",
        "possession", "по наличию", "ст. 18 ФЗ-89",
        _I_II, where="разработка"),
    Obligation(
        "ker", "Комплексное экологическое разрешение (КЭР)", "development",
        "possession", "по наличию", "ст. 31.1 ФЗ-7",
        lambda p: p.cat_in("I")),
    Obligation(
        "dvos", "Декларация о воздействии на окружающую среду (ДВОС)",
        "development", "possession", "по наличию", "ст. 31.2 ФЗ-7",
        lambda p: p.cat_in("II")),
]
