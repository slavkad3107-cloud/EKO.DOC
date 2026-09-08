"""Таблицы отходов ООС читаются из текста без ИИ (раунд 7)."""
from pathlib import Path

from ecodoc.parsers import oos_tables
from ecodoc.parsers.text_extract import ExtractedDoc

PAGE_OPER = """Таблица 3.6.2.1 - Количество ожидаемых отходов при эксплуатации
Вид отхода
Класс
опасно
сти
Количество
ожидаемых
отходов
Мероприятие по
обращению с
отходом
Наименование
Код по ФККО
м3
т
Мусор от офисных и бытовых помещений
организаций
несортированный
(исключая
крупногабаритный)
7 33 100 01 72 4
IV
121,38
19,98
Региональный
оператор
Мусор и смет уличный
7 31 200 01 72 4
IV
95,19
59,5
размещение
Всего IV класса опасности:
216,67
79,486
Пищевые отходы кухонь и организаций
общественного питания несортированные
7 36 100 01 30 5
V
14,23
5,69
Всего V класса опасности:
"""

PAGE_BUILD = """Таблица 3.6.1.4 - Количество отходов, ожидаемых при проведении строительных работ
Наименование
Код по ФККО
м3
т
Лом бетонных изделий, отходы бетона в кусковой форме
8 22 201 01 21 5
V
5,05
8,08
передача лицензированной организации
"""


def test_parse_operation_table():
    rows, stage = oos_tables.parse_page(PAGE_OPER)
    assert stage == "эксплуатация" and len(rows) == 3
    r = rows[0]
    assert r["fkko"] == "73310001724" and r["hazard_class"] == 4
    assert r["name"].startswith("Мусор от офисных и бытовых помещений")
    assert "Региональный" not in rows[1]["name"] and rows[1]["name"] == "Мусор и смет уличный"
    assert r["volume_m3"] == "121.38" and r["mass_t"] == "19.98" and r["density"] == "0.165"
    assert rows[2]["fkko"] == "73610001305" and rows[2]["hazard_class"] == 5


def test_extract_doc_two_stages_and_merge(tmp_path):
    doc = ExtractedDoc(Path("Раздел ПД № 8 ООС.pdf"), PAGE_BUILD + PAGE_OPER,
                       [PAGE_BUILD, PAGE_OPER], "pdf-text")
    rows = oos_tables.extract(doc)
    stages = {r["stage"] for r in rows}
    assert stages == {"строительство", "эксплуатация"} and len(rows) == 4
    assert rows[0]["page"] == 1 and rows[1]["page"] == 2
    assert oos_tables.is_project_doc(doc)
    # слияние в базу через тот же код, что и у ИИ-разбора
    from ecodoc.ai import analyzer
    from ecodoc.core.models import ReportContext
    ctx = ReportContext()
    rep = analyzer.ExtractionReport()
    analyzer._merge_oos_wastes(ctx, {"oos_wastes": rows}, "Раздел ПД № 8 ООС.pdf (лист 1)", rep)
    got = ctx.extra.get("oos_wastes") or []
    assert len(got) == 4
    build = [x for x in got if x.get("stage") == "строительство"]
    assert build and build[0]["fkko"] == "82220101215"


def test_merge_does_not_duplicate_spaced_codes():
    """Позиция с кодом «8 22 201 01 21 5» и строка ООС «82220101215» — один отход."""
    from ecodoc.ai import analyzer
    from ecodoc.core.models import ReportContext, WasteFlow
    ctx = ReportContext()
    ctx.wastes = [WasteFlow(fkko_code="8 22 201 01 21 5", name="Лом бетонных изделий", hazard_class=5)]
    rows = [{"stage": "строительство", "fkko": "82220101215", "name": "Лом бетонных изделий",
             "hazard_class": 5, "mass_t": "8.08", "volume_m3": "5.05", "density": "1.6"}]
    analyzer._merge_oos_wastes(ctx, {"oos_wastes": rows}, "ООС.pdf", analyzer.ExtractionReport())
    assert len(ctx.wastes) == 1
    rep = analyzer.ExtractionReport()
    analyzer._merge_wastes(ctx, {"wastes": [{"fkko": "82220101215", "name": "Лом бетонных изделий",
                                             "generated": "8.08"}]}, {}, "ж.pdf", rep)
    assert len(ctx.wastes) == 1 and str(ctx.wastes[0].generated) == "8.08"
