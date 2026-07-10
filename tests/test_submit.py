"""Контур подачи в ЛКПП: сверка XML под ИП + сборка пакета."""
from ecodoc.core import registry
from ecodoc.core.models import (NVOSObject, Organization, ReportContext,
                                ReportPeriod, WasteFlow)
from ecodoc.submit import build_package


def _ctx_ip():
    return ReportContext(
        organization=Organization(name="ИП Миних Е.А.", inn="780600114472",
                                  ogrn="316470400067741", okpo="0123456789",
                                  okved="38.11", oktmo="41612154", director_name="Миних Е.А."),
        period=ReportPeriod(year=2025),
        objects=[NVOSObject(code="41-0247-000123-П", oktmo="41612154", name="Янино")],
        wastes=[WasteFlow(fkko_code="73310001724", name="ТКО", hazard_class=4,
                          generated="2", transferred="2", transferred_burial="2")])


def test_ip_xml_fields(tmp_path):
    registry.load_all()
    rep = registry.get("2tp-waste")(_ctx_ip())
    xml = rep.render_xml(tmp_path / "ip.xml").read_text(encoding="utf-8")
    assert "<FINDIVID>true</FINDIVID>" in xml                      # ИП
    assert "<OFFICIAL>Индивидуальный предприниматель</OFFICIAL>" in xml
    assert "<NOT_REG_OBJ>false</NOT_REG_OBJ>" in xml               # объект на учёте
    assert "<REG_NUMBER>41-0247-000123-П</REG_NUMBER>" in xml


def test_tr_disp_is_burial(tmp_path):
    """TP2_TR_DISP = передано на захоронение, не «всего передано»."""
    ctx = _ctx_ip()
    ctx.wastes[0].transferred = "5"       # всего передано
    ctx.wastes[0].transferred_burial = "3"  # из них на захоронение
    registry.load_all()
    xml = registry.get("2tp-waste")(ctx).render_xml(tmp_path / "b.xml").read_text(encoding="utf-8")
    assert "<TP2_TRANSF>5.0</TP2_TRANSF>" in xml
    assert "<TP2_TR_DISP>3.0</TP2_TR_DISP>" in xml


def test_build_package(tmp_path):
    registry.load_all()
    rep = registry.get("2tp-waste")(_ctx_ip())
    rep.ctx.extra["mchd"] = {"number": "N1", "powers": ["RPNDZ_REPORT"],
                             "doveritel": "ИП Миних", "predstavitel": "ИП Дубовик"}
    res = build_package(rep, tmp_path)
    assert res["dir"].exists()
    assert "xml" in res["files"] and "print" in res["files"]
    assert res["checklist"].exists()
    text = res["checklist"].read_text(encoding="utf-8")
    assert "RPNDZ_REPORT" in text and "Импорт XML" in text


def test_preflight_flags_missing_ogrnip(tmp_path):
    ctx = _ctx_ip()
    ctx.organization.ogrn = ""            # нет ОГРНИП
    registry.load_all()
    issues = registry.get("2tp-waste")(ctx).validate()
    assert any(i.level == "error" and "ОГРНИП" in i.field for i in issues)
