"""Региональный кадастр отходов СПб (Распоряжение № 87-р в ред. № 28-р):
расхождения с типовыми формами Комитета и принятым отчётом за 2024 г.
— район СПб в п. 2.2 Формы 1, формат ФККО и римский класс в Формах 2/3,
формулировки п. 1.14 и Формы 5, сетка шапки Формы 4."""
import openpyxl

from ecodoc.core import registry
from ecodoc.core.models import NVOSObject, WasteFlow
from ecodoc.reports.cadastre_spb.report import _district_name, _hazard
from tests.test_waste_forms import _ctx


def _render(ctx, tmp_path):
    registry.load_all()
    return openpyxl.load_workbook(
        registry.get("cadastre-spb")(ctx).render_print(tmp_path / "k.xlsx"))


def test_district_regex():
    # «Название район» / «р-н» в обеих позициях; слово из названия улицы — нет
    assert _district_name("СПб, Приморский район, Богатырский пр., 2") == "Приморский"
    assert _district_name("дорога на Металлострой, д.3 (Всеволожский р-н)") == "Всеволожский"
    assert _district_name("р-н Центральный, Невский пр., 1") == "Центральный"
    assert _district_name("СПб, Богатырский пр., 2") == ""
    assert _district_name("") == ""


def test_hazard_roman():
    assert _hazard(1) == "I" and _hazard(4) == "IV" and _hazard("5") == "V"
    assert _hazard("") == ""


def test_form1_district_from_address(tmp_path):
    """Район из адреса объекта печатается в п. 2.2 после адреса в скобках
    (так в принятом отчёте); в адресе с районом ничего не дублируется."""
    ctx = _ctx()
    ctx.objects = [NVOSObject(code="40-0278-004029-П", name="БЦ",
                              address="СПб, Невский пр., 1", oktmo="",
                              region_code="78")]
    ctx.extra["district"] = "Центральный район"
    f1 = _render(ctx, tmp_path)["Форма 1"]
    assert f1["D22"].value == "СПб, Невский пр., 1 (Центральный район)"
    ctx.extra.pop("district")
    ctx.objects[0].address = "СПб, Центральный район, Невский пр., 1"
    f1 = _render(ctx, tmp_path)["Форма 1"]
    assert f1["D22"].value == "СПб, Центральный район, Невский пр., 1"


def test_form1_district_from_oktmo_ref(tmp_path):
    """Без района в адресе район берётся из справочника oktmo_ref.json по ОКТМО
    (40324000 → «Приморский р-н» в value) — тестовый контекст именно такой."""
    ctx = _ctx()
    f1 = _render(ctx, tmp_path)["Форма 1"]
    assert f1["D22"].value == "СПб, Богатырский пр., 2 (Приморский район)"
    assert f1["C19"].value.endswith("в региональный кадастр")   # п. 1.14 дословно


def test_validate_error_without_district():
    """Район не определён → error (по п. 27 Порядка сведения без района
    считаются не представленными); для объекта в ЛО проверка не нужна."""
    registry.load_all()
    ctx = _ctx()
    ctx.objects = [NVOSObject(code="x", address="СПб, Невский пр., 1", oktmo="",
                              region_code="78")]
    errs = [i for i in registry.get("cadastre-spb")(ctx).validate()
            if i.level == "error"]
    assert any(i.field == "район" for i in errs)
    ctx.objects[0].region_code = "47"
    errs = [i for i in registry.get("cadastre-spb")(ctx).validate()
            if i.level == "error"]
    assert not any(i.field == "район" for i in errs)


def test_forms_2_3_fkko_format_and_roman_class(tmp_path):
    """Агрегация актов хранит код 11 цифрами — в печать уходит формат ФККО
    «7 33 100 01 72 4» и римский класс, как в Подсистеме и принятом отчёте."""
    ctx = _ctx()
    ctx.wastes = [WasteFlow(fkko_code="73310001724", name="Мусор офисный",
                            hazard_class=4, generated="1", transferred="1")]
    wb = _render(ctx, tmp_path)
    f3, f2 = wb["Форма 3"], wb["Форма 2"]
    assert f3["C13"].value == "7 33 100 01 72 4" and f3["D13"].value == "IV"
    assert f2["G8"].value == "7 33 100 01 72 4" and f2["H8"].value == "IV"


def test_form4_grid_matches_typical_form(tmp_path):
    """Сетка шапки Формы 4 как в Типовые_формы.xlsx: одиночные графы 5:8,
    группы в строке 5, подписи групп 6:8, номера граф в 9, данные с 10."""
    ctx = _ctx()
    ctx.extra["treatment_objects"] = [{"c2": "40-0278-000001-П", "c3": "СПб, Центральный район"}]
    f4 = _render(ctx, tmp_path)["Форма 4"]
    merged = {str(r) for r in f4.merged_cells.ranges}
    expect = {f"{c}5:{c}8" for c in "ABCDEFGHIJKLMSTUVW"}
    expect |= {"N5:P5", "Q5:R5", "X5:AA5"}
    expect |= {f"{c}6:{c}8" for c in ["N", "O", "P", "Q", "R", "X", "Y", "Z", "AA"]}
    assert expect <= merged
    assert [f4.cell(row=9, column=i).value for i in range(1, 28)] == list(range(1, 28))
    assert f4["A10"].value == 1 and f4["B10"].value == "40-0278-000001-П"
    assert f4["A8"].value is None or f4["A8"].value == "№, п/п"


def test_form5_wording_and_footnote(tmp_path):
    f5 = _render(_ctx(), tmp_path)["Форма 5"]
    assert "за отчетный период 2024 год." in f5["A15"].value
    assert f5["A18"].value == "УИН, либо штрих код2"
    assert f5["A34"].value == "___________________"
    assert f5["A35"].value == "2 Не заполняется"


def test_module_docstring_channels():
    import ecodoc.reports.cadastre_spb.report as m
    doc = m.__doc__
    assert "oopp.kpoos.gov.spb.ru" in doc and "kadastr@kpoos.gov.spb.ru" in doc
    assert "Дегтярный пер., д. 9" in doc
    assert "у СПб её нет" not in doc
