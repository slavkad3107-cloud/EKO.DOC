"""Тесты полноценного Плана мероприятий НМУ (приказы МПР № 651 и № 662).

Проверяем: состав по рекомендуемому образцу № 662, наполнение таблиц из
extra['emission_sources'] и ctx.pollutants, расчёт «после» = до × (100−%)/100,
целевые проценты приказа № 651 (в т.ч. для регулируемых видов деятельности),
пометки «[требуется: …]» при пустых данных и совпадение их с gaps().
"""
from decimal import Decimal

from ecodoc.core.models import (Medium, NVOSObject, Organization, Pollutant,
                                ReportContext)
from ecodoc.development import nmu


def _ctx(**nmu_extra) -> ReportContext:
    ctx = ReportContext(
        organization=Organization(name="ООО «Завод»", inn="7801234564",
                                  ogrn="1027800000000",
                                  director_name="Иванов И.И."),
        objects=[NVOSObject(code="40-0178-001234-П", name="Промплощадка № 1",
                            category="II", address="СПб, ул. Заводская, 1")])
    ctx.extra["emission_sources"] = [
        {"number": "0001", "name": "Котельная", "kind": "организованный",
         "pollutants": [
             {"code": "0301", "name": "Азота диоксид", "g_s": "0.5",
              "t_year": "1.2"},
             {"code": "0337", "name": "Углерода оксид", "g_s": "1.0",
              "t_year": "3.0"}]},
        {"number": "0002", "name": "Сварочный пост", "kind": "организованный",
         "pollutants": [
             {"code": "0123", "name": "Железа оксид", "g_s": "0.02",
              "t_year": "0.05"}]},
    ]
    ctx.pollutants.append(Pollutant(name="Азота диоксид", code="0301",
                                    medium=Medium.AIR,
                                    mass_norm=Decimal("1.2")))
    if nmu_extra:
        ctx.extra["nmu"] = nmu_extra
    return ctx


def _text(path) -> str:
    from docx import Document
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return "\n".join(parts)


def test_sections_and_npa(tmp_path):
    """Состав по образцу № 662: грифы, пп. 1–9, реквизиты действующих НПА."""
    p = nmu.generate(_ctx(forecast_kind="специализированный"),
                     tmp_path / "n.docx")
    text = _text(p)
    assert "УТВЕРЖДЕНО" in text and "СОГЛАСОВАНО" in text
    for fragment in (
            "1. Наименование юридического лица",
            "2. Наименование объекта", "3. Сведения о фактическом месте",
            "4. Категория объекта: II", "5. Код объекта: 40-0178-001234-П",
            "6. Вид получаемого прогноза НМУ: специализированный",
            "7. Перечень мероприятий", "8. Результаты расчётов рассеивания",
            "9. Информация о методе контроля"):
        assert fragment in text, fragment
    # действующая база, а не отменённый № 811
    assert "от 26.11.2025 № 651" in text
    assert "от 28.11.2025 № 662" in text
    assert "№ 96-ФЗ" in text
    assert "№ 811" not in text
    # три степени опасности НМУ при специализированном прогнозе
    for mode in (1, 2, 3):
        assert nmu.MODES[mode] in text


def test_tables_filled_from_sources(tmp_path):
    """Таблицы п. 7 наполняются из extra['emission_sources']: номера
    источников, вещества, «до» г/с и «после» = до × (100−15)/100."""
    p = nmu.generate(_ctx(forecast_kind="специализированный"),
                     tmp_path / "n.docx")
    text = _text(p)
    assert "0001" in text and "0002" in text
    assert "Азота диоксид" in text and "Железа оксид" in text
    assert "0.5" in text            # до, г/с
    assert "0.425" in text          # после 1-й степени: 0.5 × 0.85
    assert "0.3" in text            # после 3-й степени: 0.5 × 0.60


def test_user_measures_override_typical(tmp_path):
    """Свои мероприятия из extra['nmu']['measures'] попадают в таблицу
    своей степени со своим процентом; привязка к источнику работает."""
    ctx = _ctx(forecast_kind="специализированный", measures=[
        {"mode": 1, "text": "Перевод котлов на природный газ",
         "reduction_pct": 25, "source": "0001"},
        {"mode": 3, "text": "Остановка сварочного поста",
         "reduction_pct": 100, "source": "0002"}])
    text = _text(nmu.generate(ctx, tmp_path / "n.docx"))
    assert "Перевод котлов на природный газ" in text
    assert "Остановка сварочного поста" in text
    assert "0.375" in text          # 0.5 × 0.75 — свой процент 25 %
    # для 2-й степени свои мероприятия не заданы → остаётся пометка о типовых
    assert nmu.MODES[2] in text


def test_general_forecast_single_table(tmp_path):
    """При общем прогнозе — один комплекс мероприятий (не менее 20 %),
    без разбивки по степеням."""
    text = _text(nmu.generate(_ctx(forecast_kind="общий"),
                              tmp_path / "n.docx"))
    assert nmu.MODES[0] in text
    assert "не менее 20 %" in text
    assert nmu.MODES[3] not in text


def test_regulated_targets():
    """Целевые проценты приказа № 651: прочие 20/15/20/40, для регулируемых
    видов деятельности (ТЭК/ЖКХ) — 15/5/10/20."""
    ctx = _ctx()
    assert [nmu.target_pct(ctx, m) for m in (0, 1, 2, 3)] == [20, 15, 20, 40]
    ctx_reg = _ctx(regulated=True)
    assert [nmu.target_pct(ctx_reg, m) for m in (0, 1, 2, 3)] == [15, 5, 10, 20]


def test_efficiency_summary(tmp_path):
    """Сводный расчёт по веществам: суммирование по источникам и
    масса × процент степени (1.5 г/с CO+NO2? — нет: по каждому веществу)."""
    ctx = _ctx(forecast_kind="специализированный")
    rows = nmu.efficiency_rows(ctx)
    # 3 вещества × 3 степени
    assert len(rows) == 9
    no2 = [r for r in rows if r[0] == "0301"]
    assert no2[0][2] == "0.5" and no2[0][3] == "1.2"     # до: г/с и т/год
    third = [r for r in no2 if "3-я" in r[4]][0]
    assert third[5] == "40" and third[6] == "0.3"        # 0.5 × 0.6
    assert third[7] == "0.72"                            # 1.2 × 0.6
    text = _text(nmu.generate(ctx, tmp_path / "n.docx"))
    assert "10. Сводный расчёт снижения выбросов" in text
    assert "0.72" in text


def test_empty_ctx_placeholders(tmp_path):
    """Пустая база: документ собирается, все дыры помечены «[требуется…»."""
    ctx = ReportContext()
    p = nmu.generate(ctx, tmp_path / "n.docx")
    text = _text(p)
    assert p.exists() and p.stat().st_size > 1000
    assert "[требуется" in text
    problems = nmu.gaps(ctx)
    assert any("источники выбросов" in g for g in problems)
    assert any("вид прогноза" in g for g in problems)
    assert any("рассеивания" in g for g in problems)


def test_gaps_match_document_marks(tmp_path):
    """Каждая строка gaps() дословно печатается в Плане (раздел «Чего не
    хватает») — эколог видит список и в GUI, и в самом документе."""
    for ctx in (ReportContext(), _ctx(), _ctx(forecast_kind="общий")):
        text = _text(nmu.generate(ctx, tmp_path / "g.docx"))
        for g in nmu.gaps(ctx):
            assert g in text, g


def test_no_measures_required_branch(tmp_path):
    """П. 5 требований № 662: превышений ПДК нет — план фиксирует отсутствие
    необходимости мероприятий, таблицы степеней не выводятся."""
    ctx = _ctx(no_measures_required=True)
    text = _text(nmu.generate(ctx, tmp_path / "n.docx"))
    assert "не требуется" in text
    assert "п. 5 требований" in text
    assert nmu.MODES[1] not in text
