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
RE_EMAIL = re.compile(r"\b([\w.+-]+@[\w-]+\.[\w.-]+)\b")
# контекст, в котором 11-значное число — НЕ ФККО (телефон/реквизиты)
_NONFKKO_CTX = re.compile(
    r"(тел|phone|факс|моб|\+7|8\s*\(|инн|огрн|огрнип|кпп|бик|р/?сч|к/?сч|"
    r"сч[её]т|л/?с|снилс|whatsapp|viber)\D{0,6}$")


def _first(rx: re.Pattern, text: str):
    m = rx.search(text)
    if not m:
        return ""
    # группа 1, если она есть; иначе всё совпадение (страховка от regex без группы)
    return m.group(1) if m.re.groups >= 1 else m.group(0)


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

    # коды ФККО -> ПОДСКАЗКИ (extra.fkko_seen), а НЕ позиции движения.
    # Раньше каждый встреченный код превращался в пустую строку движения —
    # у пользователя копились десятки нулевых позиций-мусора. Движение
    # наполняется только справками-актами (или вручную); найденные коды
    # сохраняем как справочную информацию для подстановки.
    names = _fkko_names()
    if not isinstance(ctx.extra, dict):
        ctx.extra = {}
    seen = ctx.extra.setdefault("fkko_seen", [])
    seen_codes = {s.get("fkko") for s in seen if isinstance(s, dict)}
    for m in RE_FKKO.finditer(t):
        digits = re.sub(r"\s", "", m.group(1))
        if not _fkko_valid(digits) or digits in seen_codes:
            continue
        # контекст перед числом — если это телефон/реквизит счёта, пропускаем
        before = t[max(0, m.start() - 40):m.start()].lower()
        if _NONFKKO_CTX.search(before):
            continue
        seen_codes.add(digits)
        seen.append({"fkko": digits, "name": names.get(digits, ""),
                     "src": doc.path.name})


def _fkko_valid(digits: str) -> bool:
    """Похоже ли 11-значное число на реальный код ФККО (а не ОКТМО/шум).

    ФККО: 11 цифр, первая — блок (1–9), последняя — класс опасности.
    В отчётах о движении отходов участвуют только классы 1–5 (0 — групповые
    заголовки каталога, не позиции). Отсекаем «круглые» коды с длинными
    хвостами нулей и коды с чрезмерным повтором одной цифры (шум OCR/таблиц).
    """
    if len(digits) != 11 or not digits.isdigit():
        return False
    if digits[0] == "0":                     # реальные ФККО начинаются с 1–9
        return False
    if digits[-1] not in "12345":            # класс опасности 1–5
        return False
    # блоки ФККО 7/8/9 имеют ограниченный набор подгрупп — отсекаем «телефонные»
    # префиксы (79…, 89…, 78… и т.п.), которые структурно не бывают ФККО
    _SUBGROUPS = {"7": "12345", "8": "1234", "9": "12345"}
    if digits[0] in _SUBGROUPS and digits[1] not in _SUBGROUPS[digits[0]]:
        return False
    if digits.count("0") >= 6:               # групповой заголовок / круглый шум
        return False
    if max(digits.count(d) for d in set(digits)) >= 7:  # почти одна цифра
        return False
    return True


def _fkko_names() -> dict:
    """Код ФККО → наименование (из справочника частых отходов)."""
    try:
        from ecodoc.core.refdata import common_wastes
        return {w["fkko"]: w.get("name", "") for w in common_wastes()}
    except Exception:
        return {}


def summary(ctx: ReportContext) -> str:
    """Краткий отчёт о том, что распозналось, — для проверки человеком."""
    o = ctx.organization
    lines = [
        "── Распознано из приложенных документов ──",
        f"ИНН: {o.inn or '—'}   КПП: {o.kpp or '—'}   ОГРН: {o.ogrn or '—'}",
        f"ОКТМО: {o.oktmo or '—'}   ОКПО: {o.okpo or '—'}   ОКВЭД: {o.okved or '—'}",
        f"Объекты НВОС: {', '.join(x.code for x in ctx.objects) or '—'}",
        f"Движение отходов: {len(ctx.wastes)} позиций (из справок-актов); "
        f"встречено кодов ФККО в документах: "
        f"{len((ctx.extra or {}).get('fkko_seen', []))} (как подсказки)",
    ]
    errs = ctx.provenance.get("_errors")
    if errs:
        lines.append("Ошибки чтения: " + "; ".join(errs))
    lines.append("⚠ Проверьте значения и заполните массы/объёмы вручную.")
    return "\n".join(lines)
