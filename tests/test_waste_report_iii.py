"""Отчётность по отходам III кат./МСП — общие сведения + баланс масс."""
import openpyxl

from ecodoc.core import registry
from ecodoc.core.models import (NVOSObject, Organization, ReportContext,
                                ReportPeriod, WasteFlow)


def _ctx():
    return ReportContext(
        organization=Organization(name="ООО Т", inn="7801234564", ogrn="1157847008219",
                                  okpo="12345678", oktmo="40324000"),
        period=ReportPeriod(year=2025),
        objects=[NVOSObject(code="40-0178-001234-П", category="III", address="СПб",
                            oktmo="40908000")],
        wastes=[WasteFlow(fkko_code="73310001724", name="ТКО", hazard_class=4,
                          generated="5", transferred="5")])


def test_msp_general_and_movement(tmp_path):
    registry.load_all()
    rep = registry.get("waste-report-iii")(_ctx())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "msp.xlsx"))
    assert wb.sheetnames == ["Общие сведения", "Движение отходов", "Получатели"]
    # объект НВОС в общих сведениях (строка ищется по колонке, а не по номеру:
    # выше добавлена оговорка о правовом статусе документа)
    general = [str(c.value) for c in wb["Общие сведения"]["B"] if c.value]
    assert any("40-0178-001234-П" in v for v in general)
    # документ честно говорит, что отдельной федеральной формы нет
    left = " ".join(str(c.value) for c in wb["Общие сведения"]["A"] if c.value)
    assert "приказ Минприроды № 30 отменён" in left and "№ 173" in left
    # полный баланс: наличие на начало (раздельно хранение/накопление,
    # как графы 5/6 табл. 4.2 ПЭК) и на конец присутствуют
    heads = [wb["Движение отходов"][f"{c}1"].value for c in "ABCDEFGHIJKL"]
    assert "Нач. года (хран.), т" in heads
    assert "Нач. года (накопл.), т" in heads
    assert "Кон. года, т" in heads


def test_msp_xml_balance(tmp_path):
    registry.load_all()
    rep = registry.get("waste-report-iii")(_ctx())
    xml = rep.render_xml(tmp_path / "msp.xml").read_text(encoding="utf-8")
    assert "<НаличиеНачалоХранение>" in xml
    assert "<НаличиеНачалоНакопление>" in xml
    assert "<НаличиеКонец>" in xml
    assert "<ОбъектНВОС" in xml


def _ctx_nakopl():
    """Позиция с остатками на начало года в ОБОИХ режимах: хранение 2 т +
    накопление 3 т + образовано 10 т = передано 10 т + на конец 5 т —
    данные внутренне согласованы, предупреждения баланса быть не должно."""
    ctx = _ctx()
    ctx.wastes = [WasteFlow(fkko_code="73310001724", name="ТКО", hazard_class=4,
                            accumulated_start="2", accumulated_start_nakopl="3",
                            generated="10", transferred="10",
                            accumulated_end="5")]
    return ctx


def test_balance_counts_nakopl_start(tmp_path):
    # страховка расхождения №3: без учёта накопления на начало года
    # validate() давал ложное предупреждение на согласованных данных
    registry.load_all()
    rep = registry.get("waste-report-iii")(_ctx_nakopl())
    issues = [i for i in rep.validate() if i.field.startswith("баланс")]
    assert issues == []


def test_balance_still_warns_on_mismatch(tmp_path):
    # реальное расхождение баланса по-прежнему ловится (фикс не «заглушил» проверку)
    registry.load_all()
    ctx = _ctx_nakopl()
    ctx.wastes[0].accumulated_end = "7"  # баланс даёт 5, а заявлено 7
    rep = registry.get("waste-report-iii")(ctx)
    issues = [i for i in rep.validate() if i.field.startswith("баланс")]
    assert len(issues) == 1


def test_xlsx_and_xml_split_start_columns(tmp_path):
    # хранение и накопление на начало года печатаются раздельно и с верными
    # значениями — и в xlsx (графы D/E), и в xml
    registry.load_all()
    rep = registry.get("waste-report-iii")(_ctx_nakopl())
    wb = openpyxl.load_workbook(rep.render_print(tmp_path / "n.xlsx"))
    ws = wb["Движение отходов"]
    assert ws["D2"].value == 2 and ws["E2"].value == 3
    xml = rep.render_xml(tmp_path / "n.xml").read_text(encoding="utf-8")
    assert "<НаличиеНачалоХранение>2</НаличиеНачалоХранение>" in xml
    assert "<НаличиеНачалоНакопление>3</НаличиеНачалоНакопление>" in xml
