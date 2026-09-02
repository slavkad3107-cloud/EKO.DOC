"""Замечания пользователя по вкладкам ОРГАНИЗАЦИЯ/ОБЪЕКТ/ОТХОДЫ (02.09.2026):
краткое наименование, строгие коды объектов, период акта (год/квартал/месяц),
мусорные лицензии, происхождение паспортов, разбивка т и м³, подсказки ФККО."""
from decimal import Decimal

from ecodoc.core import sanitize, sanitize_records as recs, waste_periods, fkko
from ecodoc.core.models import NVOSObject, ReportContext, WasteAct, WasteFlow
from ecodoc.core.waste_agg import act_period, parse_period, period_label


# ── краткое наименование ────────────────────────────────────────────────
def test_short_name_for_ip_and_ooo():
    assert recs.suggest_short_name("МИНИХ ЕЛЕНА АНАТОЛЬЕВНА", "780600114472") == "ИП Миних Е.А."
    assert recs.suggest_short_name('ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ТЕХНОСТРОЙ"',
                                   "7806001144") == "ООО «Технострой»"
    assert recs.suggest_short_name("Индивидуальный предприниматель Иванов Пётр Сергеевич") \
        == "ИП Иванов П.С."


def test_short_name_problems():
    full = "МИНИХ ЕЛЕНА АНАТОЛЬЕВНА"
    assert "совпадает с полным" in recs.short_name_problem(full, full, "780600114472")
    assert "не похоже" in recs.short_name_problem(full, 'ООО "ЛЕЛЬ-ЭКО"', "780600114472")
    assert recs.short_name_problem(full, "ИП Миних Е.А.", "780600114472") == ""
    assert recs.short_name_problem(full, "", "") == "краткое наименование не заполнено"


# ── объекты ──────────────────────────────────────────────────────────────
def test_only_nvos_codes_are_objects():
    assert recs.object_problem("41-0247-005048-П") == ""
    assert recs.object_problem("41-0247-005048-P") == ""          # латинская P
    assert recs.object_problem("78:34:0004281:3000")               # кадастровый
    assert recs.object_problem("СЭ-01-23-597")                     # шифр проекта
    ctx = ReportContext()
    ctx.objects = [NVOSObject(code="41-0247-005048-П"), NVOSObject(code="78:34:0004281:3000"),
                   NVOSObject(code="XX-XXXX-XXXXXX-П")]
    removed = recs.clean_objects(ctx)
    assert [o.code for o in ctx.objects] == ["41-0247-005048-П"] and len(removed) == 2


# ── период акта ─────────────────────────────────────────────────────────
def test_parse_period_all_forms():
    assert parse_period("15.03.2025") == (2025, 1, 3)
    assert parse_period("2025-11-02") == (2025, 4, 11)
    assert parse_period("3 кв 25") == (2025, 3, 0)
    assert parse_period("III квартал 2024") == (2024, 3, 0)
    assert parse_period("март 2025") == (2025, 1, 3)
    assert parse_period("03.2025") == (2025, 1, 3)
    assert parse_period("2025") == (2025, 0, 0)
    assert parse_period("") == (0, 0, 0)


def test_act_period_prefers_explicit_fields_and_labels():
    a = WasteAct(date="3 кв 2024")
    assert act_period(a) == (2024, 3, 0) and period_label(a) == "3 кв 2024"
    b = WasteAct(date="", year=2025, month=7)
    assert act_period(b) == (2025, 3, 7) and period_label(b) == "июль 2025"
    c = WasteAct(date="01.02.2025")
    assert period_label(c) == "01.02.2025"
    assert period_label(WasteAct()) == "без периода"


# ── лицензии ────────────────────────────────────────────────────────────
def test_license_problems():
    assert recs.license_problem("Л020-00113-47/00095706 от 25.03.2021") == ""
    assert recs.license_problem("(78)-1234-СТОУ") == ""
    assert "просто число" in recs.license_problem("181.0")
    assert "не похоже" in recs.license_problem("Прогресс")
    ctx = ReportContext()
    ctx.waste_acts = [WasteAct(fkko_code="73310001724", mass=Decimal("1"),
                               license="181.0", carrier="Прогресс", carrier_license="Прогресс"),
                      WasteAct(fkko_code="73310001724", mass=Decimal("1"),
                               license="Л020-00113-47/00095706")]
    fixed = recs.clean_act_licenses(ctx)
    assert len(fixed) == 2
    assert ctx.waste_acts[0].license == "" and ctx.waste_acts[0].carrier_license == ""
    assert ctx.waste_acts[1].license.startswith("Л020")


# ── паспорта ────────────────────────────────────────────────────────────
def test_passport_sources():
    assert recs.passport_source_ok("1 П.о.о. осадки мойка__Паркинг.pdf")
    assert recs.passport_source_ok("прот._бетон_5 кл.pdf")
    assert recs.passport_source_ok("Раздел ПД №8 ООС1.pdf")
    assert recs.passport_source_ok("006_1.jpg")                     # скан — допускаем
    assert not recs.passport_source_ok("Миних_расчет 1 кв 26.xls")
    assert not recs.passport_source_ok("аппеляционная жалоба.pdf (листы 6–11)")
    assert not recs.passport_source_ok("_Отчет 1028.pdf")


def test_passports_check_and_clean():
    ctx = ReportContext()
    ctx.waste_acts = [WasteAct(fkko_code="73310001724", mass=Decimal("1"))]
    ctx.extra["waste_passports"] = [
        {"fkko": "73310001724", "name": "Мусор от офисных и бытовых помещений организаций несортированный",
         "hazard_class": 4, "components": [{"name": "бумага", "percent": "60"}],
         "_src": "П.о.о ТБО.pdf"},
        {"fkko": "73310001724", "name": "мусор офисный", "hazard_class": 4,
         "components": [], "_src": "Миних_расчет 1 кв 26.xls"},
        {"fkko": "40414000115", "name": "тара деревянная", "hazard_class": 5,
         "components": [], "_src": "аппеляционная жалоба.pdf"},
    ]
    rows = recs.check_passports(ctx)
    assert rows[0]["src_ok"] and rows[0]["in_acts"] and rows[0]["in_catalog"]
    assert not rows[1]["src_ok"] and any("дубль" in p for p in rows[1]["problems"])
    assert not rows[2]["in_catalog"]
    removed = recs.clean_passports(ctx)
    assert len(ctx.extra["waste_passports"]) == 1 and len(removed) == 2


# ── разбивка по периодам т и м³ ─────────────────────────────────────────
def test_waste_periods_t_and_m3():
    ctx = ReportContext()
    ctx.waste_acts = [
        WasteAct(fkko_code="73310001724", name="Мусор офисный", hazard_class=4,
                 mass=Decimal("1.9"), volume_m3=Decimal("12.5"), date="15.03.2025"),
        WasteAct(fkko_code="73310001724", name="Мусор офисный", hazard_class=4,
                 mass=Decimal("2.1"), density=Decimal("0.2"), date="3 кв 2025"),
        WasteAct(fkko_code="82220101215", name="Лом бетона", hazard_class=5,
                 mass=Decimal("10"), date=""),
    ]
    out = waste_periods.build(ctx)
    assert out["years"] == [2025]
    row = next(r for r in out["rows"] if r["fkko"] == "73310001724")
    p = row["periods"]["2025"]
    assert p["t"] == 4.0 and p["m3"] == 23.0                # 12.5 + 2.1/0.2
    assert p["q"]["1"]["t"] == 1.9 and p["q"]["3"]["t"] == 2.1
    assert p["m"]["3"]["m3"] == 12.5 and "9" not in p["m"]   # квартал без месяца
    assert row["fkko_fmt"] == "7 33 100 01 72 4"
    assert out["no_period"] == {"t": 10.0, "m3": 0.0, "count": 1}
    assert out["totals"]["2025"]["t"] == 4.0


# ── подсказки ФККО ───────────────────────────────────────────────────────
def test_fkko_check_suggests_real_code():
    ctx = ReportContext()
    ctx.wastes = [WasteFlow(fkko_code="40414000115",
                            name="тара деревянная, утратившая потребительские свойства",
                            hazard_class=5)]
    rows = fkko.check_context(ctx)
    assert not rows[0]["ok"]
    assert rows[0]["suggest"] and rows[0]["suggest"][0]["code"] == "40414000515"
    assert rows[0]["suggest"][0]["code_fmt"] == "4 04 140 00 51 5"


def test_clean_context_covers_records():
    ctx = ReportContext()
    ctx.objects = [NVOSObject(code="78:34:0004281:3000")]
    ctx.waste_acts = [WasteAct(fkko_code="73310001724", mass=Decimal("1"), license="51.0")]
    ctx.extra["waste_passports"] = [{"fkko": "73310001724", "name": "x", "components": [],
                                     "_src": "деклараци.html"}]
    rep = sanitize.clean_context(ctx)
    assert rep["removed_objects"] and rep["fixed_licenses"] and rep["removed_passports"]
    assert not ctx.objects and ctx.waste_acts[0].license == ""
