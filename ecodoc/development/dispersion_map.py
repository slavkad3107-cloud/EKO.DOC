"""Суммация вкладов источников и карта рассеивания по МРР-2017.

Расширяет одиночный расчёт (dispersion.calc_point) до расчёта на местности:
несколько источников с координатами, перебор направлений и скоростей ветра,
максимальная приземная концентрация в каждой точке сетки, доля ПДК и
векторная карта изолиний (SVG, без внешних зависимостей).

Формулы: приземная концентрация в точке (x — по оси факела от источника,
y — поперёк) c = c_mu · s1(x/x_mu) · s2(y), где c_mu = r(u/uм)·cм —
максимум при скорости u, x_mu = p(u/uм)·xм — его положение (МРР-2017,
разд. 5.3–5.5; поперечное s2 — ф. поперечного распределения).

⚠ Экспериментально. Для госэкспертизы нужна аттестованная УПРЗА; этот
модуль — для экспресс-оценки, проверки и выгрузки исходных данных в УПРЗА.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ecodoc.development.dispersion import DispersionResult, calc_point, s1


@dataclass
class MapSource:
    """Источник на местности: параметры трубы + координаты + вещество."""
    name: str = "ИЗА"
    x: float = 0.0             # координаты устья на площадке, м
    y: float = 0.0
    H: float = 10.0
    D: float = 0.5
    w0: float = 5.0
    Tg: float = 120.0
    Tv: float = 25.2
    M: float = 1.0             # выброс, г/с
    F: float = 1.0
    A: float = 160.0
    eta: float = 1.0
    substance: str = ""        # имя вещества (для группировки/суммации)
    code: str = ""             # код вещества
    pdk: float = 0.0           # ПДКм.р., мг/м³
    bg: float = 0.0            # фоновая концентрация, мг/м³


def _as_point(s: MapSource):
    from ecodoc.development.dispersion import PointSource
    return PointSource(name=s.name, H=s.H, D=s.D, w0=s.w0, Tg=s.Tg, Tv=s.Tv,
                       M=s.M, F=s.F, A=s.A, eta=s.eta)


def _r_speed(ratio: float) -> float:
    """Коэффициент r(u/uм) — доля cм при скорости, отличной от опасной."""
    if ratio <= 1:
        return 0.67 * ratio + 1.8 * ratio ** 2 - 1.17 * ratio ** 3
    return 3 * ratio / (2 * ratio ** 2 - ratio + 2)


def _p_speed(ratio: float) -> float:
    """Коэффициент p(u/uм) — сдвиг положения максимума при скорости u."""
    if ratio <= 0.25:
        return 3.0
    if ratio <= 1:
        return 8.43 * (1 - ratio) ** 3 + 1
    return 0.32 * ratio + 0.68


def _s2(u: float, along: float, cross: float) -> float:
    """Поперечное распределение s2(y) на расстоянии along по оси факела."""
    if along <= 0:
        return 0.0
    ty = (u if u <= 5 else 5) * cross ** 2 / along ** 2
    return 1.0 / (1 + 5 * ty + 12.8 * ty ** 2 + 17 * ty ** 3 + 45.1 * ty ** 4)


def contribution(src: MapSource, res: DispersionResult,
                 xr: float, yr: float, wind_to_deg: float, u: float) -> float:
    """Вклад источника в приземную концентрацию в точке (xr, yr), мг/м³.

    wind_to_deg — направление, КУДА дует ветер (куда вытянут факел).
    """
    dx, dy = xr - src.x, yr - src.y
    a = math.radians(wind_to_deg)
    ux, uy = math.cos(a), math.sin(a)
    along = dx * ux + dy * uy        # вдоль факела (по ветру)
    cross = -dx * uy + dy * ux       # поперёк
    if along <= 0:
        return 0.0
    ratio = u / res.um if res.um > 0 else 1.0
    x_mu = _p_speed(ratio) * res.xm
    if x_mu <= 0:
        return 0.0
    c_mu = _r_speed(ratio) * res.cm
    return c_mu * s1(along / x_mu, src.F, src.H) * _s2(u, along, cross)


@dataclass
class GridResult:
    xs: list[float]                 # координаты узлов сетки по X, м
    ys: list[float]
    conc: list[list[float]]         # макс. концентрация (с фоном), мг/м³
    share: list[list[float]]        # доля ПДК
    cmax: float                     # глобальный максимум концентрации
    share_max: float                # глобальная макс. доля ПДК
    substance: str
    pdk: float
    bg: float
    sources: list[MapSource] = field(default_factory=list)


def _speeds(um: float) -> list[float]:
    """Набор скоростей ветра для перебора (включая опасную и близкие к ней)."""
    base = {0.5, 1.0, um * 0.5, um * 0.75, um, um * 1.25, um * 1.5, 5.0}
    return sorted(s for s in base if s >= 0.5)


def compute_grid(sources: list[MapSource], substance: str | None = None,
                 n: int = 60, dirs: int = 24, margin: float = 2.0
                 ) -> GridResult:
    """Максимальная приземная концентрация по сетке (перебор ветра).

    substance — считать только по этому веществу (иначе — по первому
    встреченному). n×n узлов, dirs направлений ветра.
    """
    if substance is None:
        substance = next((s.substance for s in sources if s.substance), "")
    grp = [s for s in sources if (s.substance or "") == (substance or "")] \
        or list(sources)
    if not grp:
        raise ValueError("Нет источников для карты.")

    res = {id(s): calc_point(_as_point(s)) for s in grp}
    xm_max = max(res[id(s)].xm for s in grp) or 100.0
    # границы: охватить источники + несколько xм вокруг
    xs0 = [s.x for s in grp]
    ys0 = [s.y for s in grp]
    pad = margin * xm_max
    x0, x1 = min(xs0) - pad, max(xs0) + pad
    y0, y1 = min(ys0) - pad, max(ys0) + pad
    # квадратная сетка
    span = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    x0, x1 = cx - span / 2, cx + span / 2
    y0, y1 = cy - span / 2, cy + span / 2
    xs = [x0 + (x1 - x0) * i / (n - 1) for i in range(n)]
    ys = [y0 + (y1 - y0) * j / (n - 1) for j in range(n)]

    wind_dirs = [360 * k / dirs for k in range(dirs)]
    speed_sets = {id(s): _speeds(res[id(s)].um) for s in grp}
    all_speeds = sorted(set().union(*speed_sets.values()))

    pdk = next((s.pdk for s in grp if s.pdk), 0.0)
    bg = next((s.bg for s in grp if s.bg), 0.0)

    conc = [[0.0] * n for _ in range(n)]
    for j, yr in enumerate(ys):
        for i, xr in enumerate(xs):
            best = 0.0
            for wd in wind_dirs:
                for u in all_speeds:
                    total = 0.0
                    for s in grp:
                        total += contribution(s, res[id(s)], xr, yr, wd, u)
                    if total > best:
                        best = total
            conc[j][i] = best + bg
    cmax = max(max(row) for row in conc)
    if pdk > 0:
        share = [[c / pdk for c in row] for row in conc]
        share_max = cmax / pdk
    else:
        share = [[0.0] * n for _ in range(n)]
        share_max = 0.0
    return GridResult(xs, ys, conc, share, cmax, share_max,
                      substance or "вещество", pdk, bg, grp)


# ── векторная карта (SVG) ────────────────────────────────────────────────

def _color(share: float) -> str:
    """Цвет ячейки по доле ПДК (зелёный→жёлтый→красный)."""
    t = max(0.0, min(share, 1.5)) / 1.5
    if t < 0.5:
        r, g = int(510 * t), 200
    else:
        r, g = 255, int(200 - 300 * (t - 0.5))
    return f"rgb({max(0,min(r,255))},{max(0,min(g,255))},60)"


def render_svg(grid: GridResult, width: int = 640) -> str:
    """Карта рассеивания в SVG: цветовое поле долей ПДК + источники + шкала."""
    n = len(grid.xs)
    x0, x1 = grid.xs[0], grid.xs[-1]
    y0, y1 = grid.ys[0], grid.ys[-1]
    plot = width - 90            # поле под карту (справа — легенда)
    sx = plot / (x1 - x0 or 1)
    sy = plot / (y1 - y0 or 1)
    scale = min(sx, sy)
    H = plot + 60

    def px(x):
        return 10 + (x - x0) * scale

    def py(y):
        return 10 + (y1 - y) * scale     # ось Y вверх

    use_share = grid.pdk > 0
    field_vals = grid.share if use_share else grid.conc
    vmax = grid.share_max if use_share else (grid.cmax or 1)

    cw = (x1 - x0) / (n - 1) * scale
    ch = (y1 - y0) / (n - 1) * scale
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{H}" font-family="Segoe UI,sans-serif" font-size="11">']
    parts.append(f'<rect width="{width}" height="{H}" fill="#fff"/>')

    # цветовое поле
    for j in range(n):
        for i in range(n):
            v = field_vals[j][i]
            if v <= 0.02:
                continue
            share = v if use_share else v / vmax * 1.0
            parts.append(
                f'<rect x="{px(grid.xs[i])-cw/2:.1f}" y="{py(grid.ys[j])-ch/2:.1f}" '
                f'width="{cw+0.6:.1f}" height="{ch+0.6:.1f}" '
                f'fill="{_color(share)}" opacity="0.75"/>')

    # изолиния ПДК = 1 (граница превышения) — по узлам, простая обводка ячеек
    if use_share:
        for j in range(n):
            for i in range(n):
                if grid.share[j][i] >= 1.0:
                    parts.append(
                        f'<rect x="{px(grid.xs[i])-cw/2:.1f}" '
                        f'y="{py(grid.ys[j])-ch/2:.1f}" width="{cw:.1f}" '
                        f'height="{ch:.1f}" fill="none" stroke="#7a0010" '
                        f'stroke-width="0.4"/>')

    # источники
    for s in grid.sources:
        parts.append(
            f'<circle cx="{px(s.x):.1f}" cy="{py(s.y):.1f}" r="4" '
            f'fill="#123" stroke="#fff" stroke-width="1"/>')
        parts.append(
            f'<text x="{px(s.x)+6:.1f}" y="{py(s.y)-6:.1f}" fill="#123">'
            f'{_esc(s.name)}</text>')

    # рамка и подписи осей
    parts.append(f'<rect x="10" y="10" width="{plot:.0f}" height="{plot:.0f}" '
                 f'fill="none" stroke="#999"/>')
    parts.append(f'<text x="{10+plot/2:.0f}" y="{plot+34:.0f}" '
                 f'text-anchor="middle" fill="#555">X, м · масштаб сетки</text>')

    # легенда-шкала справа
    lx = plot + 24
    parts.append(f'<text x="{lx}" y="24" fill="#333">'
                 f'{"доля ПДК" if use_share else "мг/м³"}</text>')
    for k in range(11):
        t = k / 10 * (1.5 if use_share else 1.0)
        yy = 34 + k * 16
        parts.append(f'<rect x="{lx}" y="{yy}" width="14" height="14" '
                     f'fill="{_color(t if use_share else t)}"/>')
        label = f"{t:.2f}" if use_share else f"{t*vmax:.3g}"
        parts.append(f'<text x="{lx+18}" y="{yy+11}" fill="#333">{label}</text>')

    parts.append(f'<text x="10" y="{H-6}" fill="#7a0010">'
                 f'Максимум: {grid.share_max:.2f} ПДК'
                 f'{"  ✖ ПРЕВЫШЕНИЕ" if grid.share_max>1 else ""}  '
                 f'({grid.cmax:.4g} мг/м³, {_esc(grid.substance)})</text>')
    parts.append('</svg>')
    return "\n".join(parts)


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def summary(grid: GridResult) -> str:
    lines = [f"── Карта рассеивания: {grid.substance} ──",
             f"Источников: {len(grid.sources)}   сетка {len(grid.xs)}×{len(grid.ys)}",
             f"Максимум приземной концентрации: {grid.cmax:.4g} мг/м³"]
    if grid.pdk > 0:
        m = "✖ ПРЕВЫШЕНИЕ ПДК" if grid.share_max > 1 else "✓ в пределах ПДК"
        lines.append(f"ПДКм.р. = {grid.pdk} мг/м³   макс. доля = "
                     f"{grid.share_max:.2f} {m}")
    if grid.bg:
        lines.append(f"Учтён фон: {grid.bg} мг/м³")
    lines.append("⚠ Экспресс-оценка; для экспертизы — аттестованная УПРЗА.")
    return "\n".join(lines)
