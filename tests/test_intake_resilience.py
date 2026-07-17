"""Регрессы v0.40: отчёт без спама, ИИ-сбои не теряют файлы, чистка мусора ИП."""
import json
from pathlib import Path
from types import SimpleNamespace

from ecodoc.ai.analyzer import Conflict, ExtractionReport, analyze_docs
from ecodoc.ai.config import AIConfig
from ecodoc.core.models import ReportContext
from ecodoc.core.serialize import from_json, to_json


def test_conflicts_grouped_in_render():
    """Один и тот же конфликт из 8 договоров — одна строка, а не восемь."""
    rep = ExtractionReport()
    for i in range(8):
        rep.conflicts.append(Conflict("organization.name", "МИНИХ",
                                      "ИП Миних", f"ДС№{i}.doc"))
    rep.conflicts.append(Conflict("organization.phone", "8(911)", "+7921", "ДОГ.pdf"))
    out = rep.render()
    assert out.count("КОНФЛИКТ organization.name") == 1
    assert "в 8 документах" in out
    assert "в документе ДОГ.pdf" in out          # одиночный — по-старому


def test_ai_not_configured_marks_all_files_failed():
    """ИИ не настроен → все файлы в failed_files (intake их не удалит)."""
    docs = [SimpleNamespace(path=Path("a.pdf"), text="x"),
            SimpleNamespace(path=Path("b.doc"), text="y")]
    rep = analyze_docs(docs, ReportContext(), cfg=AIConfig(provider=""))
    assert rep.failed_files == {"a.pdf", "b.doc"}


def test_local_provider_timeout_no_cooldown():
    """Таймаут локального Ollama (большой документ) НЕ хоронит его на 5 минут;
    отказ соединения — короткое остывание; облачный таймаут — как раньше."""
    from ecodoc.ai import providers as pr
    pr._COOLDOWN.clear()
    pr._mark_dead("ollama", Exception("Read timed out"))
    assert not pr._cooling("ollama")
    pr._mark_dead("ollama", Exception("connection refused"))
    assert pr._cooling("ollama")
    pr._mark_dead("deepseek", Exception("Read timed out"))
    assert pr._cooling("deepseek")
    pr._COOLDOWN.clear()


def test_from_json_strips_kpp_for_individual(tmp_path):
    """У ИП КПП не бывает — мусор из счетов контрагентов чистится при загрузке."""
    ctx = ReportContext()
    ctx.organization.inn = "780600114472"        # 12 знаков = ИП
    ctx.organization.kpp = "780543001"           # мусор старых версий
    p = tmp_path / "context.json"
    to_json(ctx, p)
    loaded = from_json(p)
    assert loaded.organization.kpp == ""
    # у ЮЛ (10 знаков) КПП живёт
    ctx.organization.inn = "7801234564"
    to_json(ctx, p)
    assert from_json(p).organization.kpp == "780543001"


def test_summary_marks_invalid_object_codes():
    from ecodoc.core.models import NVOSObject
    from ecodoc.parsers.extractor import summary
    ctx = ReportContext()
    ctx.objects = [NVOSObject(code="41-0247-005048-П"),
                   NVOSObject(code="XX-XXXX-XXXXXX-Б"),
                   NVOSObject(code="47:07:1039001:211")]
    out = summary(ctx)
    assert "XX-XXXX-XXXXXX-Б ⚠" in out
    assert "41-0247-005048-П," in out            # валидный — без пометки
    assert "47:07:1039001:211" in out and "47:07:1039001:211 ⚠" not in out
    assert "удалите кнопкой" in out
