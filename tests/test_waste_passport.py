"""Паспорт отходов I–IV класса (Приказ №1026) — форма и наполнение."""
from ecodoc.core.models import ReportContext, WasteFlow
from ecodoc.development import waste_passport as wp


def _ctx():
    ctx = ReportContext()
    ctx.organization.name = "ИП Миних Елена Анатольевна"
    ctx.organization.inn = "780600114472"
    ctx.organization.director_name = "Миних Е.А."
    ctx.period.year = 2025
    ctx.wastes = [
        WasteFlow(fkko_code="47110101521", name="Лампы ртутные", hazard_class=1),
        WasteFlow(fkko_code="73310001724", name="Мусор от офисных помещений",
                  hazard_class=4),
        WasteFlow(fkko_code="73310002725", name="Отход V класса", hazard_class=5),
    ]
    return ctx


def test_passport_only_for_classes_1_4(tmp_path):
    """V класс паспорта не требует — на него документ не создаётся."""
    paths = wp.generate(_ctx(), tmp_path)
    assert len(paths) == 2
    names = {p.name for p in paths}
    assert "Паспорт_47110101521.docx" in names
    assert not any("73310002725" in n for n in names)


def test_passport_without_components_does_not_crash(tmp_path):
    """Регресс: при ПУСТОМ составе подставляется строка-плейсхолдер, а размер
    таблицы считался без неё → IndexError на генерации."""
    ctx = _ctx()
    ctx.wastes = [ctx.wastes[1]]              # отход без известного состава
    (path,) = wp.generate(ctx, tmp_path)
    from docx import Document
    rows = [r for t in Document(path).tables for r in t.rows]
    assert any("КХА" in c.text for r in rows for c in r.cells)


def test_passport_takes_components_from_ai_store(tmp_path):
    """Состав, извлечённый ИИ из загруженных паспортов (extra.waste_passports),
    попадает в таблицу «Сведения об отходах»."""
    ctx = _ctx()
    ctx.extra["waste_passports"] = [{
        "fkko": "47110101521", "name": "Лампы ртутные", "hazard_class": 1,
        "components": [{"name": "стекло", "percent": "92"},
                       {"name": "ртуть", "percent": "0.02"}]}]
    paths = wp.generate(ctx, tmp_path)
    lamp = next(p for p in paths if "47110101521" in p.name)
    from docx import Document
    text = "\n".join(c.text for t in Document(lamp).tables
                     for r in t.rows for c in r.cells)
    assert "стекло" in text and "92" in text
    assert "ртуть" in text
