"""Расчёт нормативов образования отходов для раздела ООС — типовые формулы.

Формулы и исходные коэффициенты взяты из реальных томов (АК-01-25-ООС1,
разд. 9.1/9.3) и из «Сборника удельных показателей образования отходов»
(1999) / «Методических рекомендаций по оценке объёмов образования отходов»
(НИЦПУРО, 2003). Всё, что здесь считается, — только арифметика по данным
пользователя (ведомость материалов, численность, ёмкости). Нормативы (%)
по умолчанию — справочные, их можно переопределить в исходных данных.

Почему считаем сами: экспертиза требует расчёт по КАЖДОМУ отходу с формулой,
исходными данными и таблицей (АК-01-25 — таблицы 9.1.1–9.1.16, 9.3.1–9.3.9);
одной строкой «мусор 1,9 т» раздел не принимают.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

D3 = Decimal("0.001")


def _d(v, default="0") -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else default).replace(",", "."))
    except Exception:
        return Decimal(default)


def r3(v: Decimal) -> Decimal:
    return v.quantize(D3, rounding=ROUND_HALF_UP)


# ── справочник строительных материалов → отход (ФККО, норматив %, плотность) ─
# Нормативы — «Сборник удельных показателей…» (1999), как в АК-01-25 табл. 9.1.4–9.1.13.
MATERIAL_WASTE: dict[str, dict] = {
    "бетон": {"fkko": "82220101215", "name": "Лом бетонных изделий, отходы бетона в "
              "кусковой форме", "pct": 0.3, "density": 2.4, "unit": "м3", "hazard": 5},
    "железобетон": {"fkko": "82230101215", "name": "Лом железобетонных изделий, отходы "
                    "железобетона в кусковой форме", "pct": 1, "density": 2.4,
                    "unit": "м3", "hazard": 5},
    "металл": {"fkko": "46101001205", "name": "Лом и отходы, содержащие незагрязненные "
               "черные металлы в виде изделий, кусков, несортированные", "pct": 1,
               "density": 7.8, "unit": "т", "hazard": 5},
    "древесина": {"fkko": "40419000515", "name": "Прочая продукция из натуральной "
                  "древесины, утратившая потребительские свойства, незагрязненная",
                  "pct": 3, "density": 0.6, "unit": "м3", "hazard": 5},
    "кирпич": {"fkko": "82310101215", "name": "Лом строительного кирпича "
               "незагрязненный", "pct": 1, "density": 0.6, "unit": "т", "hazard": 5},
    "керамика": {"fkko": "82320101215", "name": "Лом черепицы, керамики "
                 "незагрязненный", "pct": 2, "density": 1.4, "unit": "м3", "hazard": 5},
    "песок": {"fkko": "81910001495", "name": "Отходы песка незагрязненные", "pct": 1.5,
              "density": 1.5, "unit": "м3", "hazard": 5},
    "щебень": {"fkko": "81910003215", "name": "Отходы строительного щебня "
               "незагрязненные", "pct": 2, "density": 1.2, "unit": "м3", "hazard": 5},
    "асфальтобетон": {"fkko": "83020001714", "name": "Лом асфальтовых и "
                      "асфальтобетонных покрытий", "pct": 2, "density": 2.4,
                      "unit": "м3", "hazard": 4},
    "гипсокартон": {"fkko": "82420001725", "name": "Отходы затвердевшего "
                    "гипсокартона", "pct": 2, "density": 0.8, "unit": "м3", "hazard": 5},
    "упаковка": {"fkko": "40518301605", "name": "Отходы бумаги и картона от "
                 "упаковочных материалов", "pct": 100, "density": 0.1, "unit": "т",
                 "hazard": 5},
}


def material_waste(materials: list[dict]) -> list[dict]:
    """Отходы строительных материалов: М = m·К/100 (м3 или т), масса = V·ρ.

    Вход: [{"name": "Бетон", "qty": 4027, "unit": "м3", "kind": "бетон",
            "pct": 0.3?, "density": 2.4?, "fkko"?, "waste_name"?}].
    Неизвестный kind без fkko/pct — строка с пометкой «требуется»."""
    out = []
    for i, m in enumerate(materials, start=1):
        kind = str(m.get("kind") or m.get("name") or "").strip().lower()
        ref = MATERIAL_WASTE.get(kind) or next(
            (v for k, v in MATERIAL_WASTE.items() if k in kind), None) or {}
        pct = _d(m.get("pct"), str(ref.get("pct", "")) or "0")
        density = _d(m.get("density"), str(ref.get("density", "")) or "0")
        qty = _d(m.get("qty"))
        unit = str(m.get("unit") or ref.get("unit") or "м3")
        fkko = str(m.get("fkko") or ref.get("fkko") or "")
        wname = str(m.get("waste_name") or ref.get("name") or "")
        row = {"n": i, "material": m.get("name") or kind, "qty": qty, "unit": unit,
               "pct": pct, "density": density, "fkko": fkko, "waste_name": wname,
               "hazard": int(m.get("hazard") or ref.get("hazard") or
                             (fkko[-1] if fkko and fkko[-1].isdigit() else 5)),
               "note": ""}
        if not pct or not density or not fkko:
            row["note"] = ("[требуется: удельный норматив образования, плотность "
                           f"и код ФККО для материала «{row['material']}»]")
            row["m3"], row["t"] = Decimal("0"), Decimal("0")
        elif unit == "т":
            t = qty * pct / 100
            row["t"], row["m3"] = r3(t), r3(t / density)
        else:
            m3 = qty * pct / 100
            row["m3"], row["t"] = r3(m3), r3(m3 * density)
        out.append(row)
    return out


def tko_construction(workers: int, itr: int, months: int,
                     norm_worker: Decimal = Decimal("0.22"),
                     norm_itr: Decimal = Decimal("1.1"),
                     density: Decimal = Decimal("0.18")) -> list[dict]:
    """Мусор от бытовых помещений на стройке: М = p·n·c·ρ/12 (АК-01-25 табл. 9.1.1).

    Нормы накопления 0,22 м3/год на рабочего и 1,1 м3/год на ИТР — из того же
    тома (нормы накопления ТБО региона); плотность 0,18 т/м3."""
    rows = []
    for label, p, n in (("Рабочие", workers, norm_worker), ("ИТР", itr, norm_itr)):
        if not p:
            continue
        m3 = Decimal(p) * n * Decimal(months) / 12
        rows.append({"label": label, "months": months, "people": p, "norm": n,
                     "density": density, "m3": r3(m3), "t": r3(m3 * density)})
    return rows


def wheel_wash(cars_per_day: Decimal, water_per_car_m3: Decimal, days: int,
               c1_oil: Decimal = Decimal("200"), c2_oil: Decimal = Decimal("20"),
               c1_susp: Decimal = Decimal("4500"), c2_susp: Decimal = Decimal("200"),
               humidity_pct: Decimal = Decimal("60"),
               density: Decimal = Decimal("1.4")) -> list[dict]:
    """Осадок мойки колёс: Q = (C1−C2)·Q·10⁻⁶·P/(1−B/100), т (АК-01-25 табл. 9.1.3)."""
    q = cars_per_day * water_per_car_m3
    rows = []
    for label, c1, c2 in (("Всплывающая пленка из нефтеуловителей", c1_oil, c2_oil),
                          ("Взвешенные вещества", c1_susp, c2_susp)):
        t = (c1 - c2) * q * Decimal("0.000001") * Decimal(days) / (1 - humidity_pct / 100)
        rows.append({"label": label, "q": q, "c1": c1, "c2": c2, "humidity": humidity_pct,
                     "days": days, "t": r3(t), "m3": r3(t / density)})
    return rows


def electrodes(total_t: Decimal, pct: Decimal = Decimal("15"),
               density: Decimal = Decimal("2.5")) -> dict:
    """Огарки электродов: 15 % от расхода электродов, ρ = 2,5 т/м3 (табл. 9.1.10)."""
    t = total_t * pct / 100
    return {"total": total_t, "pct": pct, "density": density, "t": r3(t),
            "m3": r3(t / density)}


def soil_excess(volume_m3: Decimal, density: Decimal = Decimal("1.6")) -> dict:
    """Избыток грунта: масса = V·ρ (табл. 9.1.14); весь объём — к передаче."""
    return {"m3": r3(volume_m3), "density": density, "t": r3(volume_m3 * density)}


def cesspool(people: int, shifts: int, norm_m3: Decimal = Decimal("0.0055"),
             density: Decimal = Decimal("1")) -> dict:
    """Отходы из выгребных ям (биотуалеты): M = N·смены·норма/1000 (табл. 9.1.15).

    Делитель 1000 — так считает эталон (47 чел × 1440 смен × 0,0055 = 0,372 м3):
    норма фактически задана в литрах на человека в смену, хотя подписана «м3»."""
    m3 = Decimal(people) * Decimal(shifts) * norm_m3 / 1000
    return {"people": people, "shifts": shifts, "norm": norm_m3, "density": density,
            "m3": r3(m3), "t": r3(m3 * density)}


def by_norm(items: list[dict]) -> list[dict]:
    """Отходы эксплуатации по нормативу накопления: М = N·норма·ρ (табл. 9.3.2–9.3.8).

    Вход: [{"name": "Мусор от офисных помещений", "fkko": ..., "hazard": 4,
            "count": 58, "count_unit": "чел.", "norm_m3": 2.8?, "norm_t"?,
            "density": 0.2}]. Норматив — м3/год на единицу (сотрудник, место,
            м2 площади, машино-место) по региональным нормативам накопления."""
    out = []
    for i, it in enumerate(items, start=1):
        count = _d(it.get("count"))
        density = _d(it.get("density"))
        norm_m3, norm_t = _d(it.get("norm_m3")), _d(it.get("norm_t"))
        if norm_t:
            t = count * norm_t
            m3 = t / density if density else Decimal("0")
        else:
            m3 = count * norm_m3
            t = m3 * density
        fkko = str(it.get("fkko") or "")
        out.append({"n": i, "name": it.get("name") or "", "fkko": fkko,
                    "hazard": int(it.get("hazard") or (fkko[-1] if fkko and fkko[-1].isdigit() else 0)),
                    "count": count, "count_unit": it.get("count_unit") or "",
                    "norm": norm_t or norm_m3, "norm_unit": "т" if norm_t else "м3",
                    "density": density, "t": r3(t), "m3": r3(m3),
                    "note": "" if (count and (norm_m3 or norm_t)) else
                    f"[требуется: норматив накопления и количество для «{it.get('name')}»]"})
    return out


def lamps(fixtures: list[dict], hours_per_year: int = 4380) -> list[dict]:
    """Лампы: N_отх = N·T/K (табл. 9.3.1): число ламп × часы работы / ресурс."""
    out = []
    for i, f in enumerate(fixtures, start=1):
        n = _d(f.get("count")); k = _d(f.get("life_h")); t = _d(f.get("hours"), str(hours_per_year))
        mass_kg = _d(f.get("mass_kg")); density = _d(f.get("density"), "0.55")
        replaced = n * t / k if k else Decimal("0")
        tons = replaced * mass_kg / 1000
        out.append({"n": i, "name": f.get("name") or "", "count": n, "life_h": k,
                    "hours": t, "replaced": r3(replaced), "mass_kg": mass_kg,
                    "t": r3(tons), "m3": r3(tons / density) if density else Decimal("0"),
                    "density": density})
    return out
