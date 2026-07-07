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
