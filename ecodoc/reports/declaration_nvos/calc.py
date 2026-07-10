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
    warning: str = ""    # напр. «нет ставки в справочнике»


@dataclass
class PaymentResult:
    lines: list[PayLine] = field(default_factory=list)
    total_air: Decimal = Decimal("0")
    total_water: Decimal = Decimal("0")
    total_waste: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    warnings: list[str] = field(default_factory=list)


_BANDS = ("norm", "limit", "over")


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
        for band in _BANDS:
            mass = D(masses[band])
            if mass <= 0:
                continue
            k_band = D(coef["band"][band])
            amount = money(mass * rate * k_ind * k_band * k_ot)
            warn = "" if entry else f"нет ставки для кода {p.code} в справочнике"
            line = PayLine(p.medium.value, p.code, p.name, band, mass, rate,
                           k_ind, k_band, k_ot, amount, warn)
            res.lines.append(line)
            if warn:
                res.warnings.append(f"{p.name} ({p.code}): {warn}")
            if p.medium == Medium.AIR:
                res.total_air += amount
            else:
                res.total_water += amount

    # --- размещение отходов ---
    wclass = rates["waste_by_class"]
    wband = coef["waste_band"]
    for w in ctx.wastes:
        rate = _waste_rate(w, wclass)
        for band, mass in (("norm", D(w.placed_norm)), ("over", D(w.placed_over))):
            if mass <= 0:
                continue
            k_band = D(wband[band])
            amount = money(mass * rate * k_ind * k_band)
            line = PayLine("waste", w.fkko_code, w.name or w.fkko_code, band,
                           mass, rate, k_ind, k_band, Decimal("1"), amount)
            res.lines.append(line)
            res.total_waste += amount

    res.total_air = money(res.total_air)
    res.total_water = money(res.total_water)
    res.total_waste = money(res.total_waste)
    res.total = money(res.total_air + res.total_water + res.total_waste)
    return res


def _waste_rate(w, wclass: dict) -> Decimal:
    cls = str(w.hazard_class)
    if cls == "5":
        key = "5_mining" if w.is_mining else "5_other"
        return D(wclass.get(key, 0))
    return D(wclass.get(cls, 0))
