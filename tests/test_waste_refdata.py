"""core/waste_refdata: нормализация состава (мг/кг → %, сумма 100, «прочие»,
отбраковка), отбор протокола состава (не воздух/вода), происхождение по
ФККО/образцу, адрес площадки, справочник Wi (приложение № 4 к пр. № 158)."""
from ecodoc.core import waste_refdata as R
from ecodoc.core.models import NVOSObject, ReportContext


# ── единицы и конверсия ──
def test_parse_value_and_units():
    assert R.parse_value("21,14") == 21.14 and R.parse_value("<0,03") == 0.0
    assert R.parse_value("31,500 ± 0,032") == 31.5
    assert R.parse_value("") is None and R.parse_value(None) is None
    assert R.detect_unit([{"name": "a", "percent": "50", "unit": "мг/кг"}]) == "мг/кг"
    assert R.detect_unit([{"name": "a", "percent": "500"}]) == "мг/кг"   # >150 без ед.
    assert R.detect_unit([{"name": "a", "percent": "99"}]) == "%"
    assert R.detect_unit([{"name": "a", "percent": "0.6", "unit": "доли"}]) == "доли"


def test_normalize_mg_per_kg_to_percent_sorted_and_100():
    comps, note = R.normalize_components([
        {"name": "Картон", "percent": "169000"},
        {"name": "Бумага", "value": "531000"},
        {"name": "Полиэтилен", "percent": "300000"}])
    assert [c["name"] for c in comps] == ["Бумага", "Полиэтилен", "Картон"]
    assert [c["percent"] for c in comps] == ["53.10", "30.00", "16.90"]
    assert R.components_total(comps) == 100.0
    assert "мг/кг" in note


def test_normalize_g_per_kg_and_fractions():
    comps, _ = R.normalize_components([{"name": "a", "percent": "700", "unit": "г/кг"},
                                       {"name": "b", "percent": "300", "unit": "г/кг"}])
    assert [c["percent"] for c in comps] == ["70.00", "30.00"]
    comps, _ = R.normalize_components([{"name": "a", "percent": "0.75", "unit": "доли"},
                                       {"name": "b", "percent": "0.25", "unit": "доли"}])
    assert [c["percent"] for c in comps] == ["75.00", "25.00"]


def test_normalize_99_101_scaled_otherwise_as_is_with_incomplete_note():
    """Замечание эколога 08.09.2026: 99–101 % → к 100; иначе строки как есть,
    пометка «состав распознан не полностью», никаких «Прочих» (только явно,
    fill_other=True); синтетические «Прочие» прошлых версий вычищаются."""
    comps, note = R.normalize_components([{"name": "a", "percent": "60"},
                                          {"name": "b", "percent": "40.6"}])   # 100.6
    assert [c["percent"] for c in comps] == ["59.64", "40.36"]
    assert R.components_total(comps) == 100.0 and "приведена к 100" in note
    assert not R.is_incomplete_note(note)
    comps, note = R.normalize_components([{"name": "a", "percent": "60"},
                                          {"name": "b", "percent": "42"}])     # 102
    assert [c["percent"] for c in comps] == ["60.00", "42.00"]
    assert R.is_incomplete_note(note) and "102.0 %" in note and "больше 100" in note
    comps, note = R.normalize_components([{"name": "a", "percent": "60"},
                                          {"name": "b", "percent": "20"}])     # 80
    assert [c["name"] for c in comps] == ["a", "b"] and R.components_total(comps) == 80.0
    assert note.startswith("состав распознан не полностью: 80.0 % — проверьте протокол/ООС")
    comps, note = R.normalize_components([{"name": "a", "percent": "60"},
                                          {"name": "b", "percent": "20"}], fill_other=True)
    assert comps[-1]["name"].startswith("Прочие") and comps[-1]["percent"] == "20.00"
    comps, note = R.normalize_components([{"name": "a", "percent": "80"},
                                          {"name": "b", "percent": "40"}],
                                         source="протокола № 5")
    assert [c["percent"] for c in comps] == ["80.00", "40.00"]
    assert "120.0 %" in note and "№ 5" in note
    # синтетическая строка прошлой версии вычищается, «Прочее» лаборатории — нет
    comps, note = R.normalize_components([
        {"name": "Прочие компоненты (неидентифицированные)", "percent": "38.6"},
        {"name": "Картон", "percent": "16.9"},
        {"name": "Прочее (неклассифицируемые материалы)", "percent": "44.5"}])
    assert [c["name"] for c in comps] == ["Прочее (неклассифицируемые материалы)", "Картон"]
    assert R.is_incomplete_note(note) and "61.4 %" in note
    assert R.normalize_components([], source="x") == ([], "")
    comps, note = R.normalize_components([{"name": "a", "percent": ""}])
    assert comps == [] and "нет числового содержания" in note


def test_fmt_pct_comma():
    assert R.fmt_pct(21.1) == "21,10" and R.fmt_pct("53.10") == "53,10"
    assert R.fmt_pct("") == ""


# ── отбор протокола состава ──
def test_protocol_matches_waste_rejects_air_water_soil():
    fkko, name = "91920102394", "песок, загрязненный нефтью или нефтепродуктами"
    air = {"kind": "КХА", "object": "атмосферный воздух",
           "substances": [{"name": "нефтепродукты", "unit": "мг/м3"}]}
    gs = {"kind": "хим", "object": "песок загрязненный нефтепродуктами",
          "substances": [{"name": "сажа", "unit": "г/с"}]}
    soil = {"kind": "хим", "object": "земельный участок с кадастровым номером",
            "substances": [{"name": "нефтепродукты", "unit": "мг/кг"}]}
    bio = {"kind": "биотест", "fkko": fkko, "substances": []}
    ok_code = {"kind": "КХА", "fkko": "9 19 201 02 39 4",
               "substances": [{"name": "нефтепродукты", "unit": "мг/кг"}]}
    ok_name = {"kind": "морфологический", "object": "Песок, загрязненный нефтью "
               "или нефтепродуктами (содержание нефтепродуктов менее 15 %)",
               "substances": [{"name": "кремний диоксид", "unit": "%"}]}
    assert not R.protocol_matches_waste(air, fkko, name)
    assert not R.protocol_matches_waste(gs, fkko, name)     # единицы выбросов
    assert not R.protocol_matches_waste(soil, fkko, name)
    assert not R.protocol_matches_waste(bio, fkko, name)    # не состав
    assert R.protocol_matches_waste(ok_code, fkko, name)
    assert R.protocol_matches_waste(ok_name, fkko, name)
    assert R.protocol_units_ok({"substances": []})           # без единиц — ок


# ── происхождение ──
def test_origin_for_exact_prefix_and_name():
    assert R.origin_for("7 33 100 01 72 4") == "жизнедеятельность работников"
    assert "смет с территории" in R.origin_for("73339001714", "смет с территории")
    assert "складских" in R.origin_for("73322001724")
    assert "уборке офисных" in R.origin_for("73310002725")
    assert "шин" in R.origin_for("92111001504", "Шины пневматические")
    assert "люминесцентные" in R.origin_for("47110101521", "Лампы ртутные")
    assert "аккумулятор" in R.origin_for("92011001532")
    assert "масла" in R.origin_for("40611001313", "Отходы минеральных масел моторных")
    assert "кирпич" in R.origin_for("82310101215", "Лом кирпичной кладки")
    assert "земляных работ" in R.origin_for("81111112495", "Отходы грунта")
    assert "черных металлов" in R.origin_for("46101001205", "Лом черных металлов")
    assert "картона" in R.origin_for("40518301605", "Отходы упаковочного картона")
    assert "полиэтилена" in R.origin_for("43411002295", "Отходы пленки полиэтилена")
    assert "стекла" in R.origin_for("45110100205", "Лом изделий из стекла")
    assert "Обтирка" in R.origin_for("91920402604", "Обтирочный материал")
    # без кода — по наименованию; без всего — пусто
    assert "уборке" in R.origin_by_name("Мусор бытовой")
    assert R.origin_for("", "") == ""
    # плейсхолдеров в формулировках нет
    for text in R.ORIGIN_BY_FKKO_PREFIX.values():
        assert "‹" not in text


# ── адрес площадки ──
def test_site_address_priority():
    ctx = ReportContext()
    ctx.organization.address = "191040, СПб, Коломенская ул, дом 7"
    ctx.objects = [NVOSObject(code="47:07:0485001:1568", name="участок", address=""),
                   NVOSObject(code="41-0247-005048-П", name="База",
                              address="ЛО, Промзона Янино, Промышленный проезд, 10")]
    ctx.extra["site_address"] = "Промышленная"          # имя площадки, не адрес
    assert R.site_address_for(ctx) == "ЛО, Промзона Янино, Промышленный проезд, 10"
    ctx.extra["site_address"] = "СПб, ул. Ручная, 3"
    assert R.site_address_for(ctx) == "СПб, ул. Ручная, 3"
    ctx.extra["site_address"] = ""
    ctx.objects = []
    assert R.site_address_for(ctx) == "191040, СПб, Коломенская ул, дом 7"
    ctx.organization.address = ""
    assert R.site_address_for(ctx) == ""


# ── справочник Wi ──
def test_wi_table_official_appendix_4_and_size():
    assert len(R.WI_TABLE) >= 60
    app4 = {"Кадмий": 309.03, "Ртуть": 113.07, "Свинец": 650.63, "Медь": 2840.10,
            "Цинк": 2511.89, "Никель": 1536.97, "Марганец": 7356.42,
            "Хром трёхвалентный": 3630.78, "Хром шестивалентный": 593.38,
            "Бензол": 331.13, "Толуол": 1778.28, "Этилбензол": 3019.95,
            "Фенол": 508.94, "Бенз(а)пирен": 59.97, "Мышьяк": 493.55}
    for name, wi in app4.items():
        assert R.WI_TABLE[name]["wi"] == wi, name
        assert "приложение № 4" in R.WI_TABLE[name]["source"]
    for comp in ("картон", "бумага", "полиэтилен", "ПВХ", "полипропилен",
                 "ткань х/б", "древесина", "стекло", "железо", "алюминий",
                 "медь", "цинк", "свинец", "кадмий", "ртуть", "никель", "хром",
                 "марганец", "нефтепродукты", "кремний диоксид (песок)",
                 "кальция карбонат", "массовая доля влаги", "пищевые отходы",
                 "резина", "ПЭТ", "полистирол", "растительные остатки",
                 "азот аммонийный", "хлориды", "сульфаты", "натрий", "фосфаты"):
        wi, src, canon = R.wi_for(comp)
        assert wi and src and canon, comp
    assert R.wi_for("бумага")[0] == 1_000_000 and "п. 11" in R.wi_for("бумага")[1]
    assert R.wi_for("Совсем неизвестное")[0] is None
    assert R.wi_for("прочие дисперсные системы")[0] is None
    assert R.wi_table_rows()[0]["name"]
