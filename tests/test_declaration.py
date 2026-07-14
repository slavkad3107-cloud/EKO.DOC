"""Тесты расчёта платы и генерации Декларации НВОС."""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecodoc.core import serialize
from ecodoc.core.money import D, money
from ecodoc.reports.declaration_nvos.calc import calculate
from ecodoc.reports.declaration_nvos.report import DeclarationNVOS


def _ctx():
    return serialize.from_json(ROOT / "samples" / "example_context.json")


def test_money_roundhalfup():
    assert money("1.005") == Decimal("1.01")
    assert money("663,2") == Decimal("663.20")


def test_calc_matches_manual():
    ctx = _ctx()  # отчётный год 2025
    res = calculate(ctx)
    # 2025: базовая индексация 1,32 × доп. коэффициент 1,045 (ПП №1034) = 1,3794
    k2025 = D("1.32") * D("1.045")
    # Азота диоксид: 1.2 т × 138.8 × 1.3794 × 1 (norm)
    no2 = next(l for l in res.lines if l.code == "0301")
    assert no2.k_ind == k2025
    assert no2.amount == money(D("1.2") * D("138.8") * k2025)
    # СО сверх лимита: 0.2 × 1.6 × 1.3794 × 100
    co_over = next(l for l in res.lines if l.code == "0337" and l.band == "over")
    assert co_over.amount == money(D("0.2") * D("1.6") * k2025 * D("100"))
    # формула согласована по всем строкам
    for ln in res.lines:
        assert ln.amount == money(ln.mass * ln.rate * ln.k_ind * ln.k_band * ln.k_extra)
    # отход 1 класса (лампы) — передан, не размещён => платы за размещение нет
    assert not any(l.medium == "waste" and l.code == "47110101521" for l in res.lines)
    # итог > 0 и согласован
    assert res.total == money(res.total_air + res.total_water + res.total_waste)
    assert res.total > 0


def test_validate_clean_sample():
    rep = DeclarationNVOS(_ctx())
    rep.ctx.organization.name = rep.ctx.organization.name or "x"
    errors = [i for i in rep.validate() if i.level == "error"]
    assert not errors, errors


def test_render(tmp_path):
    rep = DeclarationNVOS(_ctx())
    xml = rep.render_xml(tmp_path / "d.xml")
    xlsx = rep.render_print(tmp_path / "d.xlsx")
    assert xml.exists() and xml.stat().st_size > 0
    assert xlsx.exists() and xlsx.stat().st_size > 0
    assert "ДекларацияНВОС" in xml.read_text(encoding="utf-8")


def test_print_official_sheets(tmp_path):
    import openpyxl
    rep = DeclarationNVOS(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "d.xlsx"))
    assert wb.sheetnames[:2] == ["стр.1", "стр.2"]
    s2 = wb["стр.2"]
    # официальные коды строк 010–120 по столбцу A (сверено с бланком)
    codes = {s2["A" + str(r)].value for r in range(4, 30)}
    for want in ("010", "020", "021", "023", "024", "025", "100", "120"):
        assert want in codes, want
    # КБК ТКО присутствует (строка 110)
    kbk = {s2["C" + str(r)].value for r in range(4, 30)}
    assert "048 1 12 01042 01 6000 120" in kbk


def test_k_st_applies_to_waste_placement():
    """Кст (стимулирующий коэффициент) умножает плату за размещение."""
    from ecodoc.core.models import (Organization, ReportContext, ReportPeriod,
                                    WasteFlow)
    ctx = ReportContext(
        organization=Organization(name="Т", inn="7801234564", oktmo="40324000"),
        period=ReportPeriod(year=2025),
        wastes=[
            WasteFlow(fkko_code="34620001000", name="без Кст", hazard_class=4,
                      placed_norm="10"),
            WasteFlow(fkko_code="34620001001", name="Кст 0.3", hazard_class=4,
                      placed_norm="10", k_st="0.3"),
        ])
    res = calculate(ctx)
    plain = next(l for l in res.lines if l.name == "без Кст")
    stim = next(l for l in res.lines if l.name == "Кст 0.3")
    assert stim.k_extra == D("0.3")
    assert stim.amount == money(plain.amount * D("0.3"))


def test_declaration_sections_tko_split(tmp_path):
    """ТКО (ФККО «7 3…») уходит в Р6, отходы производства — в Р5."""
    from ecodoc.core.models import ReportContext, ReportPeriod, Organization, WasteFlow
    from ecodoc.reports.declaration_nvos.calc import calculate
    ctx = ReportContext(
        organization=Organization(name="Т", inn="7801234564", oktmo="40324000"),
        period=ReportPeriod(year=2025),
        wastes=[
            WasteFlow(fkko_code="34620001000", name="отход произв.", hazard_class=4,
                      placed_norm="5"),
            WasteFlow(fkko_code="73310001724", name="ТКО", hazard_class=4,
                      placed_norm="3"),
        ])
    c = calculate(ctx)
    assert c.by_section["Р5"] > 0 and c.by_section["Р6"] > 0
    # согласованность: сумма разделов == итог
    assert money(sum(c.by_section.values())) == c.total


if __name__ == "__main__":
    test_money_roundhalfup()
    test_calc_matches_manual()
    test_validate_clean_sample()
    import tempfile
    test_render(Path(tempfile.mkdtemp()))
    print("OK — все проверки прошли")
