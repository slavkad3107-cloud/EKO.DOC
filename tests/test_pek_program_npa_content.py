"""Программа ПЭК: содержание разделов по п. 3–9 Требований (приложение 1
к приказу № 109) — 8 расхождений ревью 21.08.2026 по эталону ТХС.

Каждый тест закрывает одну находку: [1] реквизиты и уполномоченный орган,
[2] источник × вещество и сроки инвентаризации, [3] блоки раздела 3,
[4] численность/права/приказ, [5] область аккредитации, [6] методики и
нормативы в планах-графиках, [7] ОРО, [8] дата в грифе утверждения.
"""
from ecodoc.development import pek_program
from tests.test_pek_program_full import _docx_text, _rich_ctx


def _full_ctx():
    """Все новые ключи extra.pek заполнены — пробелов по ним быть не должно."""
    ctx = _rich_ctx()
    ctx.organization.okved = "41.2"
    ctx.objects[0].region_code = "78"
    ctx.extra["emission_sources"][0]["pollutants"][0].update(
        {"g_s": "0.0655849", "t_year": "1.5"})
    ctx.extra["water"]["discharge"][0].update({
        "sampling_point": "колодец КК-1",
        "pollutants": [{"code": "132", "name": "Взвешенные вещества",
                        "mass": "0.2"}]})
    ctx.extra["pek"].update({
        "supervision_level": "региональный",
        "air_inventory_next": "при изменении технологии",
        "air_inventory_revision": "при расхождении с фактом более 10 %",
        "treatment_facilities": "ЛОС «Векса-5» производительностью 5 л/с",
        "water_scheme": "водоснабжение от сетей ГУП «Водоканал»",
        "flow_meters": [{"name": "расходомер ВЗЛЁТ ЭР", "error": "±1,5 %",
                         "verification": "свид. № 123 до 01.06.2027"}],
        "water_accounting_terms": "ежемесячно, итоги за квартал и год",
        "nds": {"Взвешенные вещества": "10 мг/дм³"},
        "methods": {"0301": "ПНД Ф 13.1.8-97", "2704": "методика расчёта АТП",
                    "Взвешенные вещества": "ПНД Ф 14.1:2:4.254-09"},
        "staff_count": 1,
        "order_no": "15-ОД", "order_date": "10.01.2026",
        "rights_duties": ["обязан вести ПЭК", "вправе требовать документы"],
        "oro_none": True,
    })
    ctx.extra["pek"]["labs"][0]["scope"] = "реестр ФСА RA.RU.21ЭК01"
    return ctx


def test_general_requisites_table_and_authority(tmp_path):
    """[1] Раздел 1: ОПФ, ОКВЭД, уровень надзора и КОНКРЕТНЫЙ орган по региону."""
    ctx = _full_ctx()
    text = _docx_text(pek_program.generate(ctx, tmp_path / "p.docx"))
    assert "Общество с ограниченной ответственностью" in text   # ОПФ из «ООО»
    assert "41.2" in text
    assert "Региональный" in text
    assert "Комитет по природопользованию" in text
    assert not any("уполномоченного органа" in g for g in pek_program.gaps(ctx))
    # федеральный надзор → территориальный орган Росприроднадзора
    ctx.extra["pek"]["supervision_level"] = "федеральный"
    assert "Росприроднадзора" in pek_program.authority(ctx)
    # регион вне справочника — не выдумываем, просим
    ctx.objects[0].region_code = "66"
    assert pek_program.authority(ctx) == ""
    assert any("уполномоченного органа" in g for g in pek_program.gaps(ctx))
    # уровень надзора машина не угадывает
    ctx2 = _rich_ctx()
    assert any("уровень государственного" in g for g in pek_program.gaps(ctx2))


def test_air_inventory_per_source_and_terms(tmp_path):
    """[2] Раздел 2: источник × вещество с г/с, т/год, маркерное, сроки."""
    ctx = _full_ctx()
    text = _docx_text(pek_program.generate(ctx, tmp_path / "p.docx"))
    assert "по каждому источнику" in text
    assert "0001 Труба котельной" in text and "6001 Стоянка техники" in text
    assert "0.0655849" in text                      # г/с из инвентаризации
    assert "Суммарные выбросы по объекту в целом" in text
    assert "Сроки проведения инвентаризации выбросов" in text
    assert "при расхождении с фактом более 10 %" in text
    assert not any("сроки проведения инвентаризации выбросов" in g.lower()
                   for g in pek_program.gaps(ctx))
    assert any("сроки проведения инвентаризации" in g
               for g in pek_program.gaps(_rich_ctx()))


def test_water_inventory_blocks(tmp_path):
    """[3] Раздел 3: вещество × выпуск, очистные, схемы, приборы, сроки."""
    ctx = _full_ctx()
    text = _docx_text(pek_program.generate(ctx, tmp_path / "p.docx"))
    assert "по каждому выпуску" in text
    assert "ЛОС «Векса-5»" in text
    assert "ГУП «Водоканал»" in text
    assert "расходомер ВЗЛЁТ ЭР" in text and "±1,5 %" in text
    assert "свид. № 123 до 01.06.2027" in text
    assert "ежемесячно, итоги за квартал и год" in text
    water_gaps = [g for g in pek_program.gaps(ctx) if "п. 5 Требований" in g]
    assert water_gaps == [], water_gaps
    poor = [g for g in pek_program.gaps(_rich_ctx()) if "п. 5 Требований" in g]
    assert any("очистных" in g for g in poor)
    assert any("погрешность" in g for g in poor)
    assert any("ПО КАЖДОМУ ВЫПУСКУ" in g for g in poor)


def test_staff_count_rights_and_order(tmp_path):
    """[4] Раздел 7: численность, права и обязанности, приказ о назначении."""
    ctx = _full_ctx()
    text = _docx_text(pek_program.generate(ctx, tmp_path / "p.docx"))
    assert "Численность, чел." in text
    assert "приказом № 15-ОД от 10.01.2026" in text
    assert "вправе требовать документы" in text
    assert "типовой перечень" not in text
    # без rights_duties — типовой текст по ст. 67 с явной пометкой и gap
    ctx2 = _rich_ctx()
    text2 = _docx_text(pek_program.generate(ctx2, tmp_path / "p2.docx"))
    assert "типовой перечень по ст. 67" in text2
    assert any("ТИПОВЫЕ" in g for g in pek_program.gaps(ctx2))
    assert any("численность" in g for g in pek_program.gaps(ctx2))


def test_lab_scope_column(tmp_path):
    """[5] Раздел 8: графа «Область аккредитации»."""
    ctx = _full_ctx()
    text = _docx_text(pek_program.generate(ctx, tmp_path / "p.docx"))
    assert "Область аккредитации" in text
    assert "реестр ФСА RA.RU.21ЭК01" in text
    assert not any("область аккредитации" in g for g in pek_program.gaps(ctx))
    ctx2 = _rich_ctx()
    text2 = _docx_text(pek_program.generate(ctx2, tmp_path / "p2.docx"))
    assert "[требуется: область аккредитации]" in text2
    assert any("область аккредитации" in g for g in pek_program.gaps(ctx2))


def test_plan_methodology_and_norm_columns(tmp_path):
    """[6] 9.1/9.2: методика измерений, норматив выброса, НДС, место отбора."""
    ctx = _full_ctx()
    text = _docx_text(pek_program.generate(ctx, tmp_path / "p.docx"))
    assert "Методика (метод) измерений" in text
    assert "Норматив (мощность) выброса" in text
    assert "ПНД Ф 13.1.8-97" in text
    assert "ПНД Ф 14.1:2:4.254-09" in text
    assert "колодец КК-1" in text                   # место отбора отдельно
    assert "10 мг/дм³" in text                      # НДС
    air = pek_program.plan_air(ctx)
    no2 = next(r for r in air if r["code"] == "0301")
    assert no2["norm"] == "0.0655849 г/с; 1.5 т/год"
    assert no2["methodology"] == "ПНД Ф 13.1.8-97"
    # бензин у стоянки без НДВ → gap по п. 9.1.1 с названием вещества
    assert any("без НДВ" in g and "Бензин" in g for g in pek_program.gaps(ctx))
    # без методик — просим, не выдумываем
    ctx2 = _rich_ctx()
    rows = pek_program.plan_air(ctx2)
    assert all(r["methodology"].startswith("[требуется") for r in rows)
    assert any("методики (методы)" in g for g in pek_program.gaps(ctx2))


def test_oro_none_and_inventory_columns(tmp_path):
    """[7] Раздел 4: явное отсутствие ОРО / инвентаризация ОРО и сроки."""
    ctx = _full_ctx()
    text = _docx_text(pek_program.generate(ctx, tmp_path / "p.docx"))
    assert "Объекты размещения отходов на объекте отсутствуют" in text
    assert not any("ГРОРО" in g for g in pek_program.gaps(ctx))
    ctx.extra["pek"]["oro_none"] = False
    ctx.extra["pek"]["oro"] = [{"name": "Полигон", "groro": "78-00001-З-00592"}]
    text = _docx_text(pek_program.generate(ctx, tmp_path / "p2.docx"))
    assert "Дата инвентаризации" in text and "Срок следующей инвентаризации" in text
    assert any("инвентаризации ОРО «Полигон»" in g for g in pek_program.gaps(ctx))
    ctx.extra["pek"]["oro"][0].update({"inventory_date": "01.06.2025",
                                       "inventory_next": "01.06.2030"})
    assert not any("инвентаризации ОРО" in g for g in pek_program.gaps(ctx))


def test_approval_stamp_uses_program_date(tmp_path):
    """[8] Гриф «УТВЕРЖДАЮ» — дата утверждения целиком, не отчётный год."""
    ctx = _rich_ctx()                   # program_date=01.02.2026
    ctx.period.year = 2025
    assert pek_program.approval_stamp_date(ctx) == "«01» февраля 2026 г."
    text = _docx_text(pek_program.generate(ctx, tmp_path / "p.docx"))
    assert "«01» февраля 2026 г." in text
    assert "2025 г." not in text
    ctx.extra["pek"]["program_date"] = ""
    assert pek_program.approval_stamp_date(ctx).startswith("«___»")


def test_gaps_equal_text_marks_full_ctx(tmp_path):
    """Инвариант gaps()==пометки в тексте держится и на полном контексте."""
    ctx = _full_ctx()
    text = _docx_text(pek_program.generate(ctx, tmp_path / "g.docx"))
    for g in pek_program.gaps(ctx):
        assert f"[{g}]" in text, g
