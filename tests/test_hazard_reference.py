"""Тесты расчёта класса опасности и справочников."""
from pathlib import Path

from ecodoc.development.hazard_class import Component, calculate
from ecodoc.core.refdata import substances, common_wastes


def test_hazard_class_boundaries():
    # K = 50000/100 + 950000/1e6 = 500.95 → 10³ ≥ K > 10² → III класс
    r = calculate([Component("Нефтепродукты", 50000, 100),
                   Component("Песок", 950000, 1_000_000)])
    assert r.hazard_class == 3
    assert 500 < r.k_total < 502


def test_hazard_class_official_scale():
    """Приложение № 1 к Критериям (пр. № 158, ранее № 536): верхняя граница
    диапазона включается, нижняя — нет. K=10⁴ — это II класс, K=10 — V."""
    def cls(k):
        return calculate([Component("х", k, 1)]).hazard_class
    assert cls(10) == 5 and cls(10.1) == 4          # K ≤ 10 → V
    assert cls(100) == 4 and cls(101) == 3          # 10² ≥ K > 10 → IV
    assert cls(1_000) == 3 and cls(1_001) == 2      # 10³ ≥ K > 10² → III
    assert cls(10_000) == 2 and cls(10_001) == 1    # 10⁴ ≥ K > 10³ → II
    assert cls(500_000) == 1                        # 10⁶ ≥ K > 10⁴ → I


def test_hazard_class_high():
    r = calculate([Component("Ртуть", 1000, 1)])   # K = 1000 → III (граница)
    assert r.hazard_class == 3
    r2 = calculate([Component("Оч.опасное", 100000, 1)])  # K = 1e5 → I
    assert r2.hazard_class == 1


def test_hazard_zero_wi_skipped():
    r = calculate([Component("Инерт", 1_000_000, 0)])
    assert any("Wi" in w for w in r.warnings)
    assert r.hazard_class == 5


def test_reference_loaded():
    subs = substances()
    assert len(subs) >= 20
    no2 = next(s for s in subs if s["code"] == "0301")
    assert no2["pdk_mr"] == 0.2
    assert len(common_wastes()) >= 5


def test_hazard_calc_document(tmp_path):
    """Расчёт оформляется документом: таблица компонентов, K, вывод."""
    from docx import Document

    from ecodoc.development.hazard_class import generate
    path = generate([Component("Нефтепродукты", 50000, 100),
                     Component("Песок", 950000, 1_000_000)],
                    tmp_path / "расчёт.docx",
                    waste_name="Грунт, загрязнённый нефтепродуктами",
                    fkko="93110001394", org_name="ООО «Тест»",
                    basis="протокол КХА № 12-25, Wi — прил. к пр. № 536")
    doc = Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs)
    cells = [c.text for t in doc.tables for r in t.rows for c in r.cells]
    assert "приказ Минприроды России от 31.03.2025 № 158" in text
    assert "10⁶ ≥ K > 10⁴" in text                  # официальные границы
    assert "9 31 100 01 39 4" in cells and "протокол КХА № 12-25" in text
    assert "III (3) классу" in text                 # K ≈ 501 → III класс
    assert "Нефтепродукты" in cells and "50 000" in cells
    assert "Wi, мг/кг" in cells and "Источник Wi" in cells
    assert "‹" not in text


def test_hazard_doc_v_class_biotest_note(tmp_path):
    from docx import Document

    from ecodoc.development.hazard_class import generate
    path = generate([Component("Песок", 1_000_000, 1_000_000)],
                    tmp_path / "v.docx", waste_name="Песок чистый")
    text = "\n".join(p.text for p in Document(str(path)).paragraphs)
    assert "V (5) классу" in text and "биотестированием" in text


def test_api_hazard_class_saves_document(tmp_path, monkeypatch):
    monkeypatch.setenv("ECODOC_RESULTS", str(tmp_path / "res"))
    from ecodoc.gui import server
    out = server.api_hazard_class({}, {
        "components": [{"name": "Нефтепродукты", "ci": 50000, "wi": 100}],
        "save": 1, "waste_name": "Грунт: тест/1", "fkko": "93110001394"})
    assert out["hazard_class"] == 3                 # K = 500 → III
    p = Path(out["path"])
    assert p.exists() and p.suffix == ".docx"
    assert "/" not in p.name.replace("расчёт_класса_", "", 1)  # имя очищено


# ── Wi по первичным показателям (пп. 7–10, приложения № 2–3 к Критериям) ──
def test_wi_from_indicators_formula():
    from ecodoc.development.hazard_class import binf_score, wi_from_indicators
    assert [binf_score(n) for n in (3, 5, 6, 8, 9, 10, 11, 19)] == \
        [1, 1, 2, 2, 3, 3, 4, 4]
    # все баллы 4 при n=11 → Binf=4 → Xi=4 → Zi=5 → lg Wi = 6 → 10⁶
    r = wi_from_indicators([4] * 11)
    assert r["xi"] == 4 and r["wi"] == 1_000_000
    # n=6 (Binf=2), баллы 2,2,3,3,2,2 → Xi=(14+2)/7=2.2857 → Zi=2.7143 → lg=Zi
    r = wi_from_indicators([2, 2, 3, 3, 2, 2])
    assert r["binf"] == 2 and abs(r["zi"] - 2.7143) < 1e-3
    assert abs(r["wi"] - 10 ** 2.7143) < 2
    # Zi = 1: баллы 1,1,1 (n=3, Binf=1) → Xi=1 → Zi=1 → lg=0 → Wi=1
    assert wi_from_indicators([1, 1, 1])["wi"] == 1
    import pytest
    with pytest.raises(ValueError):
        wi_from_indicators([])


def test_components_from_percent_uses_reference_and_indicators():
    from ecodoc.development.hazard_class import (calculate,
                                                 components_from_percent)
    comps, missing = components_from_percent([
        {"name": "бумага", "percent": "60"},
        {"name": "Ртуть", "percent": "0.02"},
        {"name": "Неизвестное вещество Х", "percent": "5",
         "scores": [2, 2, 3, 3, 2, 2]},
        {"name": "Совсем неизвестное", "percent": "1"}])
    by = {c.name: c for c in comps}
    assert by["бумага"].wi == 1_000_000 and by["бумага"].ci == 600_000
    assert by["Ртуть"].wi == 113.07                  # приложение № 4 к № 158
    assert "приложение № 4" in by["Ртуть"].wi_source
    assert by["Неизвестное вещество Х"].wi > 1 and "первичным" in \
        by["Неизвестное вещество Х"].wi_source
    assert missing == ["Совсем неизвестное"]
    r = calculate(comps)
    assert r.hazard_class in (3, 4) and any("Wi" in w for w in r.warnings)


def test_api_hazard_class_passport_mode(tmp_path, monkeypatch):
    """Режим «по паспорту»: {org, site, passport: fkko} → состав из базы →
    docx в класс_опасности/, ответ с k, hazard_class, missing_wi, note."""
    monkeypatch.setenv("ECODOC_RESULTS", str(tmp_path / "res"))
    from docx import Document

    from ecodoc.core import serialize, workspace
    from ecodoc.core.models import NVOSObject, ReportContext, WasteFlow
    from ecodoc.gui import server
    workspace.add_org("ОргHZ")
    workspace.add_site("ОргHZ", "ПлHZ")
    ctx = ReportContext()
    ctx.organization.name = "ООО «Ромашка»"
    ctx.organization.inn = "7800000000"
    ctx.objects = [NVOSObject(code="40-0178-001234-П", name="Площадка",
                              address="СПб, ул. Тестовая, 5")]
    ctx.wastes = [WasteFlow(fkko_code="7 33 100 01 72 4", name="Мусор офисный",
                            hazard_class=4)]
    ctx.extra["waste_passports"] = [{
        "fkko": "73310001724", "name": "Мусор офисный", "hazard_class": 4,
        "_src": "006.jpg",
        "components": [{"name": "бумага", "percent": "60"},
                       {"name": "полиэтилен", "percent": "30"},
                       {"name": "нефтепродукты", "percent": "5"},
                       {"name": "Загадочный компонент", "percent": "5"}]}]
    serialize.to_json(ctx, workspace.site_dir("ОргHZ", "ПлHZ") / "context.json")
    out = server.api_hazard_class({}, {"org": "ОргHZ", "site": "ПлHZ",
                                       "passport": "73310001724", "save": 1})
    assert "error" not in out
    assert out["k"] == out["k_total"] and out["hazard_class"] in (3, 4)
    assert out["missing_wi"] == ["Загадочный компонент"]
    assert "паспорт" in out["note"]
    p = Path(out["path"])
    assert p.exists() and p.parent.name == "класс_опасности"
    doc = Document(str(p))
    text = "\n".join(x.text for x in doc.paragraphs)
    cells = [c.text for t in doc.tables for r in t.rows for c in r.cells]
    assert "ОргHZ" in text and "7 33 100 01 72 4" in cells   # org — из org.json
    assert "Загадочный компонент" in text and "БДО" in text
    assert "‹" not in text and "‹" not in "".join(cells)
    # тело {org, site, fkko} — тот же режим
    out_f = server.api_hazard_class({}, {"org": "ОргHZ", "site": "ПлHZ",
                                         "fkko": "7 33 100 01 72 4", "save": 0})
    assert out_f["hazard_class"] == out["hazard_class"] and "path" not in out_f
    # без components и без fkko/passport в теле — старая ошибка калькулятора
    assert "error" in server.api_hazard_class({}, {"org": "ОргHZ", "site": "ПлHZ"})
    # ручной режим (контракт GUI) не сломан, Wi без значения — из справочника
    out2 = server.api_hazard_class({}, {"components": [
        {"name": "бумага", "ci": 600000, "wi": 0},
        {"name": "Ртуть", "ci": 200, "wi": 0}]})
    assert "error" not in out2
    assert next(c for c in out2["components"] if c["name"] == "Ртуть")["wi"] == 113.07
