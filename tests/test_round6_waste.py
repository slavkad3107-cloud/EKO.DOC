"""Раунд 6 (07.09.2026, вечер): удаление отхода насовсем, кэш текстов и
переразбор без исходника, составы для расчёта класса, сведения из
сгенерированных паспортов, пустые акты не сохраняются, страница без кэша."""
from decimal import Decimal

from ecodoc.ai import analyzer
from ecodoc.core import waste_crosscheck, waste_exclude, workspace
from ecodoc.core.models import WasteAct, WasteFlow
from ecodoc.gui import server
from ecodoc.intake import candidates, intake, sources, textcache


def _site():
    workspace.add_org("ОРГ")
    workspace.add_site("ОРГ", "Пл")
    return workspace.site_dir("ОРГ", "Пл")


def _seed():
    site_dir = _site()
    ctx = workspace.load_context("ОРГ", "Пл")
    ctx.organization.inn = "780600114472"
    ctx.wastes = [WasteFlow(fkko_code="73310001724", name="Мусор офисный", hazard_class=4,
                            generated=Decimal("2")),
                  WasteFlow(fkko_code="40414000515", name="Тара деревянная", hazard_class=5)]
    ctx.waste_acts = [WasteAct(fkko_code="73310001724", name="Мусор", hazard_class=4,
                               mass=Decimal("1"), date="15.03.2025", receiver="ООО П"),
                      WasteAct(fkko_code="40414000515", name="Тара", mass=Decimal("0.5"),
                               date="3 кв 2025")]
    ctx.extra["waste_passports"] = [{"fkko": "73310001724", "name": "Мусор офисный",
                                     "hazard_class": 4,
                                     "components": [{"name": "Бумага", "percent": "60"},
                                                    {"name": "Пластик", "percent": "40"}],
                                     "_src": "паспорт.pdf"}]
    ctx.extra["oos_wastes"] = [{"fkko": "73310001724", "name": "Мусор", "stage": "строительство",
                                "mass_t": "2", "volume_m3": "10", "density": "0.2"}]
    workspace.save_context("ОРГ", "Пл", ctx)
    store = candidates.Store(site_dir)
    store.add(candidates.Candidate(key="wastes[fkko=73310001724].generated", value="2",
                                   file="ООС.pdf", state=candidates.ACCEPTED))
    store.save()
    return site_dir


def test_waste_forget_removes_everywhere_and_excludes():
    site_dir = _seed()
    res = server.api_waste_forget({}, {"org": "ОРГ", "site": "Пл", "fkko": "7 33 100 01 72 4"})
    assert res["wastes"] == 1 and res["acts"] == 1 and res["passports"] == 1
    assert res["oos"] == 1 and res["candidates"] == 1
    ctx = workspace.load_context("ОРГ", "Пл")
    assert [w.fkko_code for w in ctx.wastes] == ["40414000515"]
    assert all(a.fkko_code != "73310001724" for a in ctx.waste_acts)
    assert waste_exclude.is_excluded(ctx, "73310001724")
    # кандидат отклонён с причиной, сверка код не показывает
    c = candidates.Store(site_dir).items[0]
    assert c.state == candidates.REJECTED and "удалено" in c.reason
    rows = waste_crosscheck.build(ctx, site_dir)["rows"]
    assert all(r["fkko"] != "73310001724" for r in rows)
    # приём не воскрешает: акт/отход/ООС с этим кодом отклоняются с причиной
    rep = analyzer.ExtractionReport()
    analyzer._merge_acts(ctx, {"disposal_acts": [{"fkko": "73310001724", "mass_t": "3",
                                                  "date": "01.04.2025"}]}, "акт.pdf", rep)
    analyzer._merge_wastes(ctx, {"wastes": [{"fkko": "73310001724", "name": "Мусор"}]},
                           {}, "ж.pdf", rep)
    assert not ctx.waste_acts or all(a.fkko_code != "73310001724" for a in ctx.waste_acts)
    assert any("исключён" in r.reason for r in rep.rejected)
    assert not candidates.write(ctx, "wastes[fkko=73310001724].generated", "5")
    # снять исключение
    assert server.api_waste_restore({}, {"org": "ОРГ", "site": "Пл", "fkko": "73310001724"})["ok"]
    assert not waste_exclude.is_excluded(workspace.load_context("ОРГ", "Пл"), "73310001724")


def test_context_save_drops_empty_acts():
    _site()
    got = server.api_context_get({"org": "ОРГ", "site": "Пл"}, {})
    ctx = got["context"]
    ctx["waste_acts"] = [{"fkko_code": "", "name": "", "mass": "0", "volume_m3": "0"},
                         {"fkko_code": "73310001724", "name": "Мусор", "mass": "1"}]
    out = server.api_context_save({}, {"org": "ОРГ", "site": "Пл", "context": ctx,
                                       "version": got["version"]})
    assert out["ok"] and out["dropped_empty_acts"] == 1
    assert len(workspace.load_context("ОРГ", "Пл").waste_acts) == 1


def test_textcache_roundtrip_and_reanalyze_without_source(tmp_path):
    site_dir = _site()
    f = tmp_path / "ООС раздел 8.txt"
    f.write_text("Перечень мероприятий по охране окружающей среды. ИНН 780600114472. "
                 "Код ФККО 7 33 100 01 72 4 мусор офисный.", encoding="utf-8")
    names, _log = intake.store([str(f)], "ОРГ", "Пл")
    intake.analyze_stored(names, "ОРГ", "Пл", use_ai=False)
    att = site_dir / "attachments"
    assert not (att / names[0]).exists()                    # исходник удалён
    sha = sources.sha_by_name(site_dir, names[0])
    assert sha and textcache.has(site_dir, sha)             # текст сохранён
    doc = textcache.load(site_dir, sha)
    assert "7 33 100 01 72 4" in doc.text and doc.from_cache
    imap = server.api_intake_map({}, {"org": "ОРГ", "site": "Пл"})
    row = next(d for d in imap["docs"] if d["file"] == names[0])
    assert row["reanalyze"] is True
    # переразбор без исходника
    struct = {}
    rep = intake.analyze_stored(names, "ОРГ", "Пл", use_ai=False, struct=struct)
    assert struct["from_cache"] == names and "из сохранённого текста" in rep
    assert struct["files_total"] == 1


def test_waste_compositions_and_remember_details():
    from ecodoc.development import waste_passport
    _seed()
    out = server.api_waste_compositions({}, {"org": "ОРГ", "site": "Пл"})
    rows = {r["fkko"]: r for r in out["rows"]}
    assert "73310001724" in rows and rows["73310001724"]["total"] == 100.0
    assert rows["73310001724"]["components"][0]["name"] == "Бумага"
    ctx = workspace.load_context("ОРГ", "Пл")
    n = waste_passport.remember_details(ctx)
    assert n == 1
    rec = ctx.extra["waste_details"]["73310001724"]
    assert rec["components"] and rec["origin"] and rec.get("passport_generated_at")
    assert ctx.extra["passports_generated_at"]
    # без составов — внятная подсказка, а не «загрузите паспорта»
    ctx.extra["waste_passports"] = []
    ctx.extra["waste_details"] = {}
    ctx.extra["passports_generated_at"] = "2026-09-07"
    workspace.save_context("ОРГ", "Пл", ctx)
    out2 = server.api_waste_compositions({}, {"org": "ОРГ", "site": "Пл"})
    assert out2["rows"] == [] and "паспорта сформированы" in out2["note"]


def test_oos_note_explains_old_analysis():
    site_dir = _seed()
    ctx = workspace.load_context("ОРГ", "Пл")
    ctx.extra["oos_wastes"] = []
    sources.remember(site_dir, "e" * 40, file="Раздел ПД № 8 ООС.pdf", method="pdf")
    note = server._oos_note(ctx, site_dir)
    assert "прежней версией" in note and "загрузите файл заново" in note
    textcache.save(site_dir, "e" * 40, type("D", (), {"pages": ["текст"], "text": "текст",
                                                       "path": "Раздел ПД № 8 ООС.pdf",
                                                       "method": "pdf"})())
    assert "Переразобрать" in server._oos_note(ctx, site_dir)
    sources.exclude(site_dir, "e" * 40)
    assert "не загружен" in server._oos_note(ctx, site_dir)


def test_index_rendered_with_version():
    data = server.render_index()
    assert b"__ECODOC_VERSION__" not in data
