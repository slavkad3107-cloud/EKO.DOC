"""ИИ-извлечение данных из приложенных документов.

Дополняет консервативный regex-парсер (parsers/extractor.py) семантикой:
LLM читает текст справок/актов/протоколов и возвращает структурированный
JSON, где у КАЖДОГО значения есть цитата-источник. Значения попадают в
ReportContext только вместе с провенансом (файл + цитата), чтобы эколог
видел, что принято и откуда взято.

Правило слияния то же, что у regex-парсера: не перезаписывать непустое.
Конфликты (ИИ увидел другое значение) не применяются, а показываются.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from ecodoc.ai.config import AIConfig, load_config
from ecodoc.ai.providers import AIError, chat_with_fallback
from ecodoc.core.models import NVOSObject, ReportContext, WasteFlow
from ecodoc.parsers.text_extract import ExtractedDoc

_CHUNK = 14000  # символов текста документа на один запрос к модели

SYSTEM = """Ты — ассистент инженера-эколога РФ. Извлеки из фрагмента документа
данные для экологической отчётности. Верни СТРОГО один JSON-объект без
пояснений и без markdown. Схема (все поля необязательны, пропускай пустые):
{
 "doc_type": "справка об утилизации|акт|протокол КХА|биотестирование|договор|устав|иное",
 "organization": {"name":"", "short_name":"", "inn":"", "kpp":"", "ogrn":"",
                  "address":"", "director_name":"", "phone":"", "email":""},
 "objects": [{"code":"XX-XXXX-XXXXXX-Б", "name":"", "address":"", "category":""}],
 "wastes": [{"fkko":"11 цифр", "name":"", "hazard_class":1-5,
             "generated":"т", "transferred":"т", "used":"т", "neutralized":"т"}],
 "disposal_acts": [{"date":"ДД.ММ.ГГГГ", "counterparty":"", "inn":"",
                    "license":"", "carrier":"перевозчик", "fkko":"", "waste_name":"",
                    "mass_t":"", "volume_m3":"", "hazard_class":1-5,
                    "operation":"утилизация|обезвреживание|размещение|хранение|обработка"}],
 "lab_results": [{"kind":"КХА|биотест|хим", "protocol_no":"", "date":"",
                  "lab":"", "object":"", "substances":[{"name":"", "value":"", "unit":""}]}],
 "quotes": {"<путь.к.полю>": "дословная короткая цитата из текста"}
}
Правила: числа — строками с точкой; массы в тоннах (переведи из кг: /1000);
не выдумывай — включай только то, что явно есть в тексте; для каждого
заполненного поля добавь запись в quotes (например "organization.inn",
"wastes[0].generated", "disposal_acts[0].mass_t")."""


@dataclass
class Accepted:
    """Принятое значение — для отчёта «что принято и откуда взято»."""
    field: str
    value: str
    src: str        # имя файла
    quote: str = ""


@dataclass
class Conflict:
    field: str
    current: str
    proposed: str
    src: str


@dataclass
class ExtractionReport:
    accepted: list[Accepted] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    used_model: str = ""

    def render(self) -> str:
        lines = ["── ИИ-анализ: что принято и откуда взято ──"]
        if self.used_model:
            lines.append(f"Модель: {self.used_model}")
        for a in self.accepted:
            q = f'  ← «{a.quote[:90]}»' if a.quote else ""
            lines.append(f"  ✓ {a.field} = {a.value}   [{a.src}]{q}")
        if not self.accepted:
            lines.append("  (новых значений не принято)")
        for c in self.conflicts:
            lines.append(f"  ⚠ КОНФЛИКТ {c.field}: в контексте «{c.current}», "
                         f"в документе {c.src} — «{c.proposed}» (не применено)")
        for e in self.errors:
            lines.append(f"  ✖ {e}")
        return "\n".join(lines)


def _parse_json(text: str) -> dict:
    """Достать JSON из ответа модели (модели любят обрамлять ```json)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("в ответе модели нет JSON")
    return json.loads(text[start:end + 1])


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower().replace("ё", "е")


def _verify_quotes(quotes: dict, chunk: str) -> dict:
    """Цитата легитимна, только если реально встречается в тексте документа.

    Модель может «сочинить» цитату — тогда помечаем её, чтобы эколог не
    принял значение за подтверждённое.
    """
    norm_chunk = _norm(chunk)
    out = {}
    for key, q in (quotes or {}).items():
        q = str(q or "")
        if q and _norm(q) not in norm_chunk:
            q += "  ⚠ЦИТАТА НЕ НАЙДЕНА В ТЕКСТЕ — проверьте!"
        out[key] = q
    return out


def _merge_org(ctx: ReportContext, data: dict, quotes: dict, src: str,
               rep: ExtractionReport):
    org = data.get("organization") or {}
    for attr in ("name", "short_name", "inn", "kpp", "ogrn", "address",
                 "director_name", "phone", "email"):
        val = str(org.get(attr) or "").strip()
        if not val:
            continue
        cur = getattr(ctx.organization, attr, "")
        if cur and cur != val:
            rep.conflicts.append(Conflict(f"organization.{attr}", cur, val, src))
        elif not cur:
            setattr(ctx.organization, attr, val)
            quote = quotes.get(f"organization.{attr}", "")
            ctx.provenance[attr] = {"src": src, "quote": quote, "by": "ai"}
            rep.accepted.append(Accepted(f"organization.{attr}", val, src, quote))


def _merge_objects(ctx: ReportContext, data: dict, src: str, rep: ExtractionReport):
    for o in data.get("objects") or []:
        code = str(o.get("code") or "").strip()
        if not code:
            continue
        existing = next((x for x in ctx.objects if x.code == code), None)
        if existing is None:
            existing = NVOSObject(code=code, region_code=code.split("-")[0])
            ctx.objects.append(existing)
            rep.accepted.append(Accepted("objects[].code", code, src))
        for attr in ("name", "address", "category"):
            val = str(o.get(attr) or "").strip()
            if val and not getattr(existing, attr):
                setattr(existing, attr, val)
                rep.accepted.append(Accepted(f"объект {code}.{attr}", val, src))


def _merge_acts(ctx: ReportContext, data: dict, src: str, rep: ExtractionReport):
    """Справки-акты об обращении с отходами — первичный ввод (WasteAct).
    Дедуп по (ФККО, дата, получатель, масса), чтобы повторный анализ не двоил."""
    from ecodoc.core.models import WasteAct
    seen = {(a.fkko_code, a.date, a.receiver, str(a.mass)) for a in ctx.waste_acts}
    for act in data.get("disposal_acts") or []:
        fkko = re.sub(r"\D", "", str(act.get("fkko") or ""))
        mass = _dec(act.get("mass_t"))
        if len(fkko) != 11 or mass is None or mass == 0:
            continue
        hz = act.get("hazard_class")
        hazard = int(hz) if hz in (1, 2, 3, 4, 5) else (
            int(fkko[-1]) if fkko[-1] in "12345" else 5)
        receiver = str(act.get("counterparty") or "").strip()
        key = (fkko, str(act.get("date") or ""), receiver, str(mass))
        if key in seen:
            continue
        seen.add(key)
        ctx.waste_acts.append(WasteAct(
            name=str(act.get("waste_name") or "").strip(), fkko_code=fkko,
            hazard_class=hazard, mass=mass,
            volume_m3=_dec(act.get("volume_m3")) or 0,
            operation=str(act.get("operation") or "").strip(),
            carrier=str(act.get("carrier") or "").strip(), receiver=receiver,
            receiver_inn=str(act.get("inn") or "").strip(),
            license=str(act.get("license") or "").strip(),
            date=str(act.get("date") or "").strip()))
        rep.accepted.append(Accepted(
            f"акт {fkko} ({act.get('operation','')})", f"{mass} т → {receiver}", src))


def _merge_wastes(ctx: ReportContext, data: dict, quotes: dict, src: str,
                  rep: ExtractionReport):
    # агрегированное движение из документа (напр. готовый журнал); акты идут
    # в ctx.waste_acts отдельно (_merge_acts) и потом сворачиваются apply_acts
    items = [(w, f"wastes[{j}]")
             for j, w in enumerate(data.get("wastes") or [])]
    for w, qkey in items:
        fkko = re.sub(r"\D", "", str(w.get("fkko") or ""))
        if len(fkko) != 11:
            continue
        flow = next((x for x in ctx.wastes if x.fkko_code == fkko), None)
        if flow is None:
            hz = w.get("hazard_class")
            flow = WasteFlow(fkko_code=fkko,
                             hazard_class=int(hz) if hz in (1, 2, 3, 4, 5) else
                             (int(fkko[-1]) if fkko[-1] in "12345" else 5))
            ctx.wastes.append(flow)
            rep.accepted.append(Accepted("wastes[].fkko", fkko, src))
        if w.get("name") and not flow.name:
            flow.name = str(w["name"]).strip()
            rep.accepted.append(Accepted(f"отход {fkko}.name", flow.name, src))
        for attr in ("generated", "transferred", "used", "neutralized"):
            val = _dec(w.get(attr))
            if val is None or val == 0:
                continue
            cur = getattr(flow, attr)
            if cur and cur != val:
                rep.conflicts.append(Conflict(f"отход {fkko}.{attr}",
                                              str(cur), str(val), src))
            elif not cur:
                setattr(flow, attr, val)
                quote = quotes.get(f"{qkey}.{attr}", "") or \
                    quotes.get(f"{qkey}.mass_t", "")
                ctx.provenance.setdefault("ai_values", []).append(
                    {"field": f"отход {fkko}.{attr}", "value": str(val),
                     "src": src, "quote": quote})
                rep.accepted.append(Accepted(f"отход {fkko}.{attr} (т)",
                                             str(val), src, quote))


def _store_extras(ctx: ReportContext, data: dict, src: str,
                  rep: ExtractionReport):
    """Акты и протоколы целиком складываем в extra — пригодятся формам."""
    labels = {"disposal_acts": "акт/справка об утилизации",
              "lab_results": "протокол лаборатории"}
    for key, label in labels.items():
        for item in data.get(key) or []:
            item["_src"] = src
            existing = ctx.extra.setdefault(key, [])
            if item in existing:
                continue
            existing.append(item)
            brief = ", ".join(f"{k}={v}" for k, v in item.items()
                              if v and not k.startswith("_") and k != "substances")
            rep.accepted.append(Accepted(f"{label} → extra.{key}", brief, src))


def analyze_docs(docs: list[ExtractedDoc], ctx: ReportContext,
                 cfg: AIConfig | None = None) -> ExtractionReport:
    """Прогнать документы через LLM и слить результат в контекст.

    Запросы к модели идут ПАРАЛЛЕЛЬНО (сетевые вызовы — потоки дают большой
    выигрыш, особенно на облачном провайдере). Слияние результатов в общий
    контекст — потом, последовательно (потокобезопасно).
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    cfg = cfg or load_config()
    rep = ExtractionReport()
    if not cfg.provider:
        rep.errors.append("ИИ не настроен: запустите `python -m ecodoc ai setup`")
        return rep

    # список задач (документ, кусок текста, метка)
    tasks = []
    for doc in docs:
        chunks = [doc.text[i:i + _CHUNK] for i in range(0, len(doc.text), _CHUNK)] \
            or [""]
        for n, chunk in enumerate(chunks, 1):
            if not chunk.strip():
                continue
            label = doc.path.name if len(chunks) == 1 else f"{doc.path.name} (ч.{n})"
            tasks.append((label, doc.path.name, chunk))

    def _ask(task):
        label, docname, chunk = task
        try:
            answer, model = chat_with_fallback(
                cfg, SYSTEM, f"Документ «{docname}»:\n\n{chunk}")
            return (label, chunk, _parse_json(answer), model, None)
        except (AIError, ValueError, json.JSONDecodeError) as e:
            return (label, chunk, None, "", str(e))

    # локальный провайдер (ollama) — без параллелизма (перегрузит одну модель);
    # облачный — до 6 одновременных запросов
    local = cfg.provider in ("ollama", "lmstudio")
    workers = 1 if local else 6
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_ask, tasks))

    # слияние — последовательно, в порядке документов
    for label, chunk, data, model, err in results:
        if err:
            rep.errors.append(f"{label}: {err}")
            continue
        rep.used_model = model
        quotes = _verify_quotes(data.get("quotes") or {}, chunk)
        _merge_org(ctx, data, quotes, label, rep)
        _merge_objects(ctx, data, label, rep)
        _merge_acts(ctx, data, label, rep)
        _merge_wastes(ctx, data, quotes, label, rep)
        _store_extras(ctx, data, label, rep)
    # свернуть собранные акты в движение (акты первичны)
    if ctx.waste_acts:
        from ecodoc.core.waste_agg import aggregate_acts
        wastes, receivers = aggregate_acts(ctx.waste_acts)
        ctx.wastes = wastes
        if receivers:
            if not isinstance(ctx.extra, dict):
                ctx.extra = {}
            ctx.extra["waste_receivers"] = receivers
        rep.accepted.append(Accepted(
            "движение отходов", f"рассчитано из {len(ctx.waste_acts)} актов "
            f"({len(wastes)} видов отходов)", "агрегация"))
    return rep
