"""Площадные и линейные источники рассеивания (разложение в точечные)."""
from ecodoc.development.dispersion_map import MapSource, compute_grid, expand_source


def test_area_expands_to_grid():
    a = MapSource(name="Склад", kind="area", x=0, y=0, x2=100, y2=80,
                  H=3, D=1, w0=1, Tg=25.1, M=0.32, substance="пыль", pdk=0.3)
    pts = expand_source(a)
    assert len(pts) == 16
    # выброс делится поровну и суммируется в исходный
    assert abs(sum(p.M for p in pts) - 0.32) < 1e-9


def test_line_expands():
    ln = MapSource(name="Дорога", kind="line", x=0, y=0, x2=300, y2=0,
                   H=2, D=1, w0=1, Tg=25.1, M=0.18, substance="NO2", pdk=0.2)
    pts = expand_source(ln)
    assert len(pts) == 6
    assert abs(sum(p.M for p in pts) - 0.18) < 1e-9
    # точки лежат на линии y=0
    assert all(abs(p.y) < 1e-9 for p in pts)


def test_point_unchanged():
    p = MapSource(name="Труба", kind="point", x=5, y=5, M=0.1)
    assert expand_source(p) == [p]


def test_grid_keeps_original_markers():
    srcs = [MapSource(name="Труба", x=0, y=0, H=18, D=0.6, w0=8.5, Tg=140,
                      M=0.35, substance="NO2", pdk=0.2),
            MapSource(name="Склад", kind="area", x=50, y=50, x2=150, y2=120,
                      H=3, D=1, w0=1, Tg=25.1, M=0.2, substance="NO2", pdk=0.2)]
    g = compute_grid(srcs, n=25, dirs=8)
    # на карте — 2 маркера (оригиналы), не 17 подточек
    assert len(g.sources) == 2
    assert g.cmax > 0
