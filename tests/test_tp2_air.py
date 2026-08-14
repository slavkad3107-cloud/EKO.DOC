"""2-ТП (воздух) — пять разделов бланка, строки 101–109, графы А/1/Б/2-9 (Приказ № 661)."""
import openpyxl
from lxml import etree

from ecodoc.core import registry
from ecodoc.core.models import (Medium, Organization, Pollutant, ReportContext,
                                ReportPeriod)


def _ctx(extra=None):
    return ReportContext(
        organization=Organization(name="ООО Т", inn="7801234564", okpo="12345678",
                                  oktmo="40324000"),
        period=ReportPeriod(year=2025),
        pollutants=[
            Pollutant(name="Сера диоксид", code="0330", medium=Medium.AIR, mass_norm="0.8"),
            Pollutant(name="Азота диоксид", code="0301", medium=Medium.AIR, mass_norm="1.2"),
            Pollutant(name="Углерода оксид", code="0337", medium=Medium.AIR, mass_norm="3.5"),
            Pollutant(name="Взвешенные вещества", code="2902", medium=Medium.AIR, mass_norm="0.5"),
        ],
        extra=extra or {})


def test_tp2_air_sections(tmp_path):
    """Бланк состоит из ПЯТИ разделов — все листы обязаны присутствовать."""
    registry.load_all()
    rep = registry.get("2tp-air")(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "air.xlsx"))
    assert wb.sheetnames == ["Титул", "Раздел 1", "Раздел 2 (специфич.)",
                             "Раздел 3 (источники)", "Раздел 4 (мероприятия)",
                             "Раздел 5 (группы источн.)"]
    s1 = wb["Раздел 1"]
    # строки 101-109 в столбце A (данные с 5-й строки: шапка + номера граф)
    assert [s1["A" + str(r)].value for r in range(5, 14)] == \
        [101, 102, 103, 104, 105, 106, 107, 108, 109]
    # графа 7 (I): 101 Всего = 102 твёрдые + 103 газообразные; SO2/CO/NOx разнесены
    assert s1["I5"].value == 6.0            # 101 всего
    assert s1["I6"].value == 0.5            # 102 твёрдые (взвешенные)
    assert s1["I7"].value == 5.5            # 103 = 0.8+3.5+1.2
    assert s1["I8"].value == 0.8            # 104 SO2
    assert s1["I10"].value == 1.2           # 106 NOx


def test_tp2_air_sect1_columns_match_blank(tmp_path):
    """Состав/порядок граф Раздела 1 — по бланку: А, 1, Б, 2-9.

    В бланке есть код ЗВ (гр.1), «в т.ч. от организованных» (гр.3) и
    ПДВ/ВСВ (гр.8-9); выдуманной графы «отходит от источников» нет."""
    registry.load_all()
    rep = registry.get("2tp-air")(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "air.xlsx"))
    s1 = wb["Раздел 1"]
    # служебная строка номеров граф — как в бланке
    assert [s1[f"{c}4"].value for c in "ABCDEFGHIJK"] == \
        ["А", "1", "Б", "2", "3", "4", "5", "6", "7", "8", "9"]
    # коды ЗВ графы 1 — фиксированные по бланку
    assert [s1["B" + str(r)].value for r in range(5, 14)] == \
        ["0001", "0002", "0004", "0330", "0337", "0301", "0401", "0006", "0005"]
    joined = " ".join(str(s1[f"{c}3"].value) for c in "ABCDEFGHIJK").lower()
    assert "организованных" in joined       # гр.3 бланка
    assert "пдв" in joined and "всв" in joined   # гр.8-9 бланка
    assert "очист" in joined                # графы потока очистки
    assert "отходит" not in joined          # такой графы в бланке нет
    assert "лимит" not in joined and "сверх" not in joined  # не декларация
    # гр.3 без ввода — прочерк (программа не выдумывает ноль),
    # ПДВ/ВСВ вне строк 104-106 — «X», как в бланке
    assert s1["E5"].value == "-"            # 101, гр.3
    assert s1["J5"].value == "X" and s1["K5"].value == "X"   # 101, гр.8-9
    assert s1["J8"].value == "-"            # 104, гр.8 — нет данных, прочерк
    # предупреждение о незаполненной графе 3 — в validate()
    assert any("графа 3" in i.message for i in rep.validate())


def test_tp2_air_org_sources_and_limits(tmp_path):
    """Гр.3 и ПДВ/ВСВ берутся из extra и попадают в xlsx и XML."""
    registry.load_all()
    extra = {"tp2_air": {
        "cleaning": {"104": {"g7": "0.6"}},
        "limits": {"104": {"pdv": 1.5, "vsv": "-"}},
    }}
    rep = registry.get("2tp-air")(_ctx(extra))
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "air.xlsx"))
    s1 = wb["Раздел 1"]
    assert s1["E8"].value == 0.6            # 104, гр.3 из cleaning.g7
    assert s1["E7"].value == 0.6            # 103 = сумма заполненных 104-109
    assert s1["E5"].value == 0.6            # 101 = 102 + 103
    assert s1["J8"].value == 1.5            # 104, гр.8 ПДВ
    root = etree.parse(str(rep.render_xml(tmp_path / "air.xml"))).getroot()
    row104 = root.xpath("//Раздел1/Строка[@код='104']")[0]
    assert row104.findtext("ОтОрганизованных") == "0.600"
    assert row104.findtext("КодЗВ") == "0330"
    # гр.3 не может превышать гр.2 — ошибка валидации
    bad = registry.get("2tp-air")(_ctx({"tp2_air": {
        "cleaning": {"104": {"g7": "99"}}}}))
    assert any(i.level == "error" and "графа 3" in i.message
               for i in bad.validate())


def test_tp2_air_sections_4_5_content(tmp_path):
    """Разделы 4 и 5 — строки 401-405 и 501-505 по бланку, XML — все разделы."""
    registry.load_all()
    extra = {"tp2_air": {
        "measures": [{"production": "Котельная", "name": "Замена горелок",
                      "group": 3, "done": 1, "spent_year": 100.0,
                      "cut_expected": 0.5, "cut_fact": 0.4}],
        "groups": {"502": {"fuel": 0.7, "tech": 0.1}},
    }}
    rep = registry.get("2tp-air")(_ctx(extra))
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "air.xlsx"))
    s4 = wb["Раздел 4 (мероприятия)"]
    assert [s4["A" + str(r)].value for r in range(5, 10)] == \
        [401, 402, 403, 404, 405]           # пять строк всегда, как в бланке
    assert s4["C5"].value == "Замена горелок"
    assert s4["B6"].value is None           # пустая графа не выдумывается
    s5 = wb["Раздел 5 (группы источн.)"]
    assert [s5["A" + str(r)].value for r in range(5, 10)] == \
        [501, 502, 503, 504, 505]
    assert [s5["B" + str(r)].value for r in range(5, 10)] == \
        ["0002", "0330", "0337", "0301", "0007"]   # коды ЗВ по бланку
    assert s5["D6"].value == 0.7            # 502 гр.3 (сжигание топлива)
    assert s5["D5"].value == "-"            # без данных — прочерк
    root = etree.parse(str(rep.render_xml(tmp_path / "air.xml"))).getroot()
    assert [c.tag for c in root if c.tag.startswith("Раздел")] == \
        ["Раздел1", "Раздел2", "Раздел3", "Раздел4", "Раздел5"]
    assert root.xpath("//Раздел4/Мероприятие[@код='401']")
    assert root.xpath("//Раздел5/Строка[@код='502']")[0] \
        .findtext("ОтСжиганияТоплива") == "0.700"


def test_tp2_air_sum_groups_excluded(tmp_path):
    """Группы суммации (6xxx) не попадают в форму — их массы уже в веществах.

    Страховка от отката фильтра: включение группы «301+330» рядом с самими
    301 и 330 удвоило бы выброс в Разделах 1 и 2."""
    registry.load_all()
    ctx = _ctx()
    ctx.pollutants.append(Pollutant(
        name="Группа суммации: азота диоксид, серы диоксид", code="6204",
        medium=Medium.AIR, mass_norm="2.0"))
    rep = registry.get("2tp-air")(ctx)
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "air.xlsx"))
    s1 = wb["Раздел 1"]
    assert s1["I5"].value == 6.0            # 101 всего — без массы группы
    s2 = wb["Раздел 2 (специфич.)"]
    codes = [s2["A" + str(r)].value for r in range(4, s2.max_row + 1)]
    assert "6204" not in codes
    assert any("групп" in i.message for i in rep.validate())


def test_tp2_air_cleaning_control_ratio():
    """Контрольное соотношение Указаний: гр.7 = гр.4 − гр.5 + гр.2."""
    registry.load_all()
    # согласованные данные очистки: 0.8 = 0.3 − 0.2 + 0.7 — предупреждения нет
    ok = registry.get("2tp-air")(_ctx({"tp2_air": {"cleaning": {
        "104": {"g2": "0.7", "g3": "0.3", "g4": "0.2", "g6": "0.8"}}}}))
    assert not any("контрольное соотношение" in i.message for i in ok.validate())
    # рассогласованные (уловлено больше, чем поступило в форму) — предупреждение
    bad = registry.get("2tp-air")(_ctx({"tp2_air": {"cleaning": {
        "104": {"g3": "0.3", "g4": "0.2"}}}}))
    assert any("контрольное соотношение" in i.message and "104" in i.message
               for i in bad.validate())


def test_tp2_air_row_classification():
    """Коды без ведущего нуля и «именные» SO2/CO/NOx/керосин не уезжают в 109."""
    from ecodoc.reports.tp2_air.report import _air_row

    def mk(code, name):
        return Pollutant(name=name, code=code, medium=Medium.AIR, mass_norm="1")

    assert _air_row(mk("301", "Азота диоксид")) == 106      # без ведущего нуля
    assert _air_row(mk("330", "Сера диоксид")) == 104
    assert _air_row(mk("337", "Углерод оксид")) == 105
    assert _air_row(mk("3003", "Диоксид серы")) == 104      # старые коды ПДВ
    assert _air_row(mk("3332", "Оксид углерода")) == 105
    assert _air_row(mk("3004", "Диоксид азота")) == 106
    assert _air_row(mk("2732", "Керосин")) == 107           # код в справочнике
    assert _air_row(mk("9999", "Керосин ГОСТ")) == 107      # и по названию
    assert _air_row(mk("9998", "Алканы C12-C19")) == 107
    assert _air_row(mk("9997", "Уайт-спирит")) == 107
