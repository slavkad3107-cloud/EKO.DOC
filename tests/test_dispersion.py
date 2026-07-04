"""Проверки расчёта рассеивания и суммации источников."""
from ecodoc.development.dispersion import PointSource, calc_point
from ecodoc.development.dispersion_map import (MapSource, compute_grid,
                                               render_svg)
from ecodoc.development import dispersion_export as ex


def test_point_hot_source():
    r = calc_point(PointSource(H=18, D=0.6, w0=8.5, Tg=140, Tv=25.2, M=0.35))
    assert r.regime == "нагретый"
    assert 0 < r.cm < 1
    assert r.xm > 0 and r.um > 0


def test_invalid_source_raises():
    import pytest
    with pytest.raises(ValueError):
        calc_point(PointSource(H=0))


def test_grid_sum_and_pdk():
    srcs = [MapSource(name="A", x=0, y=0, H=18, D=0.6, w0=8.5, Tg=140,
                      M=0.35, substance="NO2", pdk=0.2),
            MapSource(name="B", x=100, y=0, H=6, D=0.2, w0=18, Tg=400,
                      M=0.5, substance="NO2", pdk=0.2)]
    g = compute_grid(srcs, n=25, dirs=12)
    assert g.cmax > 0
    assert g.share_max == g.cmax / 0.2
    # карта строится и содержит оба источника
    svg = render_svg(g)
    assert svg.startswith("<svg") and svg.count("<circle") == 2


def test_upraza_export(tmp_path):
    srcs = [MapSource(name="A", H=18, D=0.6, w0=8.5, M=0.35,
                      substance="NO2", code="0301")]
    xl = ex.to_excel(srcs, tmp_path / "u.xlsx")
    js = ex.to_json(srcs, tmp_path / "u.json")
    assert xl.exists() and js.exists()
    import json
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["sources"][0]["substance"] == "NO2"
    assert data["sources"][0]["V1"] > 0
