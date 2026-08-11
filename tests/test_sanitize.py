"""Санитар входных данных: что не пускаем в базу и как чистим накопленное.

Случаи взяты с реальных объектов пользователя — там мусор и обнаружился.
"""
from decimal import Decimal

import pytest

from ecodoc.core import sanitize
from ecodoc.core.models import (Medium, Pollutant, ReportContext, WasteAct,
                                WasteFlow)


# ── коды веществ ────────────────────────────────────────────────────────
def test_code_normalized_to_four_digits():
    assert sanitize.norm_code("301") == "0301"
    assert sanitize.norm_code("0301") == "0301"
    assert sanitize.norm_code(" 2908 ") == "2908"
    assert sanitize.norm_code("01.01.00.11.01") == ""   # классификатор вод
    assert sanitize.norm_code("абв") == "" and sanitize.norm_code("") == ""
    assert sanitize.norm_code("12345") == ""            # длиннее кода вещества


def test_same_substance_under_two_code_forms():
    a = sanitize.check_substance("301", "Азота диоксид")
    b = sanitize.check_substance("0301", "Азота диоксид (Двуокись азота)")
    assert a.ok and b.ok and a.code == b.code == "0301"


def test_name_normalized_for_dedup():
    assert (sanitize.norm_name("Бытовая канализация")
            == sanitize.norm_name("бытовая  канализация"))
    assert (sanitize.norm_name("Азота диоксид (Двуокись азота)")
            == sanitize.norm_name("азота диоксид"))


# ── что веществом не является ───────────────────────────────────────────
@pytest.mark.parametrize("code,name", [
    ("6501", "работа строительной техники"),
    ("6503", "движение строительной техники"),
    ("6504", "сварочные работы"),
    ("6506", "укладка асфальта"),
    ("", "вредные вещества, выделяющиеся при хранении автомобилей"),
])
def test_operations_are_not_substances(code, name):
    v = sanitize.check_substance(code, name)
    assert not v.ok and "не вещество" in v.reason


@pytest.mark.parametrize("name", [
    "Бытовые сточные воды", "Поверхностные стоки", "ливневые стоки",
    "бытовая канализация", "хоз.-бытовые сточные воды",
])
def test_water_flows_are_not_substances(name):
    v = sanitize.check_substance("", name, "water")
    assert not v.ok and "вид сточных вод" in v.reason


def test_sum_groups_rejected():
    v = sanitize.check_substance("6204", "Азота диоксид, серы диоксид")
    assert not v.ok and "группа суммации" in v.reason
    assert sanitize.is_sum_group("6053") and not sanitize.is_sum_group("0301")


def test_air_code_in_water_is_suspect_not_silent():
    """Код атмосферного перечня у сброса — принимаем, но показываем."""
    v = sanitize.check_substance("0101", "Аммоний", "water")
    assert v.ok and v.suspect and "АТМОСФЕРНОГО" in v.reason


def test_good_substance_passes():
    v = sanitize.check_substance("0337", "Углерода оксид")
    assert v.ok and not v.suspect and v.code == "0337"


# ── ПДК вместо массы ────────────────────────────────────────────────────
def test_pdk_in_mass_column_detected():
    # 0337 углерода оксид: ПДК с.с. = 3.0 — масса «3 т/год» подозрительна
    note = sanitize.pdk_conflict("0337", 3.0)
    assert "ПДК" in note
    assert not sanitize.pdk_conflict("0337", 1.4542)     # реальная масса
    assert not sanitize.pdk_conflict("", 3.0)


# ── отходы ──────────────────────────────────────────────────────────────
def test_waste_code_checked_against_catalog(monkeypatch, tmp_path):
    from ecodoc.core import fkko
    monkeypatch.setenv("ECODOC_FKKO", str(tmp_path / "fkko.json"))
    monkeypatch.setattr(fkko, "BUILTIN_FILE", tmp_path / "нет.json")
    fkko._CACHE.clear()
    fkko.save({"73310001724": {"name": "Мусор от офисных помещений", "class": 4}},
              source="тест", partial=False)

    ok = sanitize.check_waste("7 33 100 01 72 4", "Мусор от офисных помещений")
    assert ok.ok and ok.code == "73310001724"

    bad = sanitize.check_waste("78117517161", "отходы 5 класса опасности")
    assert not bad.ok and "нет в каталоге" in bad.reason

    group = sanitize.check_waste("73120000000", "лом чёрных металлов")
    assert not group.ok                       # групповой код — не позиция
    fkko._CACHE.clear()


# ── чистка накопленной базы ─────────────────────────────────────────────
@pytest.fixture()
def dirty_ctx(monkeypatch, tmp_path):
    from ecodoc.core import fkko
    monkeypatch.setenv("ECODOC_FKKO", str(tmp_path / "fkko.json"))
    monkeypatch.setattr(fkko, "BUILTIN_FILE", tmp_path / "нет.json")
    fkko._CACHE.clear()
    fkko.save({"73310001724": {"name": "Мусор от офисных помещений", "class": 4},
               "81110001495": {"name": "Грунт при землеройных работах", "class": 5}},
              source="тест", partial=False)
    c = ReportContext()
    air = lambda **kw: Pollutant(medium=Medium.AIR, **kw)          # noqa: E731
    water = lambda **kw: Pollutant(medium=Medium.WATER, **kw)      # noqa: E731
    c.pollutants = [
        air(code="301", name="Азота диоксид", mass_norm=Decimal("1.495")),
        air(code="0301", name="Азота диоксид (Двуокись азота)"),   # дубль
        air(code="6501", name="работа строительной техники"),      # мусор
        air(code="6204", name="Азота диоксид, серы диоксид"),      # суммация
        water(code="", name="Поверхностные стоки"),                # не вещество
        water(code="", name="поверхностные стоки"),                # он же
    ]
    c.wastes = [
        WasteFlow(fkko_code="73310001724", name="Мусор офисный",
                  hazard_class=4, generated=Decimal("6.4")),
        WasteFlow(fkko_code="78117517161", name="отходы 5 класса"),   # выдуман
        WasteFlow(fkko_code="86201001524", name="Газон обыкновенный"),  # смета
    ]
    c.waste_acts = [
        WasteAct(fkko_code="73310001724", name="Мусор офисный",
                 mass=Decimal("3.2"), operation="размещение", date="01.03.2025"),
        WasteAct(fkko_code="86201001524", name="Газон обыкновенный",
                 mass=Decimal("0.004"), operation="размещение", date="02.03.2025"),
    ]
    yield c
    fkko._CACHE.clear()


def test_audit_counts_trash_without_changing(dirty_ctx):
    a = sanitize.audit_context(dirty_ctx)
    t = a["totals"]
    assert t["pollutants_bad"] == 4 and t["wastes_bad"] == 2
    assert t["acts_bad"] == 1 and t["duplicates"] == 2
    assert len(dirty_ctx.pollutants) == 6 and len(dirty_ctx.wastes) == 3


def test_clean_removes_trash_and_keeps_data(dirty_ctx):
    rep = sanitize.clean_context(dirty_ctx)
    codes = [p.code for p in dirty_ctx.pollutants]
    assert codes == ["0301"]                    # дубль склеен, код нормализован
    assert dirty_ctx.pollutants[0].mass_norm == Decimal("1.495")  # масса цела
    assert [w.fkko_code for w in dirty_ctx.wastes] == ["73310001724"]
    assert [a.fkko_code for a in dirty_ctx.waste_acts] == ["73310001724"]
    assert any("работа" in r["reason"] for r in rep["removed_pollutants"])
    assert rep["removed_acts"] and "Газон" in rep["removed_acts"][0]["label"]


def test_clean_recalculates_movement_from_acts(dirty_ctx):
    """Мусор из актов не должен вернуться в движение при следующей загрузке."""
    sanitize.clean_context(dirty_ctx)
    assert not any(w.fkko_code == "86201001524" for w in dirty_ctx.wastes)
    left = next(w for w in dirty_ctx.wastes if w.fkko_code == "73310001724")
    assert left.generated == Decimal("3.2")     # пересчитано по актам


def test_clean_can_keep_everything(dirty_ctx):
    sanitize.clean_context(dirty_ctx, drop_bad=False, drop_dupes=False)
    assert len(dirty_ctx.pollutants) == 6       # ничего не удалено
    assert dirty_ctx.pollutants[0].code == "0301"   # но код нормализован


def test_api_audit_and_clean_makes_backup(dirty_ctx, tmp_path, monkeypatch):
    from ecodoc.core import serialize, workspace
    from ecodoc.gui import server
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    workspace.add_org("ОРГ")
    workspace.add_site("ОРГ", "Пл")
    serialize.to_json(dirty_ctx, workspace.site_dir("ОРГ", "Пл") / "context.json")

    # при загрузке движение пересчитывается по актам, пустые позиции
    # отбрасываются — но мусорный код из акта остаётся и должен быть виден
    before = server.api_audit_data({"org": "ОРГ", "site": "Пл"}, {})
    assert before["totals"]["wastes_bad"] >= 1
    assert before["totals"]["acts_bad"] == 1

    rep = server.api_clean_data({}, {"org": "ОРГ", "site": "Пл"})
    assert rep["backup"] and "до-очистки" in rep["backup"]
    after = server.api_audit_data({"org": "ОРГ", "site": "Пл"}, {})
    assert after["totals"]["wastes_bad"] == 0
    assert after["totals"]["pollutants_bad"] == 0
