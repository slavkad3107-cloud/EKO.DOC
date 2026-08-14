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
    """2025 год: ставки взяты напрямую из Распоряжения № 1852-р.

    Прежняя схема «ставка 2018 × коэффициент индексации» к ним не применяется;
    единственный множитель — дополнительный коэффициент 1,045 (ПП РФ № 1034)."""
    ctx = _ctx()  # отчётный год 2025
    res = calculate(ctx)
    k2025 = D("1.045")
    # Азота диоксид: 1.2 т × 209.59 (ставка 2025) × 1.045 (norm)
    no2 = next(l for l in res.lines if l.code == "0301")
    assert no2.k_ind == k2025
    assert no2.rate == D("209.59")
    assert no2.amount == money(D("1.2") * D("209.59") * k2025)
    # СО сверх лимита: 0.2 × 2.42 × 1.045 × 100
    co_over = next(l for l in res.lines if l.code == "0337" and l.band == "over")
    assert co_over.amount == money(D("0.2") * co_over.rate * k2025 * D("100"))
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
    # состав и порядок листов — как в печатной форме бланка
    assert wb.sheetnames[0] == "стр.1"
    for name in ("Информация о суммах платы", "стр.2", "Авансовые платежи",
                 "Раздел 1 (выбросы)", "Раздел 4 (сбросы)",
                 "Разделы 5-9 (отходы)"):
        assert name in wb.sheetnames, name
    # лист сумм идёт между титулом и расчётом (стр. 3–4 образца)
    assert (wb.sheetnames.index("Информация о суммах платы")
            < wb.sheetnames.index("стр.2"))
    s2 = wb["стр.2"]
    # официальные коды строк бланка по столбцу A (сверено с принятой декларацией)
    codes = {c.value for c in s2["A"]}
    for want in ("010", "020", "021", "023", "024", "025", "100", "120"):
        assert want in codes, want
    # после каждого КБК — своя строка ОКТМО
    for want in ("031", "051", "071", "091", "111"):
        assert want in codes, want
    # детализация ПНГ и ТКО
    for want in ("061", "062", "063", "121", "122", "123"):
        assert want in codes, want
    # итоговая часть по бланку: вычет (130), корректировка (140), к внесению
    # (150), зачёт (160+166), авансы (170), итог (180), возврат (190)
    for want in ("130", "135", "140", "145", "150", "155", "160", "166",
                 "170", "175", "180", "185", "190", "195"):
        assert want in codes, want
    # КБК ТКО присутствует (строка 110)
    kbk = {c.value for c in s2["C"]}
    assert "048 1 12 01042 01 6000 120" in kbk


def test_title_all_17_fields(tmp_path):
    """Титул содержит поля 1–17 бланка; ОГРН и «сокращённого наименования»
    в бланке нет (проверено по принятой декларации: 0 вхождений)."""
    import openpyxl
    rep = DeclarationNVOS(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "d.xlsx"))
    s1 = wb["стр.1"]
    nums = {str(c.value) for c in s1["A"]}
    for want in [str(i) for i in range(1, 18)]:
        assert want in nums, f"нет поля {want} титульного листа"
    text = " ".join(str(c.value) for row in s1.iter_rows()
                    for c in row if c.value)
    assert "ОГРН" not in text
    assert "Сокращённое" not in text and "Сокращенное" not in text
    assert "страницах с приложением подтверждающих документов" in text


def test_summary_sheet(tmp_path):
    """Лист «Информация о суммах платы»: строка ИТОГО равна начисленной плате
    (вычетов в образце данных нет), есть блок подписи исполнителя."""
    import openpyxl
    from ecodoc.core.money import fmt_money
    rep = DeclarationNVOS(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "d.xlsx"))
    ws = wb["Информация о суммах платы"]
    pairs = [(a.value, b.value) for a, b in zip(ws["A"], ws["B"])]
    itogo = [b for a, b in pairs if a == "ИТОГО"]
    assert itogo and itogo[0] == fmt_money(rep.calc.total)
    text = " ".join(str(a) for a, _ in pairs if a)
    assert "Исполнитель" in text


def test_advances_sheet(tmp_path):
    """Лист «Информация об авансовых платежах»: строки 010–060, выбранный
    способ исчисления отмечается знаком X из extra['declaration']."""
    import openpyxl
    ctx = _ctx()
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    ctx.extra = {**extra, "declaration": {"advance_method": {"air": "pek"}}}
    rep = DeclarationNVOS(ctx)
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "d.xlsx"))
    ws = wb["Авансовые платежи"]
    rows = list(ws.iter_rows(values_only=True))
    codes = {r[1] for r in rows}
    for want in ("010", "020", "030", "040", "050", "060"):
        assert want in codes, want
    x_rows = [r for r in rows if r[2] == "X"]
    assert len(x_rows) == 1, "X должен стоять ровно у одного способа"
    assert "производственного экологического контроля" in str(x_rows[0][0])


def test_section1_blank_layout(tmp_path):
    """Раздел 1: 18 нумерованных граф, одна строка на вещество (полосы
    раскладываются в графы 6/7/8 и 15/16/17, а не плодят строки)."""
    import openpyxl
    from ecodoc.core.money import fmt_money, money
    rep = DeclarationNVOS(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "d.xlsx"))
    ws = wb["Раздел 1 (выбросы)"]
    rows = list(ws.iter_rows(values_only=True))
    num_row = next(r for r in rows if r[0] == "1" and r[17] == "18")
    assert list(num_row[:18]) == [str(i) for i in range(1, 19)]
    r1 = [ln for ln in rep.calc.lines if ln.section == "Р1"]
    uniq = {(ln.code, ln.name) for ln in r1}
    data_rows = [r for r in rows if isinstance(r[0], int)]
    assert len(data_rows) == len(uniq)
    # СО в образце данных имеет и «норматив», и «сверх»: обе полосы в одной
    # строке, гр.18 = сумма платы по всем полосам вещества
    co_lines = [ln for ln in r1 if ln.code == "0337"]
    assert len(co_lines) > 1, "образец должен содержать СО в двух полосах"
    co_row = next(r for r in data_rows if r[1] == co_lines[0].name)
    assert co_row[17] == fmt_money(sum(ln.amount for ln in co_lines))
    assert co_row[4] == float(sum(ln.mass for ln in co_lines))
    # итог листа = сумма платы Раздела 1
    total = money(sum(ln.amount for ln in r1))
    itogo = [r for r in rows if r[0] == "Итого по стационарным источникам:"]
    assert itogo and itogo[0][17] == fmt_money(total)


def test_calc_tko_rows_match_blank(tmp_path):
    """Строки 121–123 по бланку: 121 — плата за размещение ПРИНЯТЫХ ТКО
    (регоператор; в расчёте не участвует, по умолчанию 0), 122 — в пределах
    лимита, 123 — сверх лимита. Раньше суммы стояли со сдвигом на строку
    (121=лимит, 122=сверх)."""
    import openpyxl
    from ecodoc.core.models import (Organization, ReportContext, ReportPeriod,
                                    WasteFlow)
    from ecodoc.core.money import fmt_money
    ctx = ReportContext(
        organization=Organization(name="Т", inn="7801234564", oktmo="40324000"),
        period=ReportPeriod(year=2025),
        wastes=[WasteFlow(fkko_code="73310001724", name="ТКО", hazard_class=4,
                          placed_norm="3", placed_over="1")])
    rep = DeclarationNVOS(ctx)
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "d.xlsx"))
    ws = wb["стр.2"]
    rows = {str(r[0].value): (str(r[1].value), r[3].value)
            for r in ws.iter_rows(min_col=1, max_col=4)}
    norm = sum(l.amount for l in rep.calc.lines
               if l.section == "Р6" and l.band == "norm")
    over = sum(l.amount for l in rep.calc.lines
               if l.section == "Р6" and l.band == "over")
    assert norm > 0 and over > 0
    assert "принятых ТКО" in rows["121"][0]
    assert rows["121"][1] == fmt_money(0)
    assert "в пределах установленного лимита" in rows["122"][0]
    assert rows["122"][1] == fmt_money(norm)
    assert "сверх установленного лимита" in rows["123"][0]
    assert rows["123"][1] == fmt_money(over)
    # формула бланка 120 = 121 + 122 + 123
    assert rows["120"][1] == fmt_money(norm + over)


def test_calc_blank_labels(tmp_path):
    """Заголовки итоговой части — по бланку (сверено с принятой декларацией):
    020 «без учёта корректировки», 160 «в предыдущем отчётном периоде»,
    190 «для возврата и/или зачёта»; подстроки кварталов 171–175 стоят
    в графе кодов, как в бланке."""
    import openpyxl
    rep = DeclarationNVOS(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "d.xlsx"))
    ws = wb["стр.2"]
    label = {str(a.value): str(b.value) for a, b in zip(ws["A"], ws["B"])}
    assert "без учёта корректировки" in label["020"]
    assert "в предыдущем отчётном периоде" in label["160"]
    assert "для возврата и/или зачёта" in label["190"]
    assert "ПНГ в пределах НДВ, ТН" in label["061"]
    codes = [str(c.value) for c in ws["A"]]
    assert codes.count("1 квартал") == 5  # по одному под каждой из 171–175


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
