"""Расчёт платы за НВОС.

Плата по каждой позиции:
    плата = масса × ставка × Кинд × Кполоса × Кдоп

где Кполоса — коэффициент за нормативную «корзину» (в пределах норматива /
лимита / сверх), Кинд — коэффициент индексации ставок, Кдоп — прочие
коэффициенты (территория, специальные коэффициенты за отходы).

Основание: ст. 16.3 ФЗ-7 «Об охране окружающей среды», ПП РФ №913 (ставки),
ПП РФ №255 (правила исчисления). Числа берутся из data/*.json — проверяйте
ставки и коэффициент индексации перед сдачей.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ecodoc.core.models import Medium, ReportContext
from ecodoc.core.money import D, money
from ecodoc.core.refdata import coefficients, rates_nvos


# Разделы расчёта по действующей форме декларации (Приказ №1043 в ред. № 241
# от 29.04.2025). Р1 выбросы стационарными; Р2/Р3 ПНГ (в пределах/сверх лимита);
# Р4 сбросы; Р5 отходы производства; Р6 ТКО; Р7 побочные продукты производства;
# Р8 вскрышные/вмещающие породы; Р9 побочные продукты животноводства.
SECTIONS = {
    "Р1": "Выбросы ЗВ в атмосферу стационарными источниками",
    "Р2": "Выбросы при сжигании/рассеивании ПНГ (в пределах лимита)",
    "Р3": "Выбросы при сжигании/рассеивании ПНГ (сверх лимита)",
    "Р4": "Сбросы ЗВ в водные объекты",
    "Р5": "Размещение отходов производства",
    "Р6": "Размещение твёрдых коммунальных отходов (ТКО)",
    "Р7": "Размещение побочных продуктов производства",
    "Р8": "Размещение вскрышных и вмещающих горных пород",
    "Р9": "Размещение побочных продуктов животноводства",
}
_WASTE_SECTION = {"prod": "Р5", "tko": "Р6", "byproduct": "Р7",
                  "overburden": "Р8", "livestock": "Р9"}


@dataclass
class PayLine:
    medium: str          # air | water | waste
    code: str
    name: str
    band: str            # norm | limit | over
    mass: Decimal
    rate: Decimal
    k_ind: Decimal
    k_band: Decimal
    k_extra: Decimal
    amount: Decimal      # итог по строке, руб. (округлён до копеек)
    section: str = "Р1"  # раздел декларации Р1..Р9
    warning: str = ""    # напр. «нет ставки в справочнике»


@dataclass
class PaymentResult:
    lines: list[PayLine] = field(default_factory=list)
    by_section: dict = field(default_factory=dict)  # {"Р1": Decimal, ...}
    total_air: Decimal = Decimal("0")
    total_water: Decimal = Decimal("0")
    total_waste: Decimal = Decimal("0")   # Р5+Р6+Р7+Р8+Р9 (все отходы)
    total: Decimal = Decimal("0")
    warnings: list[str] = field(default_factory=list)


_BANDS = ("norm", "limit", "over")


def _waste_section(w) -> str:
    kind = (getattr(w, "waste_kind", "") or "").strip().lower()
    if kind in _WASTE_SECTION:
        return _WASTE_SECTION[kind]
    code = str(getattr(w, "fkko_code", "")).replace(" ", "")
    return "Р6" if code.startswith("73") else "Р5"  # ТКО-блок ФККО «7 3…»


def calculate(ctx: ReportContext) -> PaymentResult:
    rates = rates_nvos()
    coef = coefficients()
    res = PaymentResult()

    # коэффициент индексации: сначала по отчётному году, иначе общий
    by_year = rates.get("indexation_by_year") or {}
    year = ctx.period.year
    if year and str(year) in by_year:
        val = by_year[str(year)]
        if val is None:
            res.warnings.append(
                f"Коэффициент индексации на {year} год не задан "
                f"(indexation_by_year в data/rates_nvos.json = null) — уточните "
                f"по действующему Постановлению Правительства и впишите значение. "
                f"Пока применён общий indexation.")
            k_ind = D(rates.get("indexation", 1))
        else:
            k_ind = D(val)
    else:
        k_ind = D(rates.get("indexation", 1))

    # дополнительный повышающий коэффициент по году (напр. 1,045 за 2025 —
    # ПП РФ №1034 от 10.07.2025). Умножается на основную индексацию.
    extra_by_year = rates.get("indexation_extra_by_year") or {}
    if year and str(year) in extra_by_year and extra_by_year[str(year)]:
        k_extra_year = D(extra_by_year[str(year)])
        k_ind = k_ind * k_extra_year
        res.warnings.append(
            f"К ставкам {year} применён дополнительный коэффициент "
            f"{k_extra_year} (ПП РФ №1034 от 10.07.2025); итоговый коэффициент "
            f"индексации = {k_ind}. Проверьте по действующему ПП перед сдачей.")

    by_section = {k: Decimal("0") for k in SECTIONS}

    # --- выбросы / сбросы ---
    for p in ctx.pollutants:
        table = rates["air"] if p.medium == Medium.AIR else rates["water"]
        entry = table.get(p.code)
        rate = D(entry["rate"]) if entry else Decimal("0")
        k_ot = D(p.k_ot) if p.k_ot is not None else D(coef.get("k_ot_default", 1))
        if k_ot < 1:
            res.warnings.append(
                f"{p.name} ({p.code}): коэффициент территории {k_ot} < 1 — "
                f"проверьте (обычно 1, для ООПТ 2)")
        masses = {"norm": p.mass_norm, "limit": p.mass_limit, "over": p.mass_over}
        is_flare = getattr(p, "is_flare", False)
        for band in _BANDS:
            mass = D(masses[band])
            if mass <= 0:
                continue
            k_band = D(coef["band"][band])
            amount = money(mass * rate * k_ind * k_band * k_ot)
            warn = "" if entry else f"нет ставки для кода {p.code} в справочнике"
            if p.medium == Medium.AIR:
                sect = ("Р3" if band == "over" else "Р2") if is_flare else "Р1"
            else:
                sect = "Р4"
            line = PayLine(p.medium.value, p.code, p.name, band, mass, rate,
                           k_ind, k_band, k_ot, amount, sect, warn)
            res.lines.append(line)
            by_section[sect] += amount
            if warn:
                res.warnings.append(f"{p.name} ({p.code}): {warn}")
            if sect == "Р1":
                res.total_air += amount       # только стационарные (без ПНГ)
            elif sect == "Р4":
                res.total_water += amount

    # --- размещение отходов (Р5 производство / Р6 ТКО / Р7-Р9) ---
    wclass = rates["waste_by_class"]
    wband = coef["waste_band"]
    for w in ctx.wastes:
        rate = _waste_rate(w, wclass)
        sect = _waste_section(w)
        for band, mass in (("norm", D(w.placed_norm)), ("over", D(w.placed_over))):
            if mass <= 0:
                continue
            k_band = D(wband[band])
            amount = money(mass * rate * k_ind * k_band)
            line = PayLine("waste", w.fkko_code, w.name or w.fkko_code, band,
                           mass, rate, k_ind, k_band, Decimal("1"), amount, sect)
            res.lines.append(line)
            by_section[sect] += amount
            res.total_waste += amount

    res.by_section = {k: money(v) for k, v in by_section.items()}
    res.total_air = money(res.total_air)
    res.total_water = money(res.total_water)
    res.total_waste = money(res.total_waste)
    res.total = money(res.total_air + res.total_water + res.total_waste
                      + res.by_section["Р2"] + res.by_section["Р3"])
    return res


def _waste_rate(w, wclass: dict) -> Decimal:
    cls = str(w.hazard_class)
    if cls == "5":
        key = "5_mining" if w.is_mining else "5_other"
        return D(wclass.get(key, 0))
    return D(wclass.get(cls, 0))
