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
 "pollutants_air": [{"code":"0301", "name":"", "mass_norm":"т/год (ПДВ)",
                     "mass_limit":"т/год (ВСВ)"}],
 "pollutants_water": [{"code":"", "name":"", "mass_norm":"т/год (НДС)",
                       "mass_limit":"т/год (ВСС)"}],
 "disposal_acts": [{"date":"ДД.ММ.ГГГГ", "counterparty":"", "inn":"",
                    "license":"лицензия получателя", "carrier":"перевозчик",
                    "carrier_license":"лицензия перевозчика", "fkko":"", "waste_name":"",
                    "mass_t":"", "volume_m3":"", "density":"т/м3", "hazard_class":1-5,
                    "operation":"утилизация|обезвреживание|размещение|хранение|обработка"}],
 "waste_passports": [{"fkko":"11 цифр", "name":"", "hazard_class":1-5,
                      "components":[{"name":"компонент состава", "percent":""}]}],
 "emission_sources": [{"number":"№ источника", "name":"", "kind":"организованный|неорганизованный",
                       "pollutants":[{"code":"", "name":"", "g_s":"г/с", "t_year":"т/год"}]}],
 "lab_results": [{"kind":"КХА|биотест|хим", "protocol_no":"", "date":"",
                  "lab":"", "object":"", "substances":[{"name":"", "value":"", "unit":""}]}],
 "quotes": {"<путь.к.полю>": "дословная короткая цитата из текста"}
}
Правила: числа — строками с точкой; массы в тоннах (переведи из кг: /1000);
не выдумывай — включай только то, что явно есть в тексте; для каждого
заполненного поля добавь запись в quotes (например "organization.inn",
"wastes[0].generated", "disposal_acts[0].mass_t").

ЧТО НЕ ЯВЛЯЕТСЯ ЗАГРЯЗНЯЮЩИМ ВЕЩЕСТВОМ (не клади в pollutants_air/water):
 • работы, процессы и оборудование — «сварочные работы», «работа
   строительной техники», «движение автотранспорта», «укладка асфальта»,
   названия труб, цехов и участков: если в таблице это столбец «источник
   выброса», его место в emission_sources, а не в перечне веществ;
 • группы суммации (коды 6000–6999, названия вида «азота диоксид, серы
   диоксид») — это сочетания веществ, а не вещества;
 • виды сточных вод — «хозяйственно-бытовые сточные воды», «поверхностные
   (ливневые) стоки», «производственные сточные воды», «канализация»: это
   потоки водоотведения, они измеряются объёмом (м³), а не массой вещества.

СРЕДА. pollutants_air — только выбросы В АТМОСФЕРУ (тома ПДВ/НДВ, разделы
ООС, инвентаризация выбросов). pollutants_water — только сбросы В ВОДНЫЕ
ОБЪЕКТЫ или в канализацию (тома НДС, договоры водоотведения, протоколы
сточной воды). Четырёхзначные коды вида 0301, 0337, 2908 — это коды
перечня веществ АТМОСФЕРНОГО воздуха: в pollutants_water их не ставь.
Если из документа не ясно, к какой среде относится вещество, — не угадывай,
пропусти его.

МАССА, А НЕ НОРМАТИВ. В mass_norm/mass_limit клади фактический или
нормативный ВЫБРОС/СБРОС в тоннах за год. В таблицах перечней веществ
рядом стоят колонки «ПДК», «ОБУВ», «класс опасности», «г/с» — их в массу
не бери. Если в строке есть только ПДК и нет массы за год — пропусти
вещество, оставив его без масс, но не подставляй ПДК."""


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
class Rejected:
    """Значение, не принятое в базу (мусор), либо принятое с оговоркой.

    Пользователь должен видеть, что программа отбросила и почему — молча
    выкидывать данные из документов нельзя."""
    field: str
    value: str
    reason: str
    src: str = ""


@dataclass
class ExtractionReport:
    accepted: list[Accepted] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    # не пущено в базу (не вещество, кода нет в ФККО) и принято с оговоркой
    rejected: list = field(default_factory=list)
    doubts: list = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    used_model: str = ""
    # файлы, которые ИИ НЕ проанализировал (провайдер упал/не настроен) —
    # intake не удаляет их исходники, чтобы анализ можно было повторить
    failed_files: set = field(default_factory=set)
    # лист-источник для каждой цитаты: {имя файла: {путь поля: {page, exact}}}
    pages: dict = field(default_factory=dict)
    # диапазон листов каждого чанка: {метка чанка: (первый, последний)}
    page_span: dict = field(default_factory=dict)

    def render(self) -> str:
        lines = ["── ИИ-анализ: что принято и откуда взято ──"]
        if self.used_model:
            lines.append(f"Модель: {self.used_model}")
        for a in self.accepted:
            q = f'  ← «{a.quote[:90]}»' if a.quote else ""
            lines.append(f"  ✓ {a.field} = {a.value}   [{a.src}]{q}")
        if not self.accepted:
            lines.append("  (новых значений не принято)")
        # одинаковый конфликт из многих файлов (реквизиты контрагента в каждом
        # договоре/ДС) сворачиваем в одну строку — не спамим отчёт
        cgroups: dict[tuple, list[str]] = {}
        for c in self.conflicts:
            cgroups.setdefault((c.field, c.current, c.proposed), []).append(c.src)
        for (fld, cur, prop), srcs in cgroups.items():
            srcs = list(dict.fromkeys(srcs))
            if len(srcs) == 1:
                where = f"в документе {srcs[0]}"
            else:
                sample = ", ".join(srcs[:2]) + (", …" if len(srcs) > 2 else "")
                where = f"в {len(srcs)} документах ({sample})"
            lines.append(f"  ⚠ КОНФЛИКТ {fld}: в контексте «{cur}», "
                         f"{where} — «{prop}» (не применено)")
        # не пущенное в базу — показываем всегда: пользователь должен видеть,
        # что программа отбросила и почему (а не гадать, куда делись строки)
        if self.rejected:
            rgroups: dict[str, list[str]] = {}
            for r in self.rejected:
                rgroups.setdefault(r.reason, []).append(f"{r.field}: {r.value}")
            lines.append(f"── Не принято в базу: {len(self.rejected)} "
                         f"позиц. (мусор в исходных документах) ──")
            for reason, items in rgroups.items():
                shown = "; ".join(items[:4]) + ("; …" if len(items) > 4 else "")
                lines.append(f"  ✖ {reason}")
                lines.append(f"     {len(items)}: {shown}")
        if self.doubts:
            lines.append(f"── Принято, но проверьте: {len(self.doubts)} ──")
            for d in self.doubts[:12]:
                lines.append(f"  ? {d.field}: {d.value} — {d.reason}")
            if len(self.doubts) > 12:
                lines.append(f"  … ещё {len(self.doubts) - 12}")
        # одинаковые ошибки (напр. «все провайдеры недоступны» на каждый файл)
        # сворачиваем в одну строку со счётчиком — не спамим отчёт
        groups: dict[str, list[str]] = {}
        for e in self.errors:
            src, _, msg = e.partition(": ")
            key = msg or e
            groups.setdefault(key, []).append(src if msg else "")
        for msg, srcs in groups.items():
            srcs = [s for s in srcs if s]
            if len(srcs) > 2:
                lines.append(f"  ✖ {msg} — {len(srcs)} файлов "
                             f"({srcs[0]}, {srcs[1]}, …)")
            elif srcs:
                for s in srcs:
                    lines.append(f"  ✖ {s}: {msg}")
            else:
                lines.append(f"  ✖ {msg}")
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


def page_chunks(doc) -> list[tuple[str, int, int]]:
    """Текст документа → чанки для модели, нарезанные ПО СТРАНИЦАМ.

    Возвращает [(текст, первая страница, последняя страница)] — 1-based.
    Границы чанка совпадают с границами страниц, поэтому лист-источник
    известен всегда, даже если модель не вернула цитату. Страница длиннее
    лимита режется внутри себя (обе части ссылаются на неё же).
    """
    pages = [p for p in (getattr(doc, "pages", None) or [doc.text])]
    out: list[tuple[str, int, int]] = []
    buf: list[str] = []
    first = 0
    for i, page in enumerate(pages, 1):
        if not (page or "").strip():
            continue
        if len(page) > _CHUNK:                      # огромная страница — режем
            if buf:
                out.append(("\n".join(buf), first, i - 1))
                buf, first = [], 0
            for j in range(0, len(page), _CHUNK):
                out.append((page[j:j + _CHUNK], i, i))
            continue
        size = sum(len(b) + 1 for b in buf)
        if buf and size + len(page) > _CHUNK:
            out.append(("\n".join(buf), first, i - 1))
            buf, first = [], 0
        if not buf:
            first = i
        buf.append(page)
    if buf:
        out.append(("\n".join(buf), first, len(pages)))
    return out or [(doc.text, 1, max(1, len(pages)))]


def page_of_quote(pages: list[str], quote: str,
                  span: tuple[int, int]) -> tuple[int, bool]:
    """(номер листа 1-based, точно ли найдено) для цитаты внутри диапазона.

    Если цитаты нет в тексте (или модель её сочинила) — возвращаем первый лист
    чанка: он всё равно верен, просто менее точен."""
    lo, hi = max(1, span[0]), min(len(pages), span[1]) if pages else span[1]
    q = _norm(quote or "")
    if q:
        for i in range(lo, hi + 1):
            if q in _norm(pages[i - 1]):
                return i, True
    return lo, False


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
        # у ИП (12-значный ИНН) КПП не бывает — не тащить его из счетов
        # контрагентов (реквизиты чужих ЮЛ в документах)
        if attr == "kpp" and ctx.organization.is_individual:
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
    from ecodoc.render.xmlutil import _is_nvos_code
    for o in data.get("objects") or []:
        code = str(o.get("code") or "").strip()
        # принимаем только реальные коды объектов НВОС (NN-NNNN-NNNNNN-Б/П/Т/Л)
        # ИЛИ кадастровые номера участков (NN:NN:NNNNNNN:NN); шаблонные
        # «XX-XXXX-…», «--», номера проектов и прочий мусор — мимо
        is_cadastral = bool(re.fullmatch(r"\d{2}:\d{2}:\d{6,7}:\d+", code))
        if not code or not (_is_nvos_code(code) or is_cadastral):
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


def _act_key(fkko, date, receiver, mass) -> tuple:
    """Нормализованный ключ дедупа акта: «16»/«16.0», «15.03.2025»/«15.3.25»
    и код с пробелами не должны давать разные ключи (иначе повторная загрузка
    того же документа задваивает массы)."""
    from decimal import Decimal
    try:
        m = str(Decimal(str(mass)).normalize())
    except Exception:
        m = str(mass)
    return (re.sub(r"\D", "", str(fkko or "")),
            re.sub(r"\D", "", str(date or "")),
            str(receiver or "").strip().lower(),
            m)


def _merge_acts(ctx: ReportContext, data: dict, src: str, rep: ExtractionReport):
    """Справки-акты об обращении с отходами — первичный ввод (WasteAct).
    Дедуп по нормализованному (ФККО, дата, получатель, масса)."""
    from ecodoc.core.models import WasteAct
    seen = {_act_key(a.fkko_code, a.date, a.receiver, a.mass)
            for a in ctx.waste_acts}
    for act in data.get("disposal_acts") or []:
        fkko = re.sub(r"\D", "", str(act.get("fkko") or ""))
        mass = _dec(act.get("mass_t"))
        if len(fkko) != 11 or mass is None or mass == 0:
            continue
        hz = act.get("hazard_class")
        hazard = int(hz) if hz in (1, 2, 3, 4, 5) else (
            int(fkko[-1]) if fkko[-1] in "12345" else 5)
        receiver = str(act.get("counterparty") or "").strip()
        key = _act_key(fkko, act.get("date"), receiver, mass)
        if key in seen:
            continue
        seen.add(key)
        ctx.waste_acts.append(WasteAct(
            name=str(act.get("waste_name") or "").strip(), fkko_code=fkko,
            hazard_class=hazard, mass=mass,
            volume_m3=_dec(act.get("volume_m3")) or 0,
            density=_dec(act.get("density")) or 0,
            operation=str(act.get("operation") or "").strip(),
            carrier=str(act.get("carrier") or "").strip(),
            carrier_license=str(act.get("carrier_license") or "").strip(),
            receiver=receiver,
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
    from ecodoc.core import sanitize
    for w, qkey in items:
        fkko = re.sub(r"\D", "", str(w.get("fkko") or ""))
        if len(fkko) != 11:
            continue
        # код сверяется с каталогом ФККО ДО записи: выдуманные коды и
        # групповые заголовки в перечень отходов объекта не идут
        chk = sanitize.check_waste(fkko, w.get("name"), w.get("hazard_class"))
        if not chk.ok:
            rep.rejected.append(Rejected(
                "отход", f"{fkko} {str(w.get('name') or '')[:40]}".strip(),
                chk.reason, src))
            continue
        if chk.suspect and chk.reason:
            rep.doubts.append(Rejected(
                "отход", f"{fkko} {str(w.get('name') or '')[:40]}".strip(),
                chk.reason, src))
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


def _merge_pollutants(ctx: ReportContext, data: dict, medium, src: str,
                      rep: ExtractionReport):
    """Вещества (выбросы/сбросы) из ООС/НДВ/НДС — только для своей среды.

    Каждая позиция проходит проверку (core/sanitize): названия работ и виды
    сточных вод в перечень веществ не пускаются, код приводится к четырём
    знакам — иначе «301» и «0301» двоят одно вещество. Отклонённое не
    теряется: причина попадает в отчёт приёма, а сама позиция остаётся в
    кандидатах, где пользователь решает сам.
    Существующие непустые массы не перезаписываются (конфликт — на решение)."""
    from ecodoc.core import sanitize
    from ecodoc.core.models import Medium, Pollutant
    key = "pollutants_air" if medium == Medium.AIR else "pollutants_water"
    what = "воздух" if medium == Medium.AIR else "вода"
    for it in data.get(key) or []:
        code = str(it.get("code") or "").strip()
        name = str(it.get("name") or "").strip()
        if not code and not name:
            continue
        v = sanitize.check_substance(code, name, "air" if medium == Medium.AIR
                                     else "water")
        if not v.ok:
            rep.rejected.append(Rejected(f"вещество ({what})",
                                         f"{code} {name}".strip(), v.reason, src))
            continue
        code = v.code                      # нормализованный (или пустой)
        if v.suspect and v.reason:
            rep.doubts.append(Rejected(f"вещество ({what})",
                                       f"{code or ''} {name}".strip(),
                                       v.reason, src))
        nm_key = sanitize.norm_name(name)
        p = next((x for x in ctx.pollutants if x.medium == medium and
                  ((code and sanitize.norm_code(x.code) == code)
                   or (not code and sanitize.norm_name(x.name) == nm_key))), None)
        if p is None:
            p = Pollutant(name=name, code=code, medium=medium)
            ctx.pollutants.append(p)
            rep.accepted.append(Accepted(
                f"вещество ({what})", f"{code} {name}".strip(), src))
        if name and not p.name:
            p.name = name
        if code and not p.code:
            p.code = code
        for attr in ("mass_norm", "mass_limit"):
            val = _dec(it.get(attr))
            if val is None or val == 0:
                continue
            doubt = sanitize.pdk_conflict(code, val)
            if doubt:                       # в графу массы попало ПДК
                rep.doubts.append(Rejected(
                    f"вещество {code or name}.{attr}", str(val), doubt, src))
                continue
            cur = getattr(p, attr)
            if cur and cur != val:
                rep.conflicts.append(Conflict(
                    f"вещество {code or name}.{attr}", str(cur), str(val), src))
            elif not cur:
                setattr(p, attr, val)
                rep.accepted.append(Accepted(
                    f"вещество {code or name}.{attr} (т)", str(val), src))


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


def _merge_passports(ctx: ReportContext, data: dict, src: str,
                     rep: ExtractionReport):
    """Паспорта отходов → extra.waste_passports (справочник по ФККО).

    Дедуп по коду ФККО; состав дополняется, если в базе его ещё нет.
    Паспорта — справочные данные (наименование/класс/состав), движение
    отходов они НЕ создают (движение — только из справок-актов)."""
    from ecodoc.core.waste_agg import norm_fkko
    store = ctx.extra.setdefault("waste_passports", [])
    for p in data.get("waste_passports") or []:
        fkko = norm_fkko(str(p.get("fkko") or ""))
        name = str(p.get("name") or "").strip()
        if not fkko and not name:
            continue
        existing = next((x for x in store
                         if norm_fkko(str(x.get("fkko") or "")) == fkko and fkko),
                        None)
        comps = [c for c in (p.get("components") or [])
                 if isinstance(c, dict) and c.get("name")]
        if existing is None:
            item = {"fkko": fkko, "name": name,
                    "hazard_class": p.get("hazard_class") or "",
                    "components": comps, "_src": src}
            store.append(item)
            rep.accepted.append(Accepted(
                "паспорт отхода → extra.waste_passports",
                f"{fkko or '—'} {name}" + (f", состав: {len(comps)} комп."
                                           if comps else ""), src))
        else:
            # дозаполняем только пустое — паспорт в базе главнее
            if not existing.get("name") and name:
                existing["name"] = name
            if not existing.get("components") and comps:
                existing["components"] = comps
                rep.accepted.append(Accepted(
                    f"состав отхода {fkko} → extra.waste_passports",
                    f"{len(comps)} комп.", src))


def _merge_sources(ctx: ReportContext, data: dict, src: str,
                   rep: ExtractionReport):
    """Источники выбросов (инвентаризация/ООС/НДВ) → extra.emission_sources."""
    from ecodoc.core import sanitize
    from ecodoc.core import sanitize_sources as ss
    store = ctx.extra.setdefault("emission_sources", [])
    for s in data.get("emission_sources") or []:
        num = ss.norm_source_number(s.get("number"))
        name = str(s.get("name") or "").strip()
        if not num and not name:
            continue
        # санитар: двери из тома ПБ, источники шума, вентсистемы из ИОС и
        # вещества-как-источники в перечень ИЗАВ не идут
        v = ss.check_source(num, name, s.get("pollutants"))
        if not v.ok:
            rep.rejected.append(Rejected("источник выбросов",
                                         f"№{num or '—'} {name}", v.reason, src))
            continue
        if v.suspect and v.reason:
            rep.doubts.append(Rejected("источник выбросов",
                                       f"№{num or '—'} {name}", v.reason, src))
        dup = next((x for x in store
                    if (num and ss.norm_source_number(x.get("number")) == num)
                    or (not num and sanitize.norm_name(x.get("name"))
                        == sanitize.norm_name(name))), None)
        if dup is not None:
            # тот же номер из другого документа — не вторая запись, а
            # доливка веществ, которых у первой ещё не было
            ss.merge_into(dup, {"pollutants": [p for p in (s.get("pollutants") or [])
                                               if isinstance(p, dict)]})
            continue
        item = {"number": num, "name": name, "kind": s.get("kind") or "",
                "pollutants": [p for p in (s.get("pollutants") or [])
                               if isinstance(p, dict)], "_src": src}
        store.append(item)
        rep.accepted.append(Accepted(
            "источник выбросов → extra.emission_sources",
            f"№{num or '—'} {name} ({len(item['pollutants'])} ЗВ)", src))


_ORG_LABEL = {"name": "наименование организации", "short_name": "краткое наименование",
              "inn": "ИНН", "kpp": "КПП", "ogrn": "ОГРН", "okpo": "ОКПО",
              "oktmo": "ОКТМО", "okved": "ОКВЭД", "address": "адрес",
              "director_name": "руководитель", "phone": "телефон", "email": "e-mail"}


def _collect(sink, data: dict, quotes: dict, pages: dict, docname: str,
             model: str, span) -> None:
    """Разложить ответ модели по кандидатам: значение + файл + лист + цитата."""
    def page_of(qkey: str) -> tuple[int, bool]:
        info = pages.get(qkey) or {}
        return int(info.get("page") or span[0]), bool(info.get("exact"))

    def put(key, value, label, qkey, unit=""):
        if value in (None, "", []):
            return
        page, exact = page_of(qkey)
        sink.add(key, value, label=label, doc="", file=docname, page=page,
                 exact=exact, quote=str(quotes.get(qkey) or ""), method="ai",
                 model=model, unit=unit)

    org = data.get("organization") or {}
    for attr, val in org.items():
        if attr in _ORG_LABEL:
            put(f"organization.{attr}", val, _ORG_LABEL[attr],
                f"organization.{attr}")
    for i, o in enumerate(data.get("objects") or []):
        code = str(o.get("code") or "").strip()
        if code:
            put(f"objects[code={code}].code", code, f"объект НВОС {code}",
                f"objects[{i}].code")
            if o.get("name"):
                put(f"objects[code={code}].name", o["name"],
                    f"объект {code}: наименование", f"objects[{i}].name")
    from ecodoc.core import sanitize
    for i, w in enumerate(data.get("wastes") or []):
        fkko = re.sub(r"\D", "", str(w.get("fkko") or ""))
        if len(fkko) != 11:
            continue
        # тот же санитар, что и на прямом слиянии: путь кандидатов раньше шёл
        # мимо него, и отбракованный там мусор возвращался в базу отсюда
        chk = sanitize.check_waste(fkko, w.get("name"), w.get("hazard_class"))
        if not chk.ok:
            continue
        name = w.get("name") or fkko
        for attr in ("generated", "transferred", "used", "neutralized"):
            put(f"wastes[fkko={fkko}].{attr}", w.get(attr),
                f"отход {name}: {attr}", f"wastes[{i}].{attr}", unit="т")
    for medium, key in (("air", "pollutants_air"), ("water", "pollutants_water")):
        for i, p in enumerate(data.get(key) or []):
            v = sanitize.check_substance(p.get("code"), p.get("name"), medium)
            if not v.ok:
                continue               # работы, потоки стоков, группы суммации
            code = v.code              # нормализованный: «301» → «0301»
            sel = f"code={code}" if code else f"name={p.get('name', '')}"
            for attr in ("mass_norm", "mass_limit", "mass_over"):
                put(f"pollutants[{medium};{sel}].{attr}", p.get(attr),
                    f"{p.get('name') or code}: {attr}", f"{key}[{i}].{attr}",
                    unit="т")
    for i, a in enumerate(data.get("disposal_acts") or []):
        fkko = re.sub(r"\D", "", str(a.get("fkko") or ""))
        mass = a.get("mass_t")
        if len(fkko) != 11 or mass in (None, ""):
            continue
        from ecodoc.intake.candidates import act_key
        base = act_key(fkko, a.get("date"), a.get("counterparty"), mass)
        put(f"{base}.mass", mass,
            f"акт {a.get('date') or ''} {fkko}: масса", f"disposal_acts[{i}].mass_t",
            unit="т")


def analyze_docs(docs: list[ExtractedDoc], ctx: ReportContext,
                 cfg: AIConfig | None = None, scope: str = "all",
                 sink=None) -> ExtractionReport:
    """Прогнать документы через LLM и слить результат в контекст.

    scope — какую категорию данных принимать из этих документов (раздельная
    загрузка: счета-фактуры не загрязняют реквизиты и т.п.):
      "all"       — всё (авто);
      "org"       — только реквизиты организации и объекты НВОС (ЕГРЮЛ/карточка);
      "acts"      — только справки-акты на отходы;
      "passports" — только паспорта отходов (ФККО/наименование/класс/состав);
      "air"       — вещества-выбросы (ООС/НДВ) и источники выбросов;
      "water"     — только вещества-сбросы (НДС/водхоз);
      "other"     — прочие документы: только extras (акты/протоколы целиком).

    Запросы к модели идут ПАРАЛЛЕЛЬНО (сетевые вызовы — потоки дают большой
    выигрыш, особенно на облачном провайдере). Слияние результатов в общий
    контекст — потом, последовательно (потокобезопасно).
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    if cfg is None:
        # «из коробки»: если ИИ ещё не настроен — настроить автоматически
        # (бесплатное облако по ключу, иначе локальная Ollama)
        from ecodoc.ai.detect import ensure_configured
        try:
            cfg = ensure_configured()
        except Exception:
            cfg = load_config()
    rep = ExtractionReport()
    if not cfg.provider:
        rep.errors.append("ИИ не настроен: задайте бесплатный ключ Cohere "
                          "(Сервис → Выбор ИИ) или установите Ollama; "
                          "в командной строке — `python -m ecodoc ai setup`")
        rep.failed_files.update(d.path.name for d in docs)
        return rep

    # список задач: чанки нарезаны ПО СТРАНИЦАМ — так у каждого найденного
    # значения есть лист-источник (для показа скана страницы пользователю)
    tasks = []
    by_name = {}
    for doc in docs:
        by_name[doc.path.name] = doc
        chunks = page_chunks(doc)
        for chunk, p_from, p_to in chunks:
            if not chunk.strip():
                continue
            where = (f" (лист {p_from})" if p_from == p_to
                     else f" (листы {p_from}–{p_to})")
            label = doc.path.name + ("" if len(chunks) == 1 else where)
            tasks.append((label, doc.path.name, chunk, p_from, p_to))

    def _ask(task):
        label, docname, chunk, p_from, p_to = task
        where = (f"страница {p_from}" if p_from == p_to
                 else f"страницы {p_from}–{p_to}")
        try:
            answer, model = chat_with_fallback(
                cfg, SYSTEM, f"Документ «{docname}», {where}:\n\n{chunk}")
            return (label, docname, chunk, _parse_json(answer), model, None,
                    (p_from, p_to))
        except (AIError, ValueError, json.JSONDecodeError) as e:
            return (label, docname, chunk, None, "", str(e), (p_from, p_to))

    # локальный провайдер (ollama) — без параллелизма (перегрузит одну модель);
    # облачный — до 6 одновременных запросов
    local = cfg.provider in ("ollama", "lmstudio")
    # у бесплатных ключей есть лимит запросов в минуту (Cohere — 20/мин):
    # умеренный параллелизм + ретрай по 429 в chat_with_fallback
    workers = 1 if local else (4 if cfg.provider == "cohere" else 6)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_ask, tasks))

    # слияние — последовательно, в порядке документов; scope определяет,
    # какие категории данных принимаются из этой партии
    from ecodoc.core.models import Medium
    for label, docname, chunk, data, model, err, span in results:
        if err:
            rep.errors.append(f"{label}: {err}")
            rep.failed_files.add(docname)
            continue
        rep.used_model = model
        quotes = _verify_quotes(data.get("quotes") or {}, chunk)
        # лист-источник для каждой цитаты: пригодится и в отчёте, и для показа
        # скана страницы; при отсутствии цитаты берём первый лист чанка
        doc_obj = by_name.get(docname)
        doc_pages = getattr(doc_obj, "pages", None) or [chunk]
        pages_seen = rep.pages.setdefault(docname, {})
        for key, q in quotes.items():
            page, exact = page_of_quote(doc_pages, q, span)
            pages_seen[key] = {"page": page, "exact": exact}
        rep.page_span[label] = span
        # находки → кандидаты (пользователь потом выберет, что взять в базу)
        if sink is not None:
            _collect(sink, data, quotes, pages_seen, docname, model, span)
        if scope in ("all", "org"):
            _merge_org(ctx, data, quotes, label, rep)
            _merge_objects(ctx, data, label, rep)
        if scope in ("all", "acts"):
            _merge_acts(ctx, data, label, rep)
            _merge_wastes(ctx, data, quotes, label, rep)
        if scope in ("all", "acts", "passports"):
            _merge_passports(ctx, data, label, rep)
        if scope in ("all", "air"):
            _merge_pollutants(ctx, data, Medium.AIR, label, rep)
            _merge_sources(ctx, data, label, rep)
        if scope in ("all", "water"):
            _merge_pollutants(ctx, data, Medium.WATER, label, rep)
        if scope in ("all", "acts", "other"):
            _store_extras(ctx, data, label, rep)
    # свернуть собранные акты в движение (акты первичны)
    if scope in ("all", "acts") and ctx.waste_acts:
        from ecodoc.core.waste_agg import (_merge_flows, _merge_receivers,
                                           aggregate_acts, period_breakdown)
        year = getattr(ctx.period, "year", None) or None
        quarter = getattr(ctx.period, "quarter", None) or None
        wastes, receivers = aggregate_acts(ctx.waste_acts, year=year, quarter=quarter)
        # слияние: акты дают образовано/передано, ручные остатки/размещение живут
        ctx.wastes = _merge_flows(ctx.wastes or [], wastes)
        if receivers:
            if not isinstance(ctx.extra, dict):
                ctx.extra = {}
            ctx.extra["waste_receivers"] = _merge_receivers(
                ctx.extra.get("waste_receivers"), receivers)
        per = f"за {year} год" if year else "период не задан (укажите год!)"
        if quarter:
            per = f"за {quarter} кв. {year}"
        rep.accepted.append(Accepted(
            "движение отходов", f"рассчитано из {len(ctx.waste_acts)} актов "
            f"({len(wastes)} видов) {per}", "агрегация"))
        # разбивка по кварталам (для контроля «данные по периодам»)
        bd = period_breakdown(ctx.waste_acts, year)
        if year and bd["total"]:
            qs = " | ".join(f"{q}кв {v:g}т" for q, v in bd["quarters"].items() if v)
            rep.accepted.append(Accepted(
                "по кварталам", f"{qs or 'даты актов не распознаны'}; "
                f"всего {bd['total']:g} т" + (f"; без даты {bd['no_date']:g} т"
                if bd["no_date"] else ""), "агрегация"))
        if not year:
            rep.errors.append("⚠ Отчётный год НЕ задан — во вкладке «Данные» "
                              "укажите год; отчётность формируется за конкретный год.")
    return rep
