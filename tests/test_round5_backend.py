"""Раунд 5 (07.09.2026): реквизиты только из ЕГРЮЛ/сторон договора,
нормативы отходов из ООС (строительные/эксплуатационные, т/м³)."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from ecodoc.ai import analyzer
from ecodoc.core.models import ReportContext, WasteAct
from ecodoc.parsers import extractor


def _ctx(inn="780600114472"):
    ctx = ReportContext()
    ctx.organization.inn = inn
    ctx.organization.name = "ИП Миних"
    return ctx


# ── реквизиты: только ЕГРЮЛ / карточка / стороны договора ────────────────
def test_org_block_from_random_document_rejected():
    ctx = _ctx()
    prob = analyzer.org_block_problem(ctx, {"name": "ООО Полигон", "address": "Янино"},
                                      "акт_утилизации.pdf (лист 1)")
    assert "только из ЕГРЮЛ" in prob


def test_org_block_from_own_documents_allowed():
    ctx = _ctx()
    assert analyzer.org_block_problem(ctx, {"name": "ИП Миних"}, "Выписка ЕГРЮЛ.pdf") == ""
    assert analyzer.org_block_problem(ctx, {"name": "ИП Миних"}, "скан.pdf",
                                      doc_type="карточка предприятия") == ""


def test_parties_pick_by_inn_then_customer_role():
    ctx = _ctx()
    parties = [{"role": "Исполнитель", "inn": "7801234567", "name": "ООО Проект"},
               {"role": "Заказчик", "inn": "780600114472", "name": "ИП Миних",
                "phone": "+7 921 000-00-00", "email": "minih@mail.ru", "address": "СПб, Лиговский 7"}]
    party, why = analyzer.pick_party(ctx, parties)
    assert party["role"] == "Заказчик" and why == ""
    # свой ИНН не известен — берём ЗАКАЗЧИКА
    party2, _ = analyzer.pick_party(_ctx(""), parties)
    assert party2["inn"] == "780600114472"
    # свой ИНН есть, но ни одна сторона не совпала
    none, why2 = analyzer.pick_party(_ctx("7700000000"), parties)
    assert none is None and "ИНН" in why2


def test_merge_parties_fills_phone_email_address_from_contract():
    ctx = _ctx()
    rep = analyzer.ExtractionReport()
    data = {"doc_type": "договор",
            "organization": {"name": "ООО Исполнитель", "inn": "7801234567"},
            "parties": [{"role": "Исполнитель", "inn": "7801234567", "name": "ООО Исполнитель",
                         "address": "чужой адрес"},
                        {"role": "Заказчик", "inn": "780600114472", "name": "ИП Миних",
                         "phone": "+7 921 000-00-00", "email": "minih@mail.ru",
                         "address": "191040, СПб, Лиговский пр., 7"}]}
    analyzer._merge_org(ctx, data, {}, "Договор 24-0622.doc (лист 9)", rep)
    analyzer._merge_parties(ctx, data, {}, "Договор 24-0622.doc (лист 9)", rep)
    assert ctx.organization.phone == "+7 921 000-00-00"
    assert ctx.organization.email == "minih@mail.ru"
    assert ctx.organization.address == "191040, СПб, Лиговский пр., 7"
    assert ctx.organization.name == "ИП Миних"
    assert any(r.field == "organization" for r in rep.rejected)     # чужой блок отклонён


def test_collect_makes_candidates_only_for_our_party(tmp_path):
    from ecodoc.intake import candidates
    ctx = _ctx()
    sink = candidates.Sink(tmp_path)
    data = {"parties": [{"role": "Исполнитель", "inn": "7801234567", "email": "a@b.ru"},
                        {"role": "Заказчик", "inn": "780600114472", "email": "minih@mail.ru"}],
            "oos_wastes": [{"stage": "строительство", "fkko": "82220101215", "mass_t": "12.5"}]}
    analyzer._collect(sink, data, {}, {}, "Договор.doc", "m", (1, 1), ctx=ctx)
    vals = {(c.key, c.value) for c in sink.store.items}
    assert ("organization.email", "minih@mail.ru") in vals
    assert ("organization.email", "a@b.ru") not in vals
    assert ("wastes[fkko=82220101215].generated", "12.5") in vals


def test_regex_requisites_only_from_own_documents():
    ctx = ReportContext()
    junk = SimpleNamespace(path=Path("Раздел ООС.pdf"), text="Проектировщик ООО Проект ИНН 7801234564 КПП 780101001",
                           pages=[], method="pdf")
    extractor._fill_from_doc(ctx, junk)
    assert ctx.organization.inn == ""
    own = SimpleNamespace(path=Path("Карточка предприятия.pdf"),
                          text="Карточка предприятия. ИНН 7801234564 КПП 780101001", pages=[], method="pdf")
    extractor._fill_from_doc(ctx, own)
    assert ctx.organization.inn == "7801234564"


# ── отходы из ООС ────────────────────────────────────────────────────────
def test_oos_wastes_construction_added_exploitation_waits():
    ctx = _ctx()
    rep = analyzer.ExtractionReport()
    data = {"oos_wastes": [
        {"stage": "при строительстве", "fkko": "82220101215", "name": "лом бетонных изделий",
         "hazard_class": 5, "mass_t": "120", "volume_m3": "50"},
        {"stage": "эксплуатация", "fkko": "73310001724",
         "name": "мусор от офисных и бытовых помещений организаций несортированный",
         "hazard_class": 4, "mass_t": "1.2", "volume_m3": "6", "density": "0.2"},
    ]}
    analyzer._merge_oos_wastes(ctx, data, "Раздел ООС том 8.pdf (лист 40)", rep)
    ow = ctx.extra["oos_wastes"]
    assert [x["stage"] for x in ow] == ["строительство", "эксплуатация"]
    assert ow[0]["density"] == "2.400" and ow[0]["decision"] == "add"
    assert ow[1]["decision"] == ""                        # ждёт решения эколога
    assert [w.fkko_code for w in ctx.wastes] == ["82220101215"]   # эксплуатация не заведена
    assert any(d.field.startswith("отходы по ООС (эксплуатация)") for d in rep.doubts)
    assert analyzer.oos_norm_for(ctx, "8 22 201 01 21 5")["mass_t"] == "120"


def test_oos_wastes_rejected_from_non_project_document():
    ctx = _ctx()
    rep = analyzer.ExtractionReport()
    analyzer._merge_oos_wastes(ctx, {"oos_wastes": [{"stage": "строительство", "fkko": "82220101215",
                                                     "mass_t": "1"}]}, "акт.pdf", rep)
    assert "oos_wastes" not in ctx.extra and rep.rejected


def test_data_issues_flags_exploitation_decision_and_density(tmp_path):
    from ecodoc.core import workspace
    from ecodoc.gui import server
    workspace.add_org("ОРГ")
    workspace.add_site("ОРГ", "Пл")
    ctx = workspace.load_context("ОРГ", "Пл")
    ctx.organization.inn = "780600114472"
    ctx.organization.short_name = "ИП Миних Е.А."
    ctx.extra["oos_wastes"] = [
        {"fkko": "73310001724", "name": "мусор офисный", "hazard_class": 4, "stage": "эксплуатация",
         "mass_t": "1.2", "volume_m3": "6", "density": "0.2", "src": "ООС.pdf (лист 3)", "decision": ""},
        {"fkko": "82220101215", "name": "лом бетона", "hazard_class": 5, "stage": "строительство",
         "mass_t": "120", "volume_m3": "50", "density": "2.4", "src": "ООС.pdf (лист 3)", "decision": "add"}]
    ctx.waste_acts = [WasteAct(fkko_code="82220101215", name="лом бетона", hazard_class=5,
                               mass=Decimal("10"), volume_m3=Decimal("40"), date="15.03.2025")]
    workspace.save_context("ОРГ", "Пл", ctx)
    out = server.api_data_issues({}, {"org": "ОРГ", "site": "Пл", "refresh": 1})
    kinds = [x["kind"] for x in out["categories"]["Отходы"]]
    assert "oos_stage" in kinds and "density_oos" in kinds
    dens = next(x for x in out["categories"]["Отходы"] if x["kind"] == "density_oos")
    assert "2.4" in dens["reason"]


def test_crosscheck_takes_norms_from_oos_wastes(tmp_path):
    from ecodoc.core import waste_crosscheck
    ctx = _ctx()
    ctx.extra["oos_wastes"] = [{"fkko": "82220101215", "name": "лом бетонных изделий", "hazard_class": 5,
                                "stage": "строительство", "mass_t": "120", "volume_m3": "50",
                                "density": "2.4", "src": "ООС.pdf (лист 3)", "decision": "add"}]
    ctx.waste_acts = [WasteAct(fkko_code="82220101215", name="лом бетонных изделий", hazard_class=5,
                               mass=Decimal("100"), date="15.03.2025")]
    out = waste_crosscheck.build(ctx, tmp_path)
    row = next(r for r in out["rows"] if r["fkko"] == "82220101215")
    assert row["sources"]["oos"]["norm_t"] == 120.0
    assert row["sources"]["oos"]["density"] == 2.4
    assert out["no_oos"] is False
