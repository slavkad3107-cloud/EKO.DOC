"""Отчёт по ПЭК — структура по Приказу № 173 (титул + таблицы 1.1–6.2)."""
import openpyxl

from ecodoc.core import registry
from ecodoc.core.models import (NVOSObject, Organization, Pollutant, Medium,
                                ReportContext, ReportPeriod, WasteFlow)


def _ctx(year=2025):
    return ReportContext(
        organization=Organization(name="ООО Т", inn="7801234564", kpp="780101001"),
        period=ReportPeriod(year=year),
        objects=[NVOSObject(code="40-0178-001234-П", category="III", oktmo="40908000")],
        pollutants=[Pollutant(name="Азота диоксид", code="0301", medium=Medium.AIR,
                              mass_norm="1.0")],
        wastes=[WasteFlow(fkko_code="73310001724", name="ТКО", hazard_class=4,
                          generated="5", received="2", transferred="5",
                          transferred_util="3", transferred_burial="2",
                          accumulated_start_nakopl="1")],
        extra={"pek": {"program_number": "1-ПЭК", "lab": "ООО Лаб (RA.RU.21XX)"},
               "ppp": [{"name": "Шлак", "formed": "10", "used": "8"}]})


def _render(tmp_path):
    registry.load_all()
    rep = registry.get("pek")(_ctx())
    return openpyxl.load_workbook(rep.render_print(tmp_path / "pek.xlsx"))


def test_pek_six_sections(tmp_path):
    wb = _render(tmp_path)
    assert wb.sheetnames == ["Титул", "Раздел 1", "Раздел 2 (воздух)",
                             "Раздел 3 (вода)", "Раздел 4 (отходы)",
                             "Раздел 5 (ППП)", "Раздел 6 (искусств. грунты)"]
    # Раздел 5: заголовок таблицы 5.1, шапка, строка нумерации граф, данные
    assert wb["Раздел 5 (ППП)"]["B6"].value == "Шлак"


def test_pek_all_20_tables_present(tmp_path):
    """Форма № 173 — 20 пронумерованных таблиц; незаполненные печатаются
    с шапкой и прочерками, а не пропускаются."""
    wb = _render(tmp_path)
    text = " || ".join(str(c.value) for ws in wb.worksheets
                       for row in ws.iter_rows() for c in row
                       if c.value is not None)
    for num in ("1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6",
                "3.1", "3.2", "3.3", "3.4", "4.1", "4.2", "4.3",
                "5.1", "5.2", "6.1", "6.2"):
        assert f"Таблица {num}." in text, f"нет таблицы {num}"


def test_pek_table_42_21_graf(tmp_path):
    """Таблица 4.2 — 21 графа по № 173: разбивка «наличие» на хранение и
    накопление, «получено от других лиц», «передано» по пяти целям."""
    wb = _render(tmp_path)
    ws = wb["Раздел 4 (отходы)"]
    # строка нумерации граф «1..21» — маркер таблицы 4.2
    num_row = next(r for r in range(1, ws.max_row + 1)
                   if ws.cell(row=r, column=1).value == 1
                   and ws.cell(row=r, column=21).value == 21)
    row = [ws.cell(row=num_row + 1, column=c).value for c in range(1, 22)]
    assert row[0] == 1                    # N строки
    assert row[1] == "ТКО"                # гр.2 наименование — раньше был ФККО
    assert row[2] == "73310001724"        # гр.3 код по ФККО
    assert row[5] == 1.0                  # гр.6 накопление на начало года
    assert row[7] == 2.0                  # гр.8 получено от других лиц
    assert row[10] == 5.0                 # гр.11 передано всего
    assert row[12] == 3.0                 # гр.13 передано для утилизации
    assert row[15] == 2.0                 # гр.16 передано для захоронения


def test_pek_empty_tables_have_headers_and_dashes(tmp_path):
    """Таблицы без данных (очистные сооружения 3.4 — 17 граф, мониторинг
    ОРО 4.1) присутствуют: шапка + строка нумерации + строка прочерков."""
    wb = _render(tmp_path)
    ws = wb["Раздел 3 (вода)"]
    num_row = next(r for r in range(1, ws.max_row + 1)
                   if ws.cell(row=r, column=1).value == 1
                   and ws.cell(row=r, column=17).value == 17)
    assert ws.cell(row=num_row + 1, column=1).value == "-"
    ws4 = wb["Раздел 4 (отходы)"]
    assert any("мониторинга" in str(c.value) for row in ws4.iter_rows()
               for c in row if c.value)


def test_pek_section1_has_inn_ogrn(tmp_path):
    """Таблица 1.1 — реквизитник формы: ИНН и код объекта попадают в
    раздел 1 (раньше ИНН печатался только на самодельном титуле)."""
    wb = _render(tmp_path)
    ws = wb["Раздел 1"]
    cells = {str(c.value) for row in ws.iter_rows() for c in row if c.value}
    assert "7801234564" in cells                   # ИНН
    assert "40-0178-001234-П" in cells             # код объекта
    assert any("лаборатор" in v.lower() for v in cells)  # таблица 1.3


def test_pek_title_blocks(tmp_path):
    """Титул бланка: блоки подписей руководителя и исполнителя, «Экз. №»,
    строка «место нахождения, год» — без них лист нельзя подписать и сдать."""
    wb = _render(tmp_path)
    ws = wb["Титул"]
    vals = [str(c.value) for row in ws.iter_rows() for c in row
            if c.value not in (None, "")]
    text = " || ".join(vals)
    assert "Экз. №" in text
    assert "УТВЕРЖДАЮ" in text
    assert "Исполнитель, ответственный за подготовку отчёта" in text
    assert "(должность)" in text
    assert "место нахождения (город, населенный пункт)" in text


def test_pek_title_has_no_section1_requisites(tmp_path):
    """Страховка от отката к самодельному титулу-реквизитнику: программа
    ПЭК, лаборатория и срок представления — не титульные поля (это
    раздел 1 формы), на титуле их быть не должно."""
    wb = _render(tmp_path)
    ws = wb["Титул"]
    text = " || ".join(str(c.value) for row in ws.iter_rows() for c in row
                       if c.value)
    for wrong in ("Программа ПЭК", "Срок представления",
                  "аттестат аккредитации"):
        assert wrong not in text, f"на титуле лишнее поле: {wrong}"


def test_pek_xml_has_new_sections(tmp_path):
    registry.load_all()
    rep = registry.get("pek")(_ctx())
    xml = rep.render_xml(tmp_path / "pek.xml").read_text(encoding="utf-8")
    assert "ПобочныеПродуктыПроизводства" in xml
    assert "ИскусственныеГрунтыТКО" in xml
