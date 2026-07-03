"""Собственный расчёт рассеивания по МРР-2017 (приказ МПР № 273 от 06.06.2017).

Ответ на вопрос «можно ли исключить УПРЗА»: формулы МРР-2017 опубликованы,
их можно реализовать самим — этот модуль считает одиночный точечный источник
с круглым устьем: cм (максимальная приземная концентрация), xм (расстояние
до максимума), uм (опасная скорость ветра) и профиль концентрации по оси
факела c(x) = s1·cм. Этого достаточно для экспресс-оценок, проверки выгрузок
«Эколога» и простых объектов (котельная, дизель-генератор, окрасочный пост).

⚠ СТАТУС: экспериментальный. Для госэкспертизы и проектов НДВ/СЗЗ пока
используйте аттестованную УПРЗА («Эколог», «Призма») — эксперты требуют
программы, согласованные с ГГО им. Воейкова. Стратегия развития — в
docs/УПРЗА_анализ.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PointSource:
    """Точечный источник с круглым устьем (труба)."""
    name: str = "ИЗА"
    H: float = 10.0        # высота устья, м
    D: float = 0.5         # диаметр устья, м
    w0: float = 5.0        # скорость выхода ГВС, м/с
    Tg: float = 120.0      # температура ГВС, °C
    Tv: float = 25.2       # температура воздуха (тёплый период), °C
    M: float = 1.0         # выброс вещества, г/с
    F: float = 1.0         # коэф. оседания (газы=1, пыль=2..3)
    A: float = 160.0       # коэф. стратификации атмосферы (СЗФО/центр=160)
    eta: float = 1.0       # коэф. рельефа


@dataclass
class DispersionResult:
    cm: float              # максимальная приземная концентрация, мг/м³
    xm: float              # расстояние до максимума, м
    um: float              # опасная скорость ветра, м/с
    regime: str            # "нагретый" | "холодный"
    V1: float              # расход ГВС, м³/с


def _n_coef(v: float) -> float:
    if v >= 2:
        return 1.0
    if v >= 0.5:
        return 0.532 * v * v - 2.13 * v + 3.13
    return 4.4 * v


def calc_point(src: PointSource) -> DispersionResult:
    """cм/xм/uм по разд. 5 МРР-2017 (одиночный точечный источник)."""
    if src.H <= 0 or src.D <= 0 or src.w0 <= 0:
        raise ValueError(f"{src.name}: H, D и w0 должны быть > 0")
    V1 = math.pi * src.D ** 2 / 4 * src.w0
    dT = max(src.Tg - src.Tv, 0.0)
    H, D, w0 = src.H, src.D, src.w0

    f = 1000 * w0 ** 2 * D / (H ** 2 * dT) if dT > 0 else math.inf
    vm_hot = 0.65 * (V1 * dT / H) ** (1 / 3) if dT > 0 else 0.0
    vm_cold = 1.3 * w0 * D / H
    fe = 800 * vm_cold ** 3
    cold = (f >= 100 or dT <= 0.5)

    if not cold:
        # МРР-2017 п. 5.6: при fe < f < 100 коэффициент m вычисляется при f = fe
        f_eff = fe if fe < f else f
        m = 1 / (0.67 + 0.1 * math.sqrt(f_eff) + 0.34 * f_eff ** (1 / 3))
        v = vm_hot
        if v < 0.5:
            # МРР-2017 п. 5.7: предельно малые опасные скорости, m' = 2.86m
            cm = src.A * src.M * src.F * 2.86 * m * src.eta / H ** (7 / 3)
        else:
            n = _n_coef(v)
            cm = src.A * src.M * src.F * m * n * src.eta / \
                (H ** 2 * (V1 * dT) ** (1 / 3))
        d = (2.48 * (1 + 0.28 * fe ** (1 / 3)) if v <= 0.5 else
             4.95 * v * (1 + 0.28 * f ** (1 / 3)) if v <= 2 else
             7 * math.sqrt(v) * (1 + 0.28 * f ** (1 / 3)))
        um = (0.5 if v <= 0.5 else
              v if v <= 2 else v * (1 + 0.12 * math.sqrt(f)))
        regime = "нагретый"
    else:
        v = vm_cold
        if v < 0.5:
            # МРР-2017 п. 5.7: предельно малые опасные скорости, m' = 0.9
            cm = src.A * src.M * src.F * 0.9 * src.eta / H ** (7 / 3)
        else:
            K = D / (8 * V1)
            n = _n_coef(v)
            cm = src.A * src.M * src.F * n * src.eta * K / H ** (4 / 3)
        d = (5.7 if v <= 0.5 else 11.4 * v if v <= 2 else 16 * math.sqrt(v))
        um = (0.5 if v <= 0.5 else v if v <= 2 else 2.2 * v)
        regime = "холодный"

    xm = (5 - src.F) / 4 * d * H
    return DispersionResult(cm=cm, xm=xm, um=um, regime=regime, V1=V1)


def s1(ratio: float, F: float = 1.0, H: float = 10.0) -> float:
    """Безразмерный коэффициент s1(x/xм) — форма факела по оси (МРР-2017).

    Для низких источников (H < 10 м) при x/xм <= 1 применяется поправка
    s1н = 0.125·(10 − H) + 0.125·(H − 2)·s1 (при H < 2 м считаем как H = 2).
    """
    r = ratio
    if r <= 0:
        return 0.0
    if r <= 1:
        base = 3 * r ** 4 - 8 * r ** 3 + 6 * r ** 2
        if H < 10:
            Hc = max(H, 2.0)
            return 0.125 * (10 - Hc) + 0.125 * (Hc - 2) * base
        return base
    if r <= 8:
        return 1.13 / (0.13 * r * r + 1)
    if F <= 1.5:
        return r / (3.58 * r * r - 35.2 * r + 120)
    return 1 / (0.1 * r * r + 2.47 * r - 17.8)


def axis_profile(src: PointSource, distances: list[float] | None = None
                 ) -> list[tuple[float, float]]:
    """[(x, c(x)), ...] по оси факела при опасной скорости ветра."""
    res = calc_point(src)
    if distances is None:
        xm = max(res.xm, 1.0)
        distances = sorted({round(xm * k) for k in
                            (0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 8, 12, 20)})
    return [(x, s1(x / res.xm, src.F, src.H) * res.cm) for x in distances]


def report(sources: list[PointSource],
           pdk: dict[str, float] | None = None) -> str:
    """Текстовый отчёт по списку источников (сравнение с ПДКм.р., если дано)."""
    lines = ["── Экспресс-расчёт рассеивания (МРР-2017, точечные источники) ──",
             "⚠ Экспериментальный модуль: для экспертизы используйте аттестованную УПРЗА.",
             ""]
    for s in sources:
        try:
            r = calc_point(s)
        except ValueError as e:
            lines.append(f"{s.name}: ✖ {e}")
            continue
        lines.append(f"{s.name}: H={s.H} м, D={s.D} м, w0={s.w0} м/с, "
                     f"M={s.M} г/с ({r.regime}, V1={r.V1:.2f} м³/с)")
        lines.append(f"   cм = {r.cm:.4g} мг/м³   xм = {r.xm:.0f} м   "
                     f"uм = {r.um:.2f} м/с")
        if pdk and s.name in pdk and pdk[s.name] > 0:
            share = r.cm / pdk[s.name]
            mark = "✓" if share <= 1 else "✖ ПРЕВЫШЕНИЕ"
            lines.append(f"   доля ПДКм.р.: {share:.2f} {mark}")
        for x, c in axis_profile(s):
            lines.append(f"      x={x:>6.0f} м  c={c:.4g} мг/м³")
    return "\n".join(lines)
