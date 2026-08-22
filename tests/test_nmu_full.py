"""Тесты полноценного Плана мероприятий НМУ (приказы МПР № 651 и № 662).

Проверяем: форма строго по рекомендуемому образцу № 662 (ровно 9 пунктов,
дословные названия, строка номеров граф «1…6»), перечень п. 7 только по
контролируемым веществам (пп. 3–4 № 651), графа 6 НЕ считается по процентам
№ 651 (они — про вклады в приземные концентрации), запреты — дословно п. 9
№ 651, числа с запятой и 7 знаками, пометки «[требуется: …]» = gaps().
"""
from decimal import Decimal

from ecodoc.core.models import (Medium, NVOSObject, Organization, Pollutant,
                                ReportContext)
from ecodoc.development import nmu


def _ctx(**nmu_extra) -> ReportContext:
    ctx = ReportContext(
        organization=Organization(name="ООО «Завод»", inn="7801234564",
                                  ogrn="1027800000000",
                                  director_name="Иванов И.И."))
    ctx.objects.append(NVOSObject(code="40-0178-001234-П",
                                  name="Промплощадка № 1", category="II",
                                  address="СПб, ул. Заводская, 1"))
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


# контролируемое вещество по расчёту рассеивания — только NO2 (п. 3 № 651)
_CTRL = {"controlled_substances": ["0301"],
         "control_points": [{"name": "КТ-1 (граница жилой зоны)",
                             "code": "0301",
                             "sources": [{"number": "0001",
                                          "contribution_pct": 62}]}]}


def _text(path) -> str:
    from docx import Document
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return "\n".join(parts)


def _tables(path) -> list[list[list[str]]]:
    from docx import Document
    return [[[c.text for c in r.cells] for r in t.rows]
            for t in Document(str(path)).tables]


def test_sections_verbatim_662(tmp_path):
    """Форма по образцу № 662: грифы, ровно 9 пунктов с дословными названиями,
    п. 6 при специализированном прогнозе — со степенями НМУ, реквизиты
    действующих НПА; пп. 10–11 со сквозной нумерацией отсутствуют."""
    p = nmu.generate(_ctx(forecast_kind="специализированный", **_CTRL),
                     tmp_path / "n.docx")
    text = _text(p)
    assert "УТВЕРЖДЕНО" in text and "СОГЛАСОВАНО" in text
    for fragment in (
            nmu.P1, nmu.P2, nmu.P3, nmu.P4, nmu.P5, nmu.P6, nmu.P7,
            nmu.P8, nmu.P9,
            "(при наличии) индивидуального предпринимателя, осуществляющего "
            "хозяйственную и (или) иную деятельность",
            "4. Категория объекта, оказывающего негативное воздействие "
            "на окружающую среду: II.",
            "5. Код объекта, оказывающего негативное воздействие "
            "на окружающую среду: 40-0178-001234-П.",
            "(общий или специализированный): специализированный "
            "(степени НМУ: 1, 2, 3)."):
        assert fragment in text, fragment
    # за формой не продолжается нумерация образца
    assert "10. " not in text and "11. " not in text
    assert "Сводный расчёт" not in text
    assert "Пояснительная записка" in text
    # действующая база, а не отменённый № 811
    assert "от 26.11.2025 № 651" in text
    assert "от 28.11.2025 № 662" in text
    assert "№ 96-ФЗ" in text
    assert "№ 811" not in text
    # три степени НМУ при специализированном прогнозе, без «целевого %»
    for mode in (1, 2, 3):
        assert nmu.MODES[mode] in text
    assert "целевое снижение" not in text


def test_table_header_and_numbering_row(tmp_path):
    """Таблица п. 7: заголовки граф дословно из образца и строка «1…6»."""
    p = nmu.generate(_ctx(forecast_kind="общий", **_CTRL), tmp_path / "n.docx")
    t7 = [t for t in _tables(p) if t[0] == nmu.HEADER]
    assert t7, "таблица п. 7 с заголовками образца не найдена"
    assert t7[0][1] == ["1", "2", "3", "4", "5", "6"]
    assert nmu.HEADER[1].startswith("Номер источника (источников)")
    assert nmu.HEADER[4] == "Величины выбросов до мероприятия г/с"
    assert nmu.HEADER[5] == "Величины выбросов после мероприятия г/с"


def test_only_controlled_substances(tmp_path):
    """Пп. 3–4 № 651: в перечне только контролируемые вещества и источники
    с ними — CO и сварочный пост (Fe) в таблицу не попадают."""
    ctx = _ctx(forecast_kind="общий", **_CTRL)
    rows, typical = nmu.measure_rows(ctx, 0)
    assert typical and len(rows) == 1
    assert rows[0][1] == "0001" and rows[0][3] == "0301 Азота диоксид"
    text = _text(nmu.generate(ctx, tmp_path / "n.docx"))
    assert "Углерода оксид" not in text
    assert "Железа оксид" not in text and "0002" not in text
    # контрольная точка и вклад источника попадают в п. 8
    assert "КТ-1 (граница жилой зоны)" in text and "№0001 — 62 %" in text


def test_no_controlled_list_means_placeholder(tmp_path):
    """Без перечня контролируемых веществ таблица по всем источникам НЕ
    строится — только пометка «[требуется: …]» и та же строка в gaps()."""
    ctx = _ctx(forecast_kind="общий")
    assert nmu.measure_rows(ctx, 0) == ([], False)
    text = _text(nmu.generate(ctx, tmp_path / "n.docx"))
    assert f"[{nmu.CONTROLLED_REQUIRED}]" in text
    assert nmu.CONTROLLED_REQUIRED in nmu.gaps(ctx)
    assert "Азота диоксид" not in text
    assert "пп. 3–5 приказа № 651" in text


def test_after_not_computed_by_651_percent(tmp_path):
    """Графа 6 не вычисляется по нормативным процентам № 651: для типовых
    мероприятий — пометка технологу; 0,4250000 (0,5×0,85) нигде нет."""
    ctx = _ctx(forecast_kind="специализированный", **_CTRL)
    for mode in (1, 2, 3):
        rows, _ = nmu.measure_rows(ctx, mode)
        assert rows and all(r[5] == nmu.AFTER_REQUIRED for r in rows)
    text = _text(nmu.generate(ctx, tmp_path / "n.docx"))
    assert "0,5000000" in text                  # до, г/с
    assert "0,4250000" not in text and "0,3000000" not in text
    assert nmu.AFTER_REQUIRED in text
    assert any("графа 6" in g for g in nmu.gaps(ctx))
    # проценты № 651 в пояснительной записке — про вклады в концентрации
    assert "снижение вкладов в приземные концентрации" in text
    assert "величина выброса × процент" not in text


def test_user_measures_after_from_technologist(tmp_path):
    """Графа 6 берётся только из данных технолога по мероприятию:
    reduction_pct — снижение этим мероприятием, after — явная величина;
    мероприятие без того и другого — пометка."""
    ctx = _ctx(forecast_kind="специализированный", **_CTRL, measures=[
        {"mode": 1, "text": "Перевод котлов на природный газ",
         "reduction_pct": 25, "source": "0001"},
        {"mode": 2, "text": "Снижение нагрузки котлов до 50 %",
         "after": "0.21", "source": "0001"},
        {"mode": 3, "text": "Остановка резервного котла", "source": "0001"}])
    r1, _ = nmu.measure_rows(ctx, 1)
    r2, _ = nmu.measure_rows(ctx, 2)
    r3, _ = nmu.measure_rows(ctx, 3)
    assert r1[0][5] == "0,3750000"              # 0,5 × 0,75 — процент технолога
    assert r2[0][5] == "0,2100000"              # явная величина после
    assert r3[0][5] == nmu.AFTER_REQUIRED
    text = _text(nmu.generate(ctx, tmp_path / "n.docx"))
    assert "Перевод котлов на природный газ" in text
    assert "0,3750000" in text and "0,2100000" in text


def test_general_forecast_single_table(tmp_path):
    """При общем прогнозе — одна таблица, требование № 651 п. 10 —
    не менее 20 % снижения вкладов; степеней нет."""
    text = _text(nmu.generate(_ctx(forecast_kind="общий", **_CTRL),
                              tmp_path / "n.docx"))
    assert "не менее чем на 20 %" in text and "п. 10 требований" in text
    assert nmu.MODES[3] not in text


def test_regulated_targets():
    """Снижение вкладов по приказу № 651: прочие 20/15/20/40, для
    регулируемых видов деятельности (ТЭК/ЖКХ) — 15/5/10/20."""
    ctx = _ctx()
    assert [nmu.target_pct(ctx, m) for m in (0, 1, 2, 3)] == [20, 15, 20, 40]
    ctx_reg = _ctx(regulated=True)
    assert [nmu.target_pct(ctx_reg, m) for m in (0, 1, 2, 3)] == [15, 5, 10, 20]
    assert not hasattr(nmu, "efficiency_rows")   # сводного расчёта по % нет


def test_prohibitions_verbatim_651(tmp_path):
    """Запреты при НМУ — дословно п. 9 № 651: регламенты, ГПУ, залповые
    с оговоркой, ПНР и испытания; «продувки и чистки» из № 811 нет."""
    text = _text(nmu.generate(_ctx(**_CTRL), tmp_path / "n.docx"))
    assert ("соблюдаются технологические регламенты работ всех производств, "
            "оборудования и установок, а также запрещаются остановки "
            "газопылеулавливающих сооружений для выполнения профилактических "
            "работ, залповые выбросы вредных веществ в атмосферный воздух "
            "(кроме случаев, когда уже проводятся технологические операции "
            "по подготовке к проведению залповых выбросов), запрещается "
            "проведение пусконаладочных работ и испытаний оборудования") in text
    assert "продувк" not in text.lower()
    assert "с изменением технологического режима" not in text


def test_number_format_and_dots():
    """Числа — запятая и 7 знаков, как в принятых планах; ноль — «0»;
    точка в конце не дублируется."""
    assert nmu._fmt(Decimal("0.064")) == "0,0640000"
    assert nmu._fmt(Decimal("0")) == "0"
    assert nmu._fmt(None) == "—"
    assert nmu._fmt(Decimal("1.23456789")) == "1,2345679"
    assert nmu._dot("Иванов И.И.") == "Иванов И.И."
    assert nmu._dot("Иванов") == "Иванов."


def test_responsible_by_units(tmp_path):
    """Ответственные по структурным подразделениям (п. 8 № 651) — таблицей;
    строка по-старому тоже принимается; без всего — пометка в gaps()."""
    ctx = _ctx(**_CTRL, responsible=[
        {"unit": "Котельная", "position": "Начальник", "name": "Петров П.П."},
        {"unit": "Сварочный участок", "position": "Мастер",
         "name": "Сидоров С.С."}])
    text = _text(nmu.generate(ctx, tmp_path / "n.docx"))
    assert "Структурное подразделение" in text
    assert "Петров П.П." in text and "Сидоров С.С." in text
    assert nmu.responsible_list(_ctx(responsible="Главный инженер Козлов К.К.")) \
        == [{"unit": "", "position": "", "name": "Главный инженер Козлов К.К."}]
    empty = ReportContext()
    assert any("подразделениям" in g for g in nmu.gaps(empty))
    assert "И.И.." not in _text(nmu.generate(_ctx(**_CTRL), tmp_path / "d.docx"))


def test_sample_hint_in_gaps():
    """Пока в Формы/Разработка/НМУ нет образца — подсказка в gaps()."""
    gs = nmu.gaps(_ctx(**_CTRL))
    if not nmu._user_sample_exists():
        assert nmu.SAMPLE_HINT in gs
    else:
        assert nmu.SAMPLE_HINT not in gs


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
    assert nmu.CONTROLLED_REQUIRED in problems


def test_gaps_match_document_marks(tmp_path):
    """Каждая строка gaps() дословно печатается в Плане (раздел «Чего не
    хватает») — эколог видит список и в GUI, и в самом документе."""
    for ctx in (ReportContext(), _ctx(), _ctx(forecast_kind="общий", **_CTRL),
                _ctx(forecast_kind="специализированный",
                     controlled_substances=["0301"])):
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
