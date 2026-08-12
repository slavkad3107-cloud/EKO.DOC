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

from ecodoc.core import sanitize
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
    year = ctx.period.year

    # С 2026 года ставки установлены НАПРЯМУЮ на каждый год (Распоряжение
    # Правительства РФ № 2409-р в ред. № 4110-р) — прежняя схема «ставки 2018 ×
    # коэффициент индексации» к ним не применяется. Для более ранних лет
    # остаётся старая схема.
    direct = (rates.get("rates_by_year") or {}).get(str(year)) if year else None
    if direct:
        rates = {**rates, **direct}

    # коэффициент индексации: сначала по отчётному году, иначе общий
    by_year = rates.get("indexation_by_year") or {}
    if direct:
        # Ставки года заданы актом напрямую. Единственный множитель — доп.
        # коэффициент (для 2025 это 1,045 по ПП РФ № 1034), и он применяется
        # не ко всем позициям: ставки, перенесённые из ПП РФ № 492, идут без
        # него — такие помечены в справочнике флагом no_extra.
        k_ind = D((rates.get("indexation_extra_by_year") or {}).get(str(year)) or 1)
        res.warnings.append(
            f"Ставки {year} года применены напрямую по действующему акту"
            + (f" с дополнительным коэффициентом {k_ind} " if k_ind != 1 else " ")
            + "(индексация к ставкам 2018 года не применяется). "
              "Проверьте перед сдачей.")
    elif year and str(year) in by_year:
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
    # К прямым ставкам года не применяется — они уже итоговые.
    extra_by_year = {} if direct else (rates.get("indexation_extra_by_year") or {})
    if year and str(year) in extra_by_year and extra_by_year[str(year)]:
        k_extra_year = D(extra_by_year[str(year)])
        k_ind = k_ind * k_extra_year
        res.warnings.append(
            f"К ставкам {year} применён дополнительный коэффициент "
            f"{k_extra_year} (ПП РФ №1034 от 10.07.2025); итоговый коэффициент "
            f"индексации = {k_ind}. Проверьте по действующему ПП перед сдачей.")

    by_section = {k: Decimal("0") for k in SECTIONS}

    if not year:
        res.warnings.append(
            "Отчётный год не указан — применён общий коэффициент индексации "
            f"{k_ind}. Заполните год во вкладке ДАННЫЕ: от него зависят ставки "
            "и коэффициенты, иначе сумма платы неверна.")

    # --- выбросы / сбросы ---
    for p in ctx.pollutants:
        table = rates["air"] if p.medium == Medium.AIR else rates["water"]
        entry, key = _find_rate(table, p.code, p.name)
        rate = D(entry["rate"]) if entry else Decimal("0")
        # часть ставок применяется без дополнительного коэффициента
        k_here = Decimal("1") if (entry or {}).get("no_extra") else k_ind
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
            amount = money(mass * rate * k_here * k_band * k_ot)
            # ставка 0 — это тоже «нет ставки»: раньше нулевая строка
            # справочника считалась найденной и плата обнулялась молча
            warn = ("" if (entry and rate > 0) else
                    f"нет ставки для кода {key or p.code} в справочнике — "
                    f"плата по веществу не начислена")
            if p.medium == Medium.AIR:
                sect = ("Р3" if band == "over" else "Р2") if is_flare else "Р1"
            else:
                sect = "Р4"
            line = PayLine(p.medium.value, key or p.code, p.name, band, mass,
                           rate, k_here, k_band, k_ot, amount, sect, warn)
            res.lines.append(line)
            by_section[sect] += amount
            if warn:
                # одно вещество — одно предупреждение (а не по разу на корзину)
                text = f"{p.name} ({key or p.code}): {warn}"
                if text not in res.warnings:
                    res.warnings.append(text)
            if sect == "Р1":
                res.total_air += amount       # только стационарные (без ПНГ)
            elif sect == "Р4":
                res.total_water += amount

    # --- размещение отходов (Р5 производство / Р6 ТКО / Р7-Р9) ---
    wclass = rates["waste_by_class"]
    wband = coef["waste_band"]
    for w in ctx.wastes:
        sect = _waste_section(w)
        entry = _waste_entry(w, wclass, sect)
        rate = D(entry.get("rate", 0))
        # ТКО: ставка установлена отдельным актом, дополнительный коэффициент
        # к ней не применяется (к остальным классам отходов — применяется)
        k_w = Decimal("1") if entry.get("no_extra") else k_ind
        # стимулирующий коэффициент Кст (ст. 16.3 ФЗ-7): 0.3 / 0 / 1 (по умолч.)
        k_st = D(w.k_st) if getattr(w, "k_st", None) is not None else Decimal("1")
        if k_st < 0 or k_st > 1:
            res.warnings.append(
                f"{w.name or w.fkko_code}: Кст={k_st} вне диапазона 0..1 — "
                f"проверьте (типовые значения 0; 0,3; 0,5; 0,67; 0,7)")
        for band, mass in (("norm", D(w.placed_norm)), ("over", D(w.placed_over))):
            if mass <= 0:
                continue
            k_band = D(wband[band])
            amount = money(mass * rate * k_w * k_band * k_st)
            line = PayLine("waste", w.fkko_code, w.name or w.fkko_code, band,
                           mass, rate, k_w, k_band, k_st, amount, sect)
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


def _find_rate(table: dict, code, name) -> tuple[dict | None, str]:
    """Ставка вещества по коду, а если код не совпал — по наименованию.

    Код ищем нормализованным: в перечнях ЗВ он четырёхзначный с ведущим нулём
    («0301»), а из документов и от ИИ приходит как «301» — без нормализации
    ставка не находилась и плата молча обнулялась.

    Поиск по наименованию нужен для сбросов: коды ЗВ для водных объектов и для
    воздуха — разные перечни, и в документах у одного и того же вещества
    («аммоний-ион») код может стоять из чужого перечня. Наименование в такой
    ситуации надёжнее кода."""
    key = sanitize.norm_code(code) or str(code or "").strip()
    entry = table.get(key) or table.get(str(code or "").strip())
    if entry:
        return entry, key
    nm = sanitize.norm_name(name)
    if not nm:
        return None, key
    for k, row in table.items():
        if not isinstance(row, dict):
            continue                    # служебные ключи вроде "_note"
        if sanitize.norm_name(row.get("name")) == nm:
            return row, k
    return None, key


def _waste_entry(w, wclass: dict, section: str = "") -> dict:
    """Строка справочника для отхода: ставка и её особенности.

    Ставка зависит не только от класса:
      • у ТКО IV класса она своя и намного ниже общей ставки IV класса
        (99,30 ₽/т против 1001,43 на 2025) — раздел Р6 берёт ключ «4_tko»;
      • у V класса три разные ставки: добывающая промышленность,
        перерабатывающая и прочие — раньше ключ «5_processing» не
        использовался никогда, и такие отходы считались как «прочие»
        (26,12 вместо 60,55 — вдвое дешевле).
    """
    cls = str(w.hazard_class)
    if section == "Р6" and cls == "4" and wclass.get("4_tko") is not None:
        key = "4_tko"
    elif cls == "5":
        kind = (getattr(w, "industry", "") or "").strip().lower()
        if w.is_mining or kind.startswith("добыв"):
            key = "5_mining"
        elif kind.startswith("перераб") or kind.startswith("обрабат"):
            key = "5_processing"
        else:
            key = "5_other"
        if key not in wclass:
            key = "5_other"
    else:
        key = cls
    row = wclass.get(key)
    if isinstance(row, dict):
        return row
    return {"rate": row if row is not None else 0}


def _waste_rate(w, wclass: dict, section: str = "") -> Decimal:
    """Ставка за размещение тонны отхода (без коэффициентов)."""
    return D(_waste_entry(w, wclass, section).get("rate", 0))
