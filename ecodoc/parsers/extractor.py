"""Эвристический разбор приложенных документов в ReportContext.

Это первый («парсинг») шаг гибридного сценария: вытащить из doc/pdf/jpg всё,
что распознаётся надёжно (реквизиты организации, код объекта НВОС, коды ФККО),
и записать в контекст вместе с провенансом (из какого файла взято), чтобы
эколог потом проверил и довёл значения вручную.

Намеренно консервативно: лучше оставить поле пустым, чем подставить мусор.
"""
from __future__ import annotations

import re
from pathlib import Path

from ecodoc.core.models import (NVOSObject, Organization, ReportContext,
                                WasteFlow)
from ecodoc.parsers.text_extract import ExtractedDoc, extract

# --- регулярные выражения по реквизитам РФ ---
RE_INN_UL = re.compile(r"\bИНН[\s:№]*?(\d{10})\b")
RE_INN_FL = re.compile(r"\bИНН[\s:№]*?(\d{12})\b")
RE_KPP = re.compile(r"\bКПП[\s:№]*?(\d{9})\b")
RE_OGRN = re.compile(r"\bОГРН(?:ИП)?[\s:№]*?(\d{13}|\d{15})\b")
RE_OKPO = re.compile(r"\bОКПО[\s:№]*?(\d{8,10})\b")
RE_OKTMO = re.compile(r"\bОКТМО[\s:№]*?(\d{8}|\d{11})\b")
RE_OKVED = re.compile(r"\bОКВЭД[\s\d.:№]*?(\d{2}\.\d{1,2}(?:\.\d{1,2})?)\b")
# код объекта НВОС: 2 цифры - 4 цифры - 6 цифр - буква (П/Т/О/К ...)
RE_NVOS = re.compile(r"\b(\d{2}-\d{4}-\d{6}-[А-ЯA-Z])\b")
# ФККО: 11 знаков (последний — класс опасности 0-5), часто с пробелами
RE_FKKO = re.compile(r"\b(\d[\d\s]{9,15}\d)\b")
RE_CATEGORY = re.compile(r"категори[ияю][\s,]*?(I{1,3}V?|IV|[1-4])\s*категори", re.IGNORECASE)
RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def _first(rx: re.Pattern, text: str):
    m = rx.search(text)
    return m.group(1) if m else ""


def parse_files(paths: list[str | Path], ocr: bool = True) -> ReportContext:
    """Разобрать список файлов в единый контекст с провенансом."""
    ctx = ReportContext()
    docs: list[ExtractedDoc] = []
    for path in paths:
        try:
            docs.append(extract(path, ocr=ocr))
        except Exception as exc:
            ctx.provenance.setdefault("_errors", []).append(f"{Path(path).name}: {exc}")
    for doc in docs:
        _fill_from_doc(ctx, doc)
    return ctx


def _set(ctx: ReportContext, obj, attr: str, value: str, doc: ExtractedDoc):
    """Заполнить поле, только если оно ещё пустое; записать провенанс."""
    if value and not getattr(obj, attr, ""):
        setattr(obj, attr, value)
        ctx.provenance[attr] = doc.path.name


def _fill_from_doc(ctx: ReportContext, doc: ExtractedDoc) -> None:
    t = doc.text
    org: Organization = ctx.organization

    inn = _first(RE_INN_UL, t) or _first(RE_INN_FL, t)
    _set(ctx, org, "inn", inn, doc)
    _set(ctx, org, "kpp", _first(RE_KPP, t), doc)
    _set(ctx, org, "ogrn", _first(RE_OGRN, t), doc)
    _set(ctx, org, "okpo", _first(RE_OKPO, t), doc)
    _set(ctx, org, "oktmo", _first(RE_OKTMO, t), doc)
    _set(ctx, org, "okved", _first(RE_OKVED, t), doc)
    _set(ctx, org, "email", _first(RE_EMAIL, t), doc)

    # объект(ы) НВОС
    for code in dict.fromkeys(RE_NVOS.findall(t)):
        if not any(o.code == code for o in ctx.objects):
            obj = NVOSObject(code=code, region_code=code.split("-")[0])
            ctx.objects.append(obj)
            ctx.provenance.setdefault("objects", []).append(
                {"code": code, "src": doc.path.name})

    # коды ФККО -> черновые позиции отходов (массы заполнит человек)
    for raw in RE_FKKO.findall(t):
        digits = re.sub(r"\s", "", raw)
        if len(digits) != 11:
            continue
        hazard = int(digits[-1]) if digits[-1] in "12345" else 5
        if not any(w.fkko_code == digits for w in ctx.wastes):
            ctx.wastes.append(WasteFlow(fkko_code=digits, hazard_class=hazard))
            ctx.provenance.setdefault("wastes", []).append(
                {"fkko": digits, "src": doc.path.name})


def summary(ctx: ReportContext) -> str:
    """Краткий отчёт о том, что распозналось, — для проверки человеком."""
    o = ctx.organization
    lines = [
        "── Распознано из приложенных документов ──",
        f"ИНН: {o.inn or '—'}   КПП: {o.kpp or '—'}   ОГРН: {o.ogrn or '—'}",
        f"ОКТМО: {o.oktmo or '—'}   ОКПО: {o.okpo or '—'}   ОКВЭД: {o.okved or '—'}",
        f"Объекты НВОС: {', '.join(x.code for x in ctx.objects) or '—'}",
        f"Позиций отходов (ФККО): {len(ctx.wastes)}",
    ]
    errs = ctx.provenance.get("_errors")
    if errs:
        lines.append("Ошибки чтения: " + "; ".join(errs))
    lines.append("⚠ Проверьте значения и заполните массы/объёмы вручную.")
    return "\n".join(lines)
