"""Регрессы разбора реквизитов из документов."""
from types import SimpleNamespace
from pathlib import Path

from ecodoc.parsers import extractor
from ecodoc.parsers.extractor import RE_EMAIL, _first
from ecodoc.core.models import ReportContext


def test_email_extraction_no_crash():
    """RE_EMAIL без группы раньше валил _first (IndexError: no such group)."""
    assert _first(RE_EMAIL, "Контакты: eco@minih.ru") == "eco@minih.ru"
    assert _first(RE_EMAIL, "нет почты тут") == ""


def test_fill_from_doc_with_email():
    doc = SimpleNamespace(path=Path("письмо.txt"),
                          text="ООО Тест ИНН 7801234564 e-mail info@example.ru")
    ctx = ReportContext()
    extractor._fill_from_doc(ctx, doc)          # не должно падать
    assert ctx.organization.inn == "7801234564"
    assert ctx.organization.email == "info@example.ru"


def test_first_handles_pattern_without_group():
    import re
    # страховка: паттерн без группы → возвращаем всё совпадение, не падаем
    assert _first(re.compile(r"\d{3}"), "код 123 тут") == "123"


def test_fkko_filter_rejects_noise():
    from ecodoc.parsers.extractor import _fkko_valid
    # реальные кобы ФККО
    assert _fkko_valid("73310001724")   # мусор офисный, класс 4
    assert _fkko_valid("47110101521")   # лампы, класс 1
    # шум, который раньше принимался за отход:
    assert not _fkko_valid("01041612155")  # начинается с 0 (ОКТМО-шум)
    assert not _fkko_valid("13000030000")  # круглый групповой код
    assert not _fkko_valid("40278000000")  # 6+ нулей
    assert not _fkko_valid("67143202148")  # класс 8 не бывает
    assert not _fkko_valid("11111111111")  # одна цифра


def test_fkko_name_autofilled():
    from types import SimpleNamespace
    doc = SimpleNamespace(path=Path("перечень.txt"),
                          text="Отход ФККО 4 71 101 01 52 1 лампы")
    ctx = ReportContext()
    extractor._fill_from_doc(ctx, doc)
    lamp = next((w for w in ctx.wastes if w.fkko_code == "47110101521"), None)
    assert lamp is not None
    assert "ламп" in lamp.name.lower()      # имя подтянулось из справочника
