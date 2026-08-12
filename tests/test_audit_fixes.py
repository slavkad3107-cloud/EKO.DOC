"""Страховки по итогам аудита: дефекты, найденные на реальной базе.

Каждый тест закрывает конкретную находку — если поведение вернётся, тест
покажет это раньше, чем пользователь.
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from ecodoc.core import workspace
from ecodoc.core.models import (Medium, NVOSObject, Pollutant, ReportContext,
                                WasteAct, WasteFlow)


# ── плата за НВОС ───────────────────────────────────────────────────────
def _ctx_no2(code: str) -> ReportContext:
    c = ReportContext()
    c.period.year = 2025
    p = Pollutant(code=code, name="Азота диоксид", mass_norm=Decimal("1"))
    p.medium = Medium.AIR
    c.pollutants = [p]
    return c


def test_rate_found_without_leading_zero():
    """«301» и «0301» — одно вещество: плата не должна обнуляться."""
    from ecodoc.reports.declaration_nvos.calc import calculate
    full = calculate(_ctx_no2("0301")).total
    short = calculate(_ctx_no2("301")).total
    assert full > 0
    assert short == full


def test_zero_rate_is_reported_not_silent():
    """Ставка 0 в справочнике — это «нет ставки», а не «плата = 0»."""
    from ecodoc.reports.declaration_nvos.calc import calculate
    c = ReportContext()
    c.period.year = 2024
    p = Pollutant(code="9998", name="Вещества без ставки", mass_norm=Decimal("5"))
    p.medium = Medium.WATER
    c.pollutants = [p]
    res = calculate(c)
    assert any("нет ставки" in w for w in res.warnings)


def test_rate_found_by_name_when_code_from_other_list():
    """У сбросов свой перечень кодов — вещество ищется и по наименованию."""
    from ecodoc.reports.declaration_nvos.calc import calculate
    c = ReportContext()
    c.period.year = 2025
    p = Pollutant(code="0101", name="Аммоний-ион", mass_norm=Decimal("1"))
    p.medium = Medium.WATER
    c.pollutants = [p]
    assert calculate(c).total_water > 0


def test_missing_year_warns():
    from ecodoc.reports.declaration_nvos.calc import calculate
    c = _ctx_no2("0301")
    c.period.year = 0
    assert any("год не указан" in w.lower() for w in calculate(c).warnings)


def test_warning_not_duplicated_per_band():
    """Одно вещество без ставки — одно предупреждение, а не по разу на корзину."""
    from ecodoc.reports.declaration_nvos.calc import calculate
    c = ReportContext()
    c.period.year = 2025
    p = Pollutant(code="9999", name="Неведомое", mass_norm=Decimal("1"),
                  mass_limit=Decimal("1"), mass_over=Decimal("1"))
    p.medium = Medium.AIR
    c.pollutants = [p]
    warns = [w for w in calculate(c).warnings if "нет ставки" in w]
    assert len(warns) == 1


def test_tko_rate_separate_from_class_four():
    """У ТКО IV класса своя ставка — она ниже общей ставки IV класса."""
    from ecodoc.core.refdata import rates_nvos
    from ecodoc.reports.declaration_nvos.calc import _waste_rate
    wclass = rates_nvos()["rates_by_year"]["2026"]["waste_by_class"]
    tko = WasteFlow(fkko_code="73310001724", hazard_class=4)
    assert _waste_rate(tko, wclass, "Р6") == Decimal("190")      # ТКО
    assert _waste_rate(tko, wclass, "Р5") == Decimal("1088.3")   # обычный IV
    assert _waste_rate(tko, wclass, "Р6") < _waste_rate(tko, wclass, "Р5")


def test_fifth_class_processing_rate_reachable():
    """У V класса три ставки: добыча / переработка / прочие."""
    from ecodoc.core.refdata import rates_nvos
    from ecodoc.reports.declaration_nvos.calc import _waste_rate
    wclass = rates_nvos()["rates_by_year"]["2025"]["waste_by_class"]
    mining = WasteFlow(fkko_code="20000000000", hazard_class=5, is_mining=True)
    proc = WasteFlow(fkko_code="30000000000", hazard_class=5,
                     industry="перерабатывающая")
    other = WasteFlow(fkko_code="40000000000", hazard_class=5)
    assert _waste_rate(mining, wclass) == Decimal("1.66")
    assert _waste_rate(proc, wclass) == Decimal("60.55")
    assert _waste_rate(other, wclass) == Decimal("26.12")


def test_direct_rates_for_2026_without_indexation():
    """С 2026 ставки заданы напрямую — коэффициент индексации не применяется."""
    from ecodoc.reports.declaration_nvos.calc import calculate
    c = _ctx_no2("0301")
    c.period.year = 2026
    res = calculate(c)
    line = res.lines[0]
    assert line.rate == Decimal("219")      # официальная ставка 2026 г.
    assert line.k_ind == Decimal("1")
    assert res.total == Decimal("219.00")


def test_rates_reference_covers_full_lists():
    """Справочник ставок — полные перечни, а не 8 веществ, как было."""
    from ecodoc.core.refdata import rates_nvos
    by_year = rates_nvos()["rates_by_year"]
    for year in ("2025", "2026"):
        assert len(by_year[year]["air"]) > 150, year
        assert len(by_year[year]["water"]) > 150, year


def test_rates_2025_from_official_act():
    """2025: ставки Распоряжения № 1852-р + доп. коэффициент 1,045."""
    from ecodoc.reports.declaration_nvos.calc import calculate
    c = _ctx_no2("0301")
    c.period.year = 2025
    line = calculate(c).lines[0]
    assert line.rate == Decimal("209.59")      # 138,8 × 1,51 по акту
    assert line.k_ind == Decimal("1.045")      # ПП РФ № 1034
    assert line.amount == Decimal("219.02")


def test_soot_has_own_rate_not_suspended_matter():
    """У сажи своя ставка: раньше стояла ставка взвешенных веществ."""
    from ecodoc.reports.declaration_nvos.calc import calculate
    c = ReportContext()
    c.period.year = 2025
    for code, name in (("0328", "Углерод (сажа)"),
                       ("2902", "Взвешенные вещества")):
        p = Pollutant(code=code, name=name, mass_norm=Decimal("1"))
        p.medium = Medium.AIR
        c.pollutants.append(p)
    rates = {ln.code: ln.rate for ln in calculate(c).lines}
    assert rates["0328"] == Decimal("209.59")
    assert rates["2902"] == Decimal("55.27")
    assert rates["0328"] != rates["2902"]


def test_tko_rate_2025_from_separate_act():
    """ТКО IV класса на 2025 — 99,30 ₽/т (ПП РФ № 595), а не 1001,43.

    И к ней НЕ применяется дополнительный коэффициент 1,045: он установлен
    для ставок Распоряжения № 1852-р, а ставка ТКО — из другого акта."""
    from ecodoc.reports.declaration_nvos.calc import calculate
    c = ReportContext()
    c.period.year = 2025
    c.wastes = [WasteFlow(fkko_code="73310001724", name="ТКО", hazard_class=4,
                          placed_norm=Decimal("1")),
                WasteFlow(fkko_code="40613001313", name="Отход IV",
                          hazard_class=4, placed_norm=Decimal("1"))]
    by_section = {ln.section: ln for ln in calculate(c).lines}
    tko, other = by_section["Р6"], by_section["Р5"]
    assert tko.rate == Decimal("99.3") and tko.k_ind == Decimal("1")
    assert tko.amount == Decimal("99.30")
    assert other.rate == Decimal("1001.43") and other.k_ind == Decimal("1.045")


# ── календарь ───────────────────────────────────────────────────────────
def test_category_parsed_from_any_form():
    from ecodoc.calendar.engine import norm_category
    for value in ("III", "3", "III категория", "объект III категории", " iii "):
        assert norm_category(value) == "III", value
    assert norm_category("") == ""


def test_calendar_sees_object_with_worded_category():
    """«III категория» — та же III: обязанности не должны пропадать."""
    from ecodoc.calendar.engine import build_calendar
    c = ReportContext()
    c.objects = [NVOSObject(code="40-0278-013459-П", category="III категория")]
    c.wastes = [WasteFlow(fkko_code="73310001724", hazard_class=4,
                          generated=Decimal("1"))]
    periodic, _ = build_calendar(c, 2026)
    codes = {e.code for e in periodic}
    assert "declaration-nvos" in codes and "pek-report" in codes


def test_deadline_moved_from_weekend():
    from ecodoc.calendar.engine import workday
    assert workday(date(2026, 3, 1)) == date(2026, 3, 2)      # вс → пн
    assert workday(date(2026, 3, 10)) == date(2026, 3, 10)    # вт — как есть


def test_nvos_payment_deadline_present():
    """Срок внесения самой платы (1 марта) — отдельная обязанность."""
    from ecodoc.calendar.obligations import OBLIGATIONS
    pay = next((o for o in OBLIGATIONS if o.code == "nvos-payment"), None)
    assert pay and (3, 1) in pay.due


def test_deadline_note_for_pek_and_cadastre():
    """Коды форм и коды обязанностей различаются — подсказка всё равно есть."""
    from ecodoc.calendar.engine import deadline_note
    for code in ("pek", "cadastre-spb"):
        assert deadline_note(code, 2025, today=date(2026, 6, 1)), code


def test_water_report_needs_water_body_not_any_water_row():
    """Сброс в городскую канализацию не делает водопользователем."""
    from ecodoc.calendar.engine import build_calendar
    c = ReportContext()
    c.objects = [NVOSObject(code="40-0278-013459-П", category="III")]
    p = Pollutant(code="1502", name="Взвешенные вещества", mass_norm=Decimal("1"))
    p.medium = Medium.WATER
    c.pollutants = [p]
    c.extra["water"] = {"discharge": [{"receiver": "ГУП «Водоканал», канализация"}]}
    codes = {e.code for e in build_calendar(c, 2026)[0]}
    assert "2tp-water" not in codes
    c.extra["water"] = {"discharge": [{"receiver": "река Охта"}]}
    codes = {e.code for e in build_calendar(c, 2026)[0]}
    assert "2tp-water" in codes


def test_submitted_mark_clears_overdue():
    from ecodoc.calendar.engine import build_calendar
    c = ReportContext()
    c.objects = [NVOSObject(code="40-0278-013459-П", category="III")]
    c.extra["submitted"] = {"declaration-nvos:2026": "сдано 05.03.2026, вх. 12"}
    entry = next(e for e in build_calendar(c, 2026)[0]
                 if e.code == "declaration-nvos")
    assert entry.done.startswith("сдано")


def test_declaration_blocked_for_iv_category_only():
    from ecodoc.core import registry
    registry.load_all()
    c = ReportContext()
    c.organization.inn = "7801234564"
    c.organization.name = "ООО «Тест»"
    c.period.year = 2025
    c.objects = [NVOSObject(code="40-0278-013459-Т", category="IV категория")]
    c.wastes = [WasteFlow(fkko_code="73310001724", hazard_class=4,
                          placed_norm=Decimal("1"))]
    issues = registry.all_reports()["declaration-nvos"](c).validate()
    assert any(i.level == "error" and "IV категории" in i.message for i in issues)


# ── данные и хранилище ──────────────────────────────────────────────────
def test_long_site_names_do_not_share_folder():
    """Две площадки с одинаковым началом длинного адреса — разные папки."""
    base = "Санкт-Петербург, посёлок Песочный, Ленинградская улица, участок "
    a = workspace.slug(base + "1, восточнее дома 68а литера А")
    b = workspace.slug(base + "2, западнее дома 70 литера Б")
    assert a != b
    assert len(a) <= 64 and len(b) <= 64


def test_cleanup_keeps_trash():
    """«Освободить место» не должно уничтожать корзину с удалённым."""
    import inspect
    src = inspect.getsource(workspace.cleanup_base)
    assert "rmtree" not in src or ".корзина" not in src.split("rmtree")[1][:80]


def test_org_json_written_atomically(tmp_path, monkeypatch):
    from ecodoc.core.models import Organization
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path))
    workspace.add_org("ОРГ")
    workspace.save_org("ОРГ", Organization(name="ОРГ", inn="7801234564"))
    assert not list((tmp_path / "ОРГ").glob("*.tmp"))
    data = json.loads((tmp_path / "ОРГ" / "org.json").read_text(encoding="utf-8"))
    assert data["inn"] == "7801234564"


def test_broken_org_json_does_not_block_site(tmp_path, monkeypatch):
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path))
    workspace.add_org("ОРГ")
    workspace.add_site("ОРГ", "Площадка")
    (tmp_path / "ОРГ" / "org.json").write_text("{битый", encoding="utf-8")
    ctx = workspace.load_context("ОРГ", "Площадка")     # не должно падать
    assert any("повреждён" in w for w in ctx.extra.get("_warnings", []))
    assert (tmp_path / "ОРГ" / "org.json.битый").exists()


def test_concurrent_save_detected(tmp_path, monkeypatch):
    """Правка из другого окна не затирается молча."""
    from ecodoc.gui import server
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path))
    workspace.add_org("ОРГ")
    workspace.add_site("ОРГ", "Пл")
    first = server.api_context_get({"org": "ОРГ", "site": "Пл"}, {})
    server.api_context_save({}, {"org": "ОРГ", "site": "Пл",
                                 "context": first["context"],
                                 "version": first["version"]})
    # вторая вкладка сохраняет со старой версией
    out = server.api_context_save({}, {"org": "ОРГ", "site": "Пл",
                                       "context": first["context"],
                                       "version": first["version"]})
    assert out.get("conflict") and "другом" in out["error"]


def test_number_from_value_with_units():
    from ecodoc.intake.candidates import _number
    assert _number("12,3 т/год") == Decimal("12.3")
    assert _number("1 234,5") == Decimal("1234.5")
    assert _number("нет данных") is None


def test_manual_row_without_masses_survives_save():
    """Только что заведённая строка отхода не должна исчезать при сохранении."""
    from ecodoc.core.waste_agg import apply_acts
    c = ReportContext()
    c.wastes = [WasteFlow(fkko_code="73310001724", name="Мусор офисный",
                          hazard_class=4)]
    c.waste_acts = [WasteAct(fkko_code="47110101521", name="Лампы",
                             mass=Decimal("0.1"), date="01.02.2025")]
    apply_acts(c)
    assert any(w.fkko_code == "73310001724" for w in c.wastes)


# ── подача ──────────────────────────────────────────────────────────────
def test_package_blocked_on_errors(tmp_path):
    from ecodoc.core import registry
    from ecodoc.submit import build_package
    registry.load_all()
    c = ReportContext()                       # пустой: заведомо есть ошибки
    report = registry.all_reports()["declaration-nvos"](c)
    res = build_package(report, tmp_path)
    assert res["blocked"] and not res["files"]
    assert res["checklist"].exists()
    forced = build_package(report, tmp_path, force=True)
    assert not forced["blocked"] and forced["files"]


def test_checklist_destination_differs_by_form(tmp_path):
    from ecodoc.core import registry
    from ecodoc.submit import build_package
    registry.load_all()
    c = ReportContext()
    c.period.year = 2025
    texts = {}
    for code in ("declaration-nvos", "cadastre-spb", "2tp-air"):
        res = build_package(registry.all_reports()[code](c), tmp_path, force=True)
        texts[code] = res["checklist"].read_text(encoding="utf-8")
    assert "ЛКПП" in texts["declaration-nvos"]
    assert "кадастр" in texts["cadastre-spb"].lower()
    assert "Росстат" in texts["2tp-air"]


def test_unknown_form_requirements_are_not_silent():
    from ecodoc.intake import requirements
    missing, docs = requirements.check(ReportContext(), "нет-такой-формы")
    assert missing and "не описаны" in missing[0]
