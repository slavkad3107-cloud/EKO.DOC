"""Раунд 4 замечаний (04.09.2026): охрана реквизитов от проектных документов,
категория «отходы», отчёт приёма по разделам, партии в карте приёма,
удаление файла вместе с его данными, ручной выбор ИИ не перебивается."""
from decimal import Decimal

from ecodoc.ai import analyzer
from ecodoc.core import workspace
from ecodoc.core.models import ReportContext, WasteAct
from ecodoc.gui import server
from ecodoc.intake import candidates, intake, sources


def _ctx(inn="780600114472"):
    ctx = ReportContext()
    ctx.organization.inn = inn
    ctx.organization.name = "ИП Миних"
    return ctx


# ── реквизиты из чужих/проектных документов не берутся ──────────────────
def test_org_block_rejected_when_inn_differs():
    ctx = _ctx()
    prob = analyzer.org_block_problem(ctx, {"inn": "7801234567", "name": "ООО Проект"},
                                      "Акт.pdf (лист 1)")
    assert "другой организации" in prob and "7801234567" in prob


def test_org_block_rejected_for_project_document_without_inn():
    ctx = _ctx()
    prob = analyzer.org_block_problem(ctx, {"name": "ООО Проектировщик",
                                            "address": "СПб"},
                                      "Раздел ООС том 8.pdf (лист 12)")
    assert "проектный документ" in prob


def test_org_block_allowed_for_own_card_and_matching_inn():
    ctx = _ctx()
    assert analyzer.org_block_problem(ctx, {"inn": "780600114472", "name": "ИП Миних"},
                                      "ООС.pdf") == ""
    assert analyzer.org_block_problem(ctx, {"name": "ИП Миних"}, "карточка.pdf",
                                      doc_type="устав") == ""
    assert analyzer.org_block_problem(_ctx(""), {"name": "ИП Миних"}, "договор.pdf") == ""


def test_merge_org_rejects_foreign_block_with_reason():
    ctx = _ctx()
    rep = analyzer.ExtractionReport()
    analyzer._merge_org(ctx, {"organization": {"inn": "7801234567", "kpp": "780101001",
                                               "address": "чужой адрес"}},
                        {}, "ПМООС.pdf (лист 3)", rep)
    assert ctx.organization.address == ""            # не записано
    assert rep.rejected and rep.rejected[0].field == "organization"
    assert "другой организации" in rep.rejected[0].reason


def test_collect_marks_foreign_requisites_rejected(tmp_path):
    ctx = _ctx()
    sink = candidates.Sink(tmp_path)
    analyzer._collect(sink, {"organization": {"inn": "7801234567", "email": "a@b.ru"}},
                      {}, {}, "ООС.pdf", "m", (1, 1), ctx=ctx)
    items = sink.store.items
    assert items and all(c.state == candidates.REJECTED for c in items)
    assert "другой организации" in items[0].reason


# ── отчёт по разделам и человеческие подписи ─────────────────────────────
def test_report_sections_and_human_labels():
    rep = analyzer.ExtractionReport()
    rep.accepted.append(analyzer.Accepted("organization.inn", "780600114472", "к.pdf"))
    rep.conflicts.append(analyzer.Conflict("вещество (воздух) 0349.mass_norm",
                                           "71.83", "0", "5_1.pdf"))
    rep.rejected.append(analyzer.Rejected("вещество (вода)", "ливневые", "поток", "н.pdf"))
    rep.accepted.append(analyzer.Accepted("акт 73310001724 (утилизация)", "1 т", "а.pdf"))
    s = rep.sections()
    assert set(s) >= {"Организация", "Выбросы", "Сбросы", "Отходы"}
    assert s["Организация"]["accepted"][0]["field"] == "организация: ИНН"
    assert "масса в пределах норматива" in s["Выбросы"]["conflicts"][0]["field"]
    rep.used_model, rep.configured = "deepseek/deepseek-chat", "cohere/command-a"
    text = rep.render()
    assert "в настройках выбрана cohere/command-a" in text
    assert "РАСХОЖДЕНИЕ" in text and "КОНФЛИКТ" not in text


# ── партия, исключённые, удаление файла с данными ────────────────────────
def _site():
    workspace.add_org("ОРГ")
    workspace.add_site("ОРГ", "Пл")
    return workspace.site_dir("ОРГ", "Пл")


def test_store_stamps_batch_and_skips_excluded(tmp_path):
    site_dir = _site()
    f = tmp_path / "справка.txt"
    f.write_text("акт", encoding="utf-8")
    names, log = intake.store([str(f)], "ОРГ", "Пл", batch="20260904_1200")
    reg, by_sha, _ = intake._load_registry(site_dir / "attachments")
    assert names == ["справка.txt"] and reg[0]["batch"] == "20260904_1200"
    sha = reg[0]["sha1"]
    # исключить и загрузить снова — не принимается
    intake._purge_sources(site_dir / "attachments", names)
    sources.exclude(site_dir, sha, "справка.txt")
    names2, log2 = intake.store([str(f)], "ОРГ", "Пл")
    assert names2 == [] and any("удалён пользователем ранее" in x for x in log2)
    assert sources.unexclude(site_dir, sha)
    names3, _ = intake.store([str(f)], "ОРГ", "Пл")
    assert names3 == ["справка.txt"]


def test_forget_removes_file_candidates_acts_and_extras():
    site_dir = _site()
    ctx = workspace.load_context("ОРГ", "Пл")
    ctx.organization.inn = "780600114472"
    ctx.organization.email = "x@y.ru"
    ctx.waste_acts = [WasteAct(fkko_code="73310001724", name="Мусор", hazard_class=4,
                               mass=Decimal("1.5"), date="15.03.2025",
                               receiver="ООО Полигон")]
    ctx.extra["lab_results"] = [{"kind": "КХА", "_src": "акт.pdf (лист 2)"},
                                {"kind": "КХА", "_src": "другой.pdf"}]
    ctx.provenance["email"] = {"src": "акт.pdf (лист 1)", "by": "ai"}
    ctx.provenance["_pages"] = {"акт.pdf": {"email": {"page": 1}}}
    workspace.save_context("ОРГ", "Пл", ctx)
    att = site_dir / "attachments"
    att.mkdir(exist_ok=True)
    (att / "акт.pdf").write_bytes(b"%PDF")
    intake._save_registry(att, [{"file": "акт.pdf", "sha1": "a" * 40, "received": "2026-09-04"}])
    sources.remember(site_dir, "a" * 40, file="акт.pdf", method="pdf")
    store = candidates.Store(site_dir)
    key = candidates.act_key("73310001724", "15.03.2025", "ООО Полигон", "1.5") + ".mass"
    store.add(candidates.Candidate(key=key, value="1.5", file="акт.pdf",
                                   state=candidates.ACCEPTED))
    store.add(candidates.Candidate(key="organization.email", value="x@y.ru",
                                   file="акт.pdf", state=candidates.ACCEPTED))
    store.add(candidates.Candidate(key="organization.inn", value="780600114472",
                                   file="карточка.pdf", state=candidates.ACCEPTED))
    store.save()

    res = server.api_intake_forget({}, {"org": "ОРГ", "site": "Пл", "file": "акт.pdf"})
    assert res["removed_file"] and not (att / "акт.pdf").exists()
    assert res["acts"] == 1 and res["candidates"] == 2 and res["fields"] == 1
    assert res["extras"] == 1
    ctx2 = workspace.load_context("ОРГ", "Пл")
    assert ctx2.waste_acts == [] and ctx2.organization.email == ""
    assert ctx2.organization.inn == "780600114472"        # из другого файла — остался
    assert [x["_src"] for x in ctx2.extra["lab_results"]] == ["другой.pdf"]
    assert "email" not in ctx2.provenance and "акт.pdf" not in ctx2.provenance["_pages"]
    left = candidates.Store(site_dir).items
    assert [c.file for c in left] == ["карточка.pdf"]
    assert ("a" * 40) in sources.excluded(site_dir)
    imap = server.api_intake_map({}, {"org": "ОРГ", "site": "Пл"})
    assert imap["excluded"][0]["file"] == "акт.pdf"
    assert all(d["file"] != "акт.pdf" for d in imap["docs"])


def test_intake_map_reports_batches():
    site_dir = _site()
    sources.remember(site_dir, "b" * 40, file="старый.pdf", method="pdf",
                     batch="20260901_1000", received="2026-09-01")
    sources.remember(site_dir, "c" * 40, file="новый.pdf", method="pdf",
                     batch="20260904_1200", received="2026-09-04")
    out = server.api_intake_map({}, {"org": "ОРГ", "site": "Пл"})
    assert out["last_batch"] == "20260904_1200"
    by = {d["file"]: d for d in out["docs"]}
    assert by["новый.pdf"]["batch"] == "20260904_1200"
    assert by["старый.pdf"]["received"] == "2026-09-01"


# ── ручной выбор ИИ не перебивается автопроверкой ────────────────────────
def test_user_model_choice_survives_health_pick(monkeypatch):
    from ecodoc.ai import detect
    from ecodoc.ai.config import AIConfig
    cfg = AIConfig(provider="cohere", model="command-a",
                   detected={"picked_by": "user"})
    monkeypatch.setattr("ecodoc.ai.config.load_config", lambda: cfg)
    monkeypatch.setattr(detect, "_migrate_to_free", lambda c: c)
    calls = []
    monkeypatch.setattr("ecodoc.ai.health.fresh", lambda: calls.append(1) or ["x"])
    out = detect.ensure_configured()
    assert (out.provider, out.model) == ("cohere", "command-a") and not calls
