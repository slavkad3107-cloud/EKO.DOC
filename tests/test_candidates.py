"""Кандидаты и кросс-сверка: что нашли, откуда и что берём в базу."""
from decimal import Decimal

import pytest

from ecodoc.core.models import (Medium, NVOSObject, Pollutant, ReportContext,
                                WasteAct, WasteFlow)
from ecodoc.intake import candidates as cd
from ecodoc.intake import crosscheck as cc


def _ctx():
    ctx = ReportContext()
    ctx.organization.inn = ""
    ctx.objects = [NVOSObject(code="41-0247-005048-П")]
    ctx.wastes = [WasteFlow(fkko_code="73310001724", name="Мусор офисный",
                            hazard_class=4, generated=Decimal("0"))]
    air = Pollutant(code="0301", name="Азота диоксид")
    air.medium = Medium.AIR
    ctx.pollutants = [air]
    return ctx


# ── ключи и запись значений ──────────────────────────────────────────────

def test_resolve_survives_reordering():
    """Ключ привязан к ФККО, а не к индексу: движение пересчитывается из актов
    и позиции «переезжают»."""
    ctx = _ctx()
    ctx.wastes.insert(0, WasteFlow(fkko_code="47110101521", name="Лампы"))
    assert cd.resolve(ctx, "wastes[fkko=73310001724].generated") == "wastes[1].generated"
    assert cd.resolve(ctx, "wastes[fkko=00000000000].generated") is None


def test_resolve_pollutants_go_to_split_tables():
    ctx = _ctx()
    water = Pollutant(code="0007", name="Взвешенные")
    water.medium = Medium.WATER
    ctx.pollutants.append(water)
    assert cd.resolve(ctx, "pollutants[air;code=0301].mass_norm") == "_pair[0].mass_norm"
    assert cd.resolve(ctx, "pollutants[water;code=0007].mass_norm") == "_pwater[0].mass_norm"


def test_write_casts_types():
    ctx = _ctx()
    assert cd.write(ctx, "wastes[fkko=73310001724].generated", "1,9")
    assert ctx.wastes[0].generated == Decimal("1.9")          # запятая → Decimal
    assert cd.write(ctx, "period.year", "2025")
    assert ctx.period.year == 2025 and isinstance(ctx.period.year, int)
    assert cd.write(ctx, "organization.inn", "7801234564")
    assert not cd.write(ctx, "wastes[fkko=73310001724].generated", "не число")
    assert not cd.write(ctx, "organization.несуществующее", "x")


def test_write_creates_missing_position():
    ctx = _ctx()
    assert cd.write(ctx, "pollutants[air;code=0337].mass_norm", "1.205")
    p = next(p for p in ctx.pollutants if p.code == "0337")
    assert p.medium == Medium.AIR and p.mass_norm == Decimal("1.205")


def test_store_dedup_keeps_state(tmp_path):
    store = cd.Store(tmp_path)
    c1 = store.add(cd.Candidate(key="organization.inn", value="7801234564",
                                file="устав.pdf"))
    c1.state = cd.REJECTED
    store.add(cd.Candidate(key="organization.inn", value="7801234564",
                           file="устав.pdf"))
    assert len(store.items) == 1 and store.items[0].seen == 2
    assert store.items[0].state == cd.REJECTED     # отклонённое не воскресает
    # то же значение из ДРУГОГО файла — отдельная запись (подтверждение)
    store.add(cd.Candidate(key="organization.inn", value="7801234564",
                           file="выписка.pdf"))
    assert len(store.items) == 2
    store.save()
    assert len(cd.Store(tmp_path).items) == 2      # переживает перезагрузку
    assert not (tmp_path / "candidates.tmp").exists()


# ── кросс-сверка ─────────────────────────────────────────────────────────

def _c(key, value, file, **kw):
    return cd.Candidate(key=key, value=value, file=file, label=kw.pop("label", key), **kw)


def test_group_single_agree_conflict():
    ctx = _ctx()
    items = [_c("organization.inn", "7801234564", "устав.pdf"),
             _c("organization.inn", "7801234564", "выписка.pdf"),
             _c("organization.ogrn", "1027801234561", "устав.pdf"),
             _c("organization.kpp", "780101001", "устав.pdf"),
             _c("organization.kpp", "780543001", "счет.pdf")]
    by_key = {g.key: g for g in cc.group(items, ctx)}
    assert by_key["organization.inn"].status == cc.AGREE          # 2 документа
    assert by_key["organization.ogrn"].status == cc.SINGLE
    assert by_key["organization.kpp"].status == cc.CONFLICT
    assert len(by_key["organization.kpp"].values) == 2


def test_group_detects_kg_vs_tonnes():
    ctx = _ctx()
    items = [_c("wastes[fkko=73310001724].generated", "12", "акт1.pdf"),
             _c("wastes[fkko=73310001724].generated", "0.012", "акт2.pdf")]
    g = cc.group(items, ctx)[0]
    assert g.status == cc.UNIT_DOUBT and "кг" in g.hint


def test_unit_conversion_makes_values_agree():
    ctx = _ctx()
    items = [_c("wastes[fkko=73310001724].generated", "12", "акт1.pdf", unit="кг"),
             _c("wastes[fkko=73310001724].generated", "0.012", "акт2.pdf", unit="т")]
    g = cc.group(items, ctx)[0]
    assert g.status == cc.AGREE          # 12 кг и 0,012 т — одно и то же


def test_auto_apply_only_safe_values():
    ctx = _ctx()
    store = cd.Store.__new__(cd.Store)
    store.site_dir = None
    store.items = [_c("wastes[fkko=73310001724].generated", "1.9", "акт.pdf"),
                   _c("organization.inn", "7801234564", "устав.pdf")]
    groups = cc.group(store.items, ctx)
    applied = cc.auto_apply(ctx, store, groups)
    assert "wastes[fkko=73310001724].generated" in applied
    assert ctx.wastes[0].generated == Decimal("1.9")
    # ИНН — критичный реквизит: молча не пишем
    assert "organization.inn" not in applied and ctx.organization.inn == ""


def test_conflict_with_existing_base_value():
    ctx = _ctx()
    ctx.organization.okpo = "11111111"
    g = cc.group([_c("organization.okpo", "22222222", "устав.pdf")], ctx)[0]
    assert g.status == cc.CONFLICT and g.current == "11111111"


def test_decide_accepts_one_and_rejects_others(tmp_path):
    ctx = _ctx()
    store = cd.Store(tmp_path)
    store.add(_c("organization.inn", "7801234564", "устав.pdf"))
    store.add(_c("organization.inn", "780600114472", "счет.pdf"))
    assert cc.decide(ctx, store, "organization.inn", "7801234564")
    assert ctx.organization.inn == "7801234564"
    states = {c.value: c.state for c in store.items}
    assert states["7801234564"] == cd.ACCEPTED
    assert states["780600114472"] == cd.REJECTED


def test_manual_entry_recorded(tmp_path):
    ctx = _ctx()
    store = cd.Store(tmp_path)
    assert cc.manual(ctx, store, "organization.oktmo", "41612155", "ОКТМО")
    assert ctx.organization.oktmo == "41612155"
    rec = store.items[0]
    assert rec.method == cd.MANUAL and rec.state == cd.ACCEPTED


def test_asks_are_concrete_and_skip_pending():
    ctx = _ctx()
    asks = cc.asks(ctx, ["declaration-nvos"])
    by_path = {a.path: a for a in asks}
    assert "10 цифр" in by_path["organization.inn"].question
    assert "ОКТМО" in by_path["organization.oktmo"].question
    # если по полю уже есть кандидат — не спрашиваем, пусть выберет
    asks2 = cc.asks(ctx, ["declaration-nvos"], pending_keys={"organization.inn"})
    assert "organization.inn" not in {a.path for a in asks2}


# ── протоколы по классу опасности ────────────────────────────────────────

def test_lab_gaps_require_kha_and_biotest():
    ctx = _ctx()
    ctx.wastes = [WasteFlow(fkko_code="73310001724", name="Мусор", hazard_class=4),
                  WasteFlow(fkko_code="73310002725", name="Грунт", hazard_class=5)]
    gaps = cc.lab_gaps(ctx)
    assert any("IV класс" in g and "КХА" in g for g in gaps)
    assert any("V класс" in g and "биотест" in g.lower() for g in gaps)

    ctx.extra["lab_results"] = [{"kind": "КХА", "object": ""},
                                {"kind": "биотестирование", "object": ""}]
    assert cc.lab_gaps(ctx) == []          # протоколы есть — замечаний нет


def test_lab_gaps_report_missing_biotest_only():
    ctx = _ctx()
    ctx.wastes = [WasteFlow(fkko_code="73310002725", name="Грунт", hazard_class=5)]
    ctx.extra["lab_results"] = [{"kind": "КХА", "object": ""}]
    gaps = cc.lab_gaps(ctx)
    assert len(gaps) == 1 and "биотест" in gaps[0].lower()


# ── сквозной сценарий ────────────────────────────────────────────────────

def test_intake_collects_candidates_with_source(tmp_path, make_pdf, monkeypatch):
    from ecodoc.core import workspace
    from ecodoc.intake import intake
    workspace.add_org("ТЕСТ")
    workspace.add_site("ТЕСТ", "Пл")
    a = make_pdf(tmp_path / "устав.pdf", ["Устав", "ИНН 7801234564"])
    b = make_pdf(tmp_path / "счет.pdf", ["Счёт-фактура", "ИНН 780600114472"])
    report = intake.run([str(a), str(b)], org="ТЕСТ", site="Пл", use_ai=False)

    site_dir = workspace.site_dir("ТЕСТ", "Пл")
    ctx = workspace.load_context("ТЕСТ", "Пл")
    store = cd.Store(site_dir)
    groups = {g.key: g for g in cc.group(store.items, ctx)}
    inn = groups["organization.inn"]
    assert inn.status == cc.CONFLICT and len(inn.values) == 2
    # у каждого варианта известен файл и лист-источник
    pages = inn.values[0]["pages"]
    assert pages and pages[0]["page"] == 2 and pages[0]["file"].endswith(".pdf")
    assert "требуют выбора: 1" in report


def test_api_candidates_and_decide(tmp_path, make_pdf):
    from ecodoc.core import workspace
    from ecodoc.gui import server
    from ecodoc.intake import intake
    workspace.add_org("ТЕСТ")
    workspace.add_site("ТЕСТ", "Пл")
    a = make_pdf(tmp_path / "устав.pdf", ["Устав", "ИНН 7801234564"])
    b = make_pdf(tmp_path / "счет.pdf", ["Счёт", "ИНН 780600114472"])
    intake.run([str(a), str(b)], org="ТЕСТ", site="Пл", use_ai=False)

    out = server.api_candidates({"org": "ТЕСТ", "site": "Пл"}, {})
    assert out["counts"]["questions"] == 1
    grp = next(g for g in out["groups"] if g["key"] == "organization.inn")
    assert grp["question"] and len(grp["values"]) == 2

    res = server.api_candidate_decide({}, {"org": "ТЕСТ", "site": "Пл",
        "decisions": [{"key": "organization.inn", "value": "7801234564"}]})
    assert res["applied"] == ["organization.inn"]
    assert workspace.load_context("ТЕСТ", "Пл").organization.inn == "7801234564"

    man = server.api_candidate_manual({}, {"org": "ТЕСТ", "site": "Пл",
        "key": "organization.oktmo", "value": "41612155", "label": "ОКТМО"})
    assert man["ok"]
    assert workspace.load_context("ТЕСТ", "Пл").organization.oktmo == "41612155"
