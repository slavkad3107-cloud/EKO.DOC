"""Прозрачность приёма (intake/insight): что откуда взято, проверка данных
по категориям с файлом/листом/подсказкой, чего не хватает формам."""
from decimal import Decimal

from ecodoc.core import workspace
from ecodoc.core.models import NVOSObject, WasteAct, WasteFlow
from ecodoc.gui import server
from ecodoc.intake import insight


def _site():
    workspace.add_org("ОРГ")
    workspace.add_site("ОРГ", "Пл")
    ctx = workspace.load_context("ОРГ", "Пл")
    ctx.organization.name = "МИНИХ ЕЛЕНА АНАТОЛЬЕВНА"
    ctx.organization.short_name = "МИНИХ ЕЛЕНА АНАТОЛЬЕВНА"     # = полному
    ctx.organization.inn = "780600114472"
    ctx.objects = [NVOSObject(code="41-0247-005048-П", category="IV")]
    ctx.waste_acts = [
        WasteAct(fkko_code="73310001724", name="Мусор офисный", hazard_class=4,
                 mass=Decimal("1.9"), date=""),                       # без периода
        WasteAct(fkko_code="73310001724", name="Мусор офисный", hazard_class=4,
                 mass=Decimal("0.002"), volume_m3=Decimal("2"),
                 date="15.03.2025", license="181.0"),                 # т/м³ и лицензия
        WasteAct(fkko_code="40414000115", name="тара деревянная, утратившая "
                 "потребительские свойства", mass=Decimal("0.5"), date="3 кв 2025"),
    ]
    ctx.wastes = [WasteFlow(fkko_code="40414000115", name="тара деревянная, утратившая "
                            "потребительские свойства", hazard_class=5)]
    workspace.save_context("ОРГ", "Пл", ctx)
    att = workspace.site_dir("ОРГ", "Пл") / "attachments"
    att.mkdir(exist_ok=True)
    (att / "скан.jpg").write_bytes(b"\xff\xd8junk")                   # остался в приёме
    return ctx


def test_intake_map_marks_unread_files():
    _site()
    out = server.api_intake_map({}, {"org": "ОРГ", "site": "Пл"})
    files = {d["file"]: d for d in out["docs"]}
    assert files["скан.jpg"]["status"] == "unread"
    assert "не разобран" in files["скан.jpg"]["reason"]
    assert out["totals"]["unread"] == 1


def test_data_issues_by_category_with_fixes():
    _site()
    out = server.api_data_issues({}, {"org": "ОРГ", "site": "Пл"})
    cats = out["categories"]
    kinds = {x["kind"] for x in cats["Отходы"]}
    assert {"missing_period", "implausible", "license", "bad_code"} <= kinds
    mp = next(x for x in cats["Отходы"] if x["kind"] == "missing_period")
    assert mp["fix"]["type"] == "input" and mp["fix"]["path"] == "waste_acts[0].date"
    # «Мусор офисный» тоже даёт bad_code (наименование расходится с каталогом),
    # поэтому ищем именно строку с опечаткой в коде тары
    bad = next(x for x in cats["Отходы"]
               if x["kind"] == "bad_code" and x["value"] == "40414000115")
    assert bad["fix"]["type"] == "replace"
    assert bad["fix"]["options"][0]["value"] == "40414000515"     # подсказка из каталога
    assert any(x["kind"] == "short_name" and x["suggest"] == "ИП Миних Е.А."
               for x in cats["Организация"])
    assert any(x["label"] == "Отчётный год" for x in cats["Объект"])
    assert any(x["kind"] == "unread" for x in cats["Объект"])
    assert out["totals"]["all"] == sum(len(v) for v in cats.values())


def test_form_gaps_lists_missing_with_fix():
    _site()
    out = server.api_form_gaps({}, {"org": "ОРГ", "site": "Пл"})
    forms = out["forms"]
    assert "declaration-nvos" in forms and "pek" in forms
    decl = forms["declaration-nvos"]
    assert decl["domain"] == "reporting" and not decl["ok"]
    paths = {m["path"] for m in decl["missing"]}
    assert "period.year" in paths                                   # года нет
    year_fix = next(m["fix"] for m in decl["missing"] if m["path"] == "period.year")
    assert year_fix["type"] == "input" and year_fix["tab"] == "obj"
    assert any(f["domain"] == "development" for f in forms.values())


def test_plausibility_rule():
    from ecodoc.core.sanitize_records import act_plausibility_problem as p
    assert p(WasteAct(mass=Decimal("1.9"), volume_m3=Decimal("12.5"))) == ""
    assert "не сходятся" in p(WasteAct(mass=Decimal("0.002"), volume_m3=Decimal("2")))
    assert "неправдоподобна" in p(WasteAct(mass=Decimal("48980")))
