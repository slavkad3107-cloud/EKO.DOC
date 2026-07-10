"""Тесты официальных бланков: журнал учёта отходов (Приказ №1028) и
региональный кадастр отходов СПб (Формы 1–5)."""
import openpyxl

from ecodoc.core import registry
from ecodoc.core.models import (NVOSObject, Organization, ReportContext,
                                ReportPeriod, WasteFlow)


def _ctx():
    return ReportContext(
        organization=Organization(
            name="ООО «Ромашка»", short_name="ООО «Ромашка»", inn="7801234564",
            ogrn="1157847008219", okpo="13884779", okved="68.20.2",
            address="197348, СПб, Богатырский пр., д.2", oktmo="40324000",
            director_name="Иванов И.И.", phone="8(812)000", email="a@b.ru"),
        period=ReportPeriod(year=2024),
        objects=[NVOSObject(code="40-0278-004029-П", name="БЦ Эталон",
                            address="СПб, Богатырский пр., 2", oktmo="40324000",
                            region_code="78")],
        wastes=[
            WasteFlow(fkko_code="47110101521", name="Лампы ртутные", hazard_class=1,
                      generated="0.115", transferred="0.115",
                      origin="Использование по назначению",
                      aggregate_state="Изделия", composition="Стекло 92%"),
            WasteFlow(fkko_code="73310001724", name="Мусор офисный", hazard_class=4,
                      generated="42.6", transferred="42.6"),
        ],
        extra={
            "waste_receivers": [
                {"fkko": "47110101521", "receiver": 'ФГУП "ФЭО"',
                 "contract": "№52274", "contract_term": "по 31.12.2024",
                 "license": "ЛО 020"}],
            "accumulation_sites": [
                {"description": "Контейнерная площадка", "capacity_t": 0.35,
                 "capacity_m3": 2.52, "waste_name": "Мусор", "fkko": "73310001724",
                 "hazard_class": 4}],
        },
    )


def test_waste_movement_1028_sheets(tmp_path):
    registry.load_all()
    rep = registry.get("waste-movement")(_ctx())
    assert rep.has_xml is False
    p = rep.render_print(tmp_path / "j.xlsx")
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Титул", "Приложение 1", "Приложение 2 (год)",
                             "Приложение 3 (год)", "Приложение 4 (год)"]
    # Приложение 1 — состав образующихся отходов
    a1 = wb["Приложение 1"]
    assert a1["C4"].value == "Код ФККО"
    assert a1["B6"].value == "Лампы ртутные"
    assert a1["E6"].value == "Использование по назначению"
    # Приложение 2 — движение, образовано в графе 6
    a2 = wb["Приложение 2 (год)"]
    assert a2["G8"].value == 0.115
    # Приложение 3 — получатель переданных отходов
    a3 = wb["Приложение 3 (год)"]
    assert a3["K8"].value == 'ФГУП "ФЭО"'


def test_waste_movement_no_xml(tmp_path):
    registry.load_all()
    rep = registry.get("waste-movement")(_ctx())
    try:
        rep.render_xml(tmp_path / "j.xml")
        assert False, "должно бросить NotImplementedError"
    except NotImplementedError:
        pass


def test_cadastre_spb_forms(tmp_path):
    registry.load_all()
    rep = registry.get("cadastre-spb")(_ctx())
    assert rep.has_xml is False
    assert not [i for i in rep.validate() if i.level == "error"]
    p = rep.render_print(tmp_path / "k.xlsx")
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Форма 1", "Форма 2", "Форма 3", "Форма 4", "Форма 5"]
    assert wb["Форма 1"]["D6"].value == "7801234564"     # ИНН
    assert wb["Форма 2"]["C8"].value == "Контейнерная площадка"
    f3 = wb["Форма 3"]
    assert f3["B13"].value == "Лампы ртутные"             # наименование в графе 2
    assert f3["C13"].value == "47110101521"              # код в графе 3
    # ТКО (73...) уходит региональному оператору — графа Q
    assert f3["Q14"].value == 42.6
    assert wb["Форма 5"]["C27"].value == "ООО «Ромашка»"


def test_tp2_waste_datapacket_xml(tmp_path):
    registry.load_all()
    rep = registry.get("2tp-waste")(_ctx())
    p = rep.render_xml(tmp_path / "2tp.xml")
    xml = p.read_text(encoding="utf-8")
    # реальный конверт Модуля природопользователя
    assert "<DATA_PACKET_NI" in xml and 'DocType="3"' in xml
    assert "<ORG_INFO>" in xml and "<EMISS_OBJECT>" in xml
    assert "<RPT_2TP_WASTE>" in xml and "<RPT_2TP_WASTE_FACT>" in xml
    assert "<WST_CODE>73310001724</WST_CODE>" in xml
    # масса IV класса — с точностью 1 знак (Указания к форме)
    assert "<TP2_FORMING>42.6</TP2_FORMING>" in xml
    assert "<CHECKSUM>" in xml


def test_tp2_waste_print_pages(tmp_path):
    registry.load_all()
    rep = registry.get("2tp-waste")(_ctx())
    p = rep.render_print(tmp_path / "2tp.xlsx")
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["стр.1", "стр.2", "стр.3"]
    assert wb["стр.1"]["A17"].value == "0609013"       # код формы по ОКУД
    assert wb["стр.2"]["B6"].value == "ВСЕГО"           # агрегатная строка
    # графы А,Б,В,Г,1..18
    assert wb["стр.2"]["A5"].value == "А"
    assert wb["стр.2"]["V5"].value == "18"
