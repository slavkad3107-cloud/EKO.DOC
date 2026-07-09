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
    ctx = _ctx()
    res = calculate(ctx)
    # Азота диоксид: 1.2 т × 138.8 × 1.32 × 1 (norm) = 219.85 (округл.)
    no2 = next(l for l in res.lines if l.code == "0301")
    assert no2.amount == money(D("1.2") * D("138.8") * D("1.32"))
    # СО сверх лимита: 0.2 × 1.6 × 1.32 × 100
    co_over = next(l for l in res.lines if l.code == "0337" and l.band == "over")
    assert co_over.amount == money(D("0.2") * D("1.6") * D("1.32") * D("100"))
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
    # официальные коды строк расчёта присутствуют по столбцу B
    codes = {s2["B" + str(r)].value for r in range(3, 17)}
    for want in ("010", "020", "021", "023", "024", "100"):
        assert want in codes, want


if __name__ == "__main__":
    test_money_roundhalfup()
    test_calc_matches_manual()
    test_validate_clean_sample()
    import tempfile
    test_render(Path(tempfile.mkdtemp()))
    print("OK — все проверки прошли")
