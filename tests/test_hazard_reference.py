"""Тесты расчёта класса опасности и справочников."""
from ecodoc.development.hazard_class import Component, calculate
from ecodoc.core.refdata import substances, common_wastes


def test_hazard_class_boundaries():
    # K = 50000/100 + 950000/1e6 = 500 + 0.95 = 500.95 → IV класс
    r = calculate([Component("Нефтепродукты", 50000, 100),
                   Component("Песок", 950000, 1_000_000)])
    assert r.hazard_class == 4
    assert 500 < r.k_total < 502


def test_hazard_class_high():
    # очень опасный компонент → I/II класс
    r = calculate([Component("Ртуть", 1000, 1)])   # K = 1000 → III
    assert r.hazard_class == 3
    r2 = calculate([Component("Оч.опасное", 100000, 1)])  # K = 1e5 → II
    assert r2.hazard_class == 2


def test_hazard_zero_wi_skipped():
    r = calculate([Component("Инерт", 1_000_000, 0)])
    assert any("Wi" in w for w in r.warnings)
    assert r.hazard_class == 5


def test_reference_loaded():
    subs = substances()
    assert len(subs) >= 20
    no2 = next(s for s in subs if s["code"] == "0301")
    assert no2["pdk_mr"] == 0.2
    assert len(common_wastes()) >= 5
