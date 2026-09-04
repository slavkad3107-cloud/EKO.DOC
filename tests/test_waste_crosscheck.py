"""Сверка отходов по источникам: ООС/ПНООЛР ↔ паспорта ↔ протоколы ↔ акты."""
import json
from decimal import Decimal

from ecodoc.core import waste_crosscheck as wc
from ecodoc.core.models import ReportContext, WasteAct, WasteFlow
from ecodoc.intake import candidates, sources

OOS, ACT = "ООС.pdf", "акт.pdf"
LAMP, TBO, WOOD = "47110101521", "73310001724", "40414000515"


def _site(tmp_path):
    """Площадка: ООС.pdf (kind oos) и акт.pdf (kind act) в реестре, кандидаты
    из обоих файлов."""
    sources.remember(tmp_path, "a" * 40, file=OOS, doc_type="oos")
    sources.remember(tmp_path, "b" * 40, file=ACT, doc_type="act")
    st = candidates.Store(tmp_path)
    # ООС: лампы (норматив 0,1 т), ТБО (норматив 2 т), тара (только в ООС)
    for fkko, name, cls, norm in ((LAMP, "Лампы ртутные", "1", "0.1"),
                                  (TBO, "Мусор от офисных помещений", "4", "2"),
                                  (WOOD, "Тара деревянная", "5", "0.5")):
        st.add(candidates.Candidate(key=f"wastes[fkko={fkko}].generated",
                                    value=norm, file=OOS, page=12))
        st.add(candidates.Candidate(key=f"wastes[fkko={fkko}].name",
                                    value=name, file=OOS, page=12))
        st.add(candidates.Candidate(key=f"wastes[fkko={fkko}].hazard_class",
                                    value=cls, file=OOS, page=12))
    # акт: ТБО под другим именем и «чужой» отход, которого в ООС нет
    st.add(candidates.Candidate(key=candidates.act_key(TBO, "15.03.2025", "ООО Оператор", "3") + ".mass",
                                value="3", file=ACT, page=1))
    st.add(candidates.Candidate(key=candidates.act_key("82220101215", "15.03.2025", "ООО Оператор", "1") + ".mass",
                                value="1", file=ACT, page=1))
    st.save()
    return tmp_path


def _ctx():
    ctx = ReportContext()
    ctx.period.year = 2025
    ctx.wastes = [WasteFlow(fkko_code=LAMP, name="Лампы ртутные", hazard_class=1),
                  WasteFlow(fkko_code=TBO, name="Мусор от офисных помещений",
                            hazard_class=4),
                  WasteFlow(fkko_code="82220101215", name="Лом бетона", hazard_class=5)]
    ctx.waste_acts = [
        WasteAct(fkko_code=TBO, name="мусор офисный", hazard_class=5,
                 mass=Decimal("3"), date="15.03.2025", receiver="ООО Оператор"),
        WasteAct(fkko_code="82220101215", name="Лом бетона", hazard_class=5,
                 mass=Decimal("1"), date="15.03.2025", receiver="ООО Оператор"),
        # прошлый год — в факт за 2025 не входит
        WasteAct(fkko_code=TBO, name="мусор офисный", hazard_class=4,
                 mass=Decimal("50"), date="10.10.2024", receiver="ООО Оператор"),
    ]
    return ctx


def _row(out, fkko):
    return next(r for r in out["rows"] if r["fkko"] == fkko)


def test_build_rules_on_synthetic_site(tmp_path):
    out = wc.build(_ctx(), _site(tmp_path))
    assert not out["no_oos"]
    assert out["totals"]["fkko"] == 4
    json.dumps(out)                                   # сериализуемо

    # (а) тара: в ООС есть, актов нет
    wood = _row(out, WOOD)
    assert "oos" in wood["sources"] and "act" not in wood["sources"]
    assert any("справок-актов" in i for i in wood["issues"])
    assert wood["sources"]["oos"]["files"] == [OOS]
    assert wood["sources"]["oos"]["norm_t"] == 0.5
    assert wood["name"] == "Тара деревянная" and wood["hazard_class"] == 5

    # (б) лом бетона: по актам есть, в ООС нет
    beton = _row(out, "82220101215")
    assert any("в ООС/ПНООЛР не предусмотрен" in i for i in beton["issues"])
    assert beton["sources"]["act"]["files"] == [ACT]
    assert beton["sources"]["act"]["fact_t"] == 1.0

    # (в) ТБО: имя в актах отличается от ООС; (г) класс расходится (4 ↔ 5);
    # (д) факт 3 т > норматива 2 т более чем на 10 % (акт 2024 не считается)
    tbo = _row(out, TBO)
    assert tbo["sources"]["act"]["fact_t"] == 3.0
    assert tbo["sources"]["oos"]["norm_t"] == 2.0
    assert any("отличается от ООС" in i for i in tbo["issues"])
    assert any("класс опасности расходится" in i for i in tbo["issues"])
    assert any("превышает норматив" in i for i in tbo["issues"])
    # (е) IV класс без паспорта
    assert any("паспорта отхода нет" in i for i in tbo["issues"])

    # (е) лампы I класса — паспорта нет, (а) актов нет
    lamp = _row(out, LAMP)
    assert any("паспорта отхода нет" in i for i in lamp["issues"])
    assert any("справок-актов" in i for i in lamp["issues"])

    assert out["totals"]["oos_only"] == 2           # лампы и тара
    assert out["totals"]["acts_only"] == 1          # лом бетона
    assert out["totals"]["with_issues"] == 4


def test_passport_and_protocol_rules(tmp_path):
    """(е)/(ж)/(з): паспорт из справочника снимает «нет паспорта», протокол
    снимает «нет протокола», состав из чужого документа — замечание."""
    site = _site(tmp_path)
    ctx = _ctx()
    ctx.extra["waste_passports"] = [
        {"fkko": TBO, "name": "Мусор от офисных помещений", "hazard_class": 4,
         "components": [{"name": "бумага", "percent": "60"}],
         "_src": "паспорт ТБО.pdf (лист 1)"},
        {"fkko": LAMP, "name": "Лампы ртутные", "hazard_class": 1,
         "components": [{"name": "стекло", "percent": "92"}],
         "_src": "расчёт платы.xls", "_kind": "other"},
    ]
    ctx.extra["lab_results"] = [
        {"kind": "КХА", "protocol_no": "7", "date": "01.02.2025", "lab": "ТАСИС",
         "object": "Мусор от офисных помещений", "_src": "протокол КХА.pdf"},
    ]
    out = wc.build(ctx, site)
    tbo = _row(out, TBO)
    assert "passport" in tbo["sources"] and "protocol" in tbo["sources"]
    assert tbo["sources"]["passport"]["files"] == ["паспорт ТБО.pdf"]
    assert not any("паспорта отхода нет" in i for i in tbo["issues"])
    assert not any("нет протокола КХА" in i for i in tbo["issues"])
    lamp = _row(out, LAMP)
    assert "other" in lamp["sources"]
    assert any("паспорта отхода нет" in i for i in lamp["issues"])
    assert any("не из ООС/протокола" in i for i in lamp["issues"])
    # V класс без биотеста
    beton = _row(out, "82220101215")
    assert any("биотестирования" in i for i in beton["issues"])


def test_no_oos_when_only_acts(tmp_path):
    """Без ООС правило (б) молчит — иначе каждый акт был бы «не предусмотрен»."""
    sources.remember(tmp_path, "b" * 40, file=ACT, doc_type="act")
    ctx = _ctx()
    out = wc.build(ctx, tmp_path)
    assert out["no_oos"]
    assert not any("не предусмотрен" in i for r in out["rows"] for i in r["issues"])


def test_build_without_site_dir():
    out = wc.build(_ctx(), None)
    assert out["no_oos"] and out["totals"]["fkko"] == 3


def test_bucket_and_kind_from_old_records_by_name(tmp_path):
    """Старые записи без doc_type — класс по имени файла кандидата."""
    assert wc.bucket("protocol_kha") == "protocol" and wc.bucket("biotest") == "protocol"
    assert wc.bucket("egrul") == "other" and wc.bucket("oos") == "oos"
    st = candidates.Store(tmp_path)
    st.add(candidates.Candidate(key=f"wastes[fkko={LAMP}].generated", value="0.1",
                                file="ПНООЛР_2025.pdf", page=3))
    st.save()
    out = wc.build(_ctx(), tmp_path)
    assert _row(out, LAMP)["sources"]["pnoolr"]["norm_t"] == 0.1
    assert not out["no_oos"]


def test_api_route_registered():
    from ecodoc.gui import server
    assert server.POST_ROUTES["waste_crosscheck"] is server.api_waste_crosscheck
