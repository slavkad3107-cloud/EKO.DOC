"""Санитар источников выбросов: мусор из чужих томов, дубли, номера.

Классы мусора — с реальной базы Техностроя (352 записи при ~10 настоящих
источниках): двери из тома ПБ, источники шума из акустики, месяцы из
помесячной таблицы, вещества как источники, «№ ИЗАВ 1» с вложенными
префиксами и латинскими двойниками букв."""
from ecodoc.core import sanitize
from ecodoc.core import sanitize_sources as ss
from ecodoc.core.models import ReportContext


def _ctx(sources):
    ctx = ReportContext()
    ctx.extra["emission_sources"] = sources
    return ctx


# ── нормализация номера ─────────────────────────────────────────────────
def test_number_normalization():
    n = ss.norm_source_number
    assert n("№6501") == "6501"
    assert n("№ ИЗАВ 1") == "1"            # вложенные префиксы: «№» + «ИЗАВ»
    assert n("№ источника 6502") == "6502"  # «источника» длиннее «ист»
    assert n("001.01.6501") == "6501"      # площадка.цех.источник из «Эколога»
    assert n("ИЗА 6503") == "6503"
    assert n("ист. 12") == "12"
    assert n("0001") == "0001"             # ведущие нули — часть номера
    assert n("6505.0") == "6505"           # хвост от чисел Excel
    assert n("источника") == ""            # слово без цифр — номера нет


def test_name_as_number_is_no_number():
    """«Автокран КС-55713 (д)» в графе номера при том же имени — номера нет."""
    assert ss.effective_number("Автокран КС-55713 (д)", "Автокран КС-55713") == ""
    assert ss.effective_number("6501", "Автокран КС-55713") == "6501"


# ── отсев мусора ────────────────────────────────────────────────────────
def test_junk_from_other_volumes_rejected():
    bad = [
        ("Этаж 1, Зона эвакуации 7", "Максимальное время выхода с этажа"),
        ("ИШ-21", "Вентилятор НАПОР-7,1"),
        ("ДП1", "Система подпора воздуха в паркинг"),
        ("ДП3.1, ДП4.1", "Система подпора воздуха в зону МГН (открытая дверь)"),
        ("Регистратор 1", "Этаж 1, уровень 1,7 м"),
        ("1 секция", "Рабочее освещение"),
        ("", "Январь"),                      # помесячная таблица выбросов
        ("", "точечный источник шума"),
    ]
    for num, name in bad:
        v = ss.check_source(num, name, [{"code": "0301"}])
        assert not v.ok, (num, name, v.reason)


def test_substance_rows_rejected():
    """Таблица веществ, прочитанная как перечень источников."""
    v = ss.check_source("301", "Азота диоксид (Азот (IV) оксид)", [{"code": "301"}])
    assert not v.ok and "вещество" in v.reason
    v2 = ss.check_source("0301", "Паркинг на 300м/м (54)", [{"code": "0301"}])
    assert not v2.ok and "код загрязняющего вещества" in v2.reason


def test_real_sources_kept():
    good = [
        ("0001", "Въезд/выезд автомобилей"),
        ("6501", "Работа строительной техники"),
        ("П1", "Вентиляционная система помещения для хранения автомобилей"),
        ("В3", "Вентиляционная система помещения СС и электрощитовой"),
        ("6006", "Контейнерная площадка"),
    ]
    for num, name in good:
        v = ss.check_source(num, name, [{"code": "0301"}])
        assert v.ok and not v.suspect, (num, name, v.reason)


def test_unnumbered_machinery_kept_as_suspect():
    """Техника стройки без номера — настоящая, но помечается."""
    v = ss.check_source("", "Экскаватор", [{"code": "0301"}] * 6)
    assert v.ok and v.suspect and "номера" in v.reason
    # без номера И без веществ — пустая строка из текста тома
    v2 = ss.check_source("", "проезды автотранспорта", [])
    assert not v2.ok


def test_homoglyphs_do_not_break_rules():
    """Латинские двойники букв (OCR): «ИЗAВ» с латинской A."""
    assert ss.norm_source_number("№ ИЗAВ 5") == "5"          # A латинская
    v = ss.check_source("ИШ-22", "Вентилятор", [{"code": "1"}])
    assert not v.ok


# ── слияние дублей ──────────────────────────────────────────────────────
def test_merge_keeps_richest_and_tops_up_pollutants():
    merged, removed = ss.merge_sources([
        {"number": "№6501", "name": "Работа строительной техники",
         "pollutants": [{"code": "0301"}, {"code": "0304"}]},
        {"number": "001.01.6501", "name": "работа строительной техники",
         "pollutants": [{"code": "0301"}, {"code": "0328"}, {"code": "0330"}]},
    ])
    assert len(merged) == 1 and len(removed) == 1
    src = merged[0]
    assert src["number"] == "6501"
    codes = {p["code"] for p in src["pollutants"]}
    assert codes == {"0301", "0328", "0330", "0304"}   # долив без дублей


def test_clean_context_cleans_sources_end_to_end():
    ctx = _ctx([
        {"number": "№6501", "name": "Работа строительной техники",
         "pollutants": [{"code": "0301"}]},
        {"number": "6501", "name": "Работа строительной техники",
         "pollutants": [{"code": "0337"}]},
        {"number": "ИШ-21", "name": "Вентилятор", "pollutants": [{"code": "1"}]},
        {"number": "", "name": "Февраль", "pollutants": [{"code": "0301"}] * 6},
    ])
    rep = sanitize.clean_context(ctx)
    left = ctx.extra["emission_sources"]
    assert len(left) == 1 and left[0]["number"] == "6501"
    assert len(left[0]["pollutants"]) == 2
    assert len(rep["removed_sources"]) == 2 and len(rep["merged_sources"]) == 1


def test_audit_reports_sources():
    ctx = _ctx([{"number": "ИШ-21", "name": "Вентилятор", "pollutants": []},
                {"number": "6501", "name": "Работа техники",
                 "pollutants": [{"code": "0301"}]},
                {"number": "№6501", "name": "Работа техники",
                 "pollutants": [{"code": "0301"}]}])
    rep = sanitize.audit_context(ctx)
    t = rep["totals"]
    assert t["sources"] == 3 and t["sources_bad"] == 1 and t["sources_dupes"] == 1
