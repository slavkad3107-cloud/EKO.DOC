"""Сверка отходов по источникам: ООС/ПНООЛР ↔ паспорта ↔ протоколы ↔ акты.

Замечание эколога: «ООС — основополагающий документ по отходам; протоколы
для паспортов должны быть сделаны на основе данных из него; добавить сверку
данных из ООС и других документов и протоколов исследований». Поэтому по
каждому коду ФККО собираем, ЧТО о нём говорит КАЖДЫЙ вид документа, и
показываем расхождения.

Откуда берутся сведения:
  * ctx.wastes / ctx.waste_acts — база (наименование, класс, массы актов);
  * ctx.extra['waste_passports'] — справочник из ИИ-разбора (паспорта,
    протоколы, таблицы характеристики отходов из ООС/ПНООЛР) с `_src`/`_kind`;
  * ctx.extra['lab_results'] — протоколы КХА/биотестирования;
  * ctx.extra['disposal_acts'] — акты с именем файла-источника;
  * кандидаты (intake/candidates.Store) — значения с файлом-источником:
    именно они говорят, что «норматив образования 1,2 т/год» пришёл из
    файла «ООС.pdf», а не из справки оператора.

Класс файла-источника — sources.kind_of (doc_type реестра, иначе по имени).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ecodoc.core import fkko as _fkko
from ecodoc.core.waste_agg import norm_fkko, parse_period
from ecodoc.intake import candidates, classify, sources

# группы источников в выдаче
KINDS = ("oos", "pnoolr", "passport", "protocol", "act", "journal",
         "inventory_waste", "other")
_PROJECT = ("oos", "pnoolr")                 # где заложен норматив образования
# откуда состав считается обоснованным (см. правило «з»)
_COMPOSITION_OK = frozenset({"oos", "pnoolr", "protocol", "passport"})
OVERRUN = Decimal("1.10")                    # факт > норматива более чем на 10 %


def bucket(kind: str) -> str:
    """Машинный класс документа → группа источников сверки."""
    k = str(kind or "")
    if k in ("protocol_kha", "biotest"):
        return "protocol"
    return k if k in KINDS else "other"


def _norm_name(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower().replace("ё", "е")


def _int_class(v) -> int:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return 0
    return n if 1 <= n <= 5 else 0


def _dec(v) -> Decimal | None:
    if isinstance(v, Decimal):
        return v
    s = str(v if v is not None else "").replace(",", ".").replace(" ", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return Decimal(m.group(0))
    except InvalidOperation:
        return None


def _file_of(src) -> str:
    """«имя файла (лист N)» → имя файла."""
    return str(src or "").split(" (лист")[0].strip()


def _plain(v):
    """Сериализуемое: Decimal → float, set → отсортированный список."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (set, frozenset)):
        return sorted(_plain(x) for x in v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


class _Row:
    def __init__(self, fkko: str):
        self.fkko = fkko
        self.name = ""
        self.hazard_class = 0
        self.sources: dict[str, dict] = {}
        self.raw_kinds: set[str] = set()     # классы файлов без группировки
        self.has_biotest = False
        self.composition_kinds: set[str] = set()   # откуда пришёл состав
        self.composition_files: set[str] = set()

    def src(self, kind: str) -> dict:
        return self.sources.setdefault(kind, {
            "files": set(), "names": set(), "classes": set(),
            "norm_t": None, "fact_t": None})

    def note(self, kind: str, *, file: str = "", name: str = "", hazard=None,
             raw_kind: str = ""):
        s = self.src(kind)
        if file:
            s["files"].add(file)
        if _norm_name(name):
            s["names"].add(str(name).strip())
        c = _int_class(hazard)
        if c:
            s["classes"].add(c)
        if raw_kind:
            self.raw_kinds.add(raw_kind)


def _rows_from_ctx(ctx, site_dir, rows: dict[str, _Row], kind_cache: dict):
    def kind_of(file: str) -> str:
        f = _file_of(file)
        if not f:
            return ""
        if f not in kind_cache:
            kind_cache[f] = (sources.kind_of(site_dir, f) if site_dir
                             else classify.classify_name(f).kind)
        return kind_cache[f]

    def row(code: str) -> _Row | None:
        code = norm_fkko(code)
        if not code:
            return None
        return rows.setdefault(code, _Row(code))

    # база: наименование и класс — как в контексте
    for w in ctx.wastes:
        r = row(w.fkko_code)
        if r is None:
            continue
        r.name = r.name or (w.name or "")
        r.hazard_class = r.hazard_class or _int_class(w.hazard_class)

    # акты: наименования, классы, факт за год
    year = int(getattr(ctx.period, "year", 0) or 0)
    fact: dict[str, Decimal] = {}
    for a in ctx.waste_acts:
        r = row(a.fkko_code)
        if r is None:
            continue
        r.note("act", name=a.name, hazard=a.hazard_class, raw_kind="act")
        a_year = int(getattr(a, "year", 0) or 0) or parse_period(a.date)[0]
        if not year or a_year == year:
            fact[r.fkko] = fact.get(r.fkko, Decimal("0")) + (_dec(a.mass) or Decimal("0"))
    for code, m in fact.items():
        rows[code].src("act")["fact_t"] = m
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    for d in extra.get("disposal_acts") or []:
        if not isinstance(d, dict):
            continue
        r = row(d.get("fkko"))
        if r is None:
            continue
        r.note("act", file=_file_of(d.get("_src")), name=d.get("waste_name"),
               hazard=d.get("hazard_class"), raw_kind="act")

    # справочник паспортов: класс файла-источника решает, чей это голос
    for p in extra.get("waste_passports") or []:
        if not isinstance(p, dict):
            continue
        r = row(p.get("fkko"))
        if r is None:
            continue
        file = _file_of(p.get("_src"))
        raw = p.get("_kind") or kind_of(file) or "passport"
        k = bucket(raw)
        r.note(k, file=file, name=p.get("name"), hazard=p.get("hazard_class"),
               raw_kind=raw)
        if raw == "biotest":
            r.has_biotest = True
        if [c for c in (p.get("components") or []) if isinstance(c, dict)]:
            r.composition_kinds.add(k)
            if file:
                r.composition_files.add(file)

    # протоколы лабораторий: по коду или по наименованию объекта исследования
    for lab in extra.get("lab_results") or []:
        if not isinstance(lab, dict):
            continue
        kind = str(lab.get("kind") or "").lower()
        target = str(lab.get("object") or "")
        tcode = norm_fkko(lab.get("fkko") or "") or norm_fkko(target)
        hits = [rows[tcode]] if tcode in rows else []
        if not hits and _norm_name(target):
            t = _norm_name(target)
            for r in rows.values():
                names = {_norm_name(r.name)} | {
                    _norm_name(n) for s in r.sources.values() for n in s["names"]}
                names.discard("")
                if any(n[:40] in t or t[:40] in n for n in names if len(n) > 8):
                    hits.append(r)
        for r in hits:
            r.note("protocol", file=_file_of(lab.get("_src")), raw_kind="protocol_kha")
            if "биотест" in kind:
                r.has_biotest = True

    # кандидаты: значения с файлом-источником
    if site_dir:
        for c in candidates.Store(site_dir).items:
            if c.state == candidates.REJECTED:
                continue
            coll, sel, attr = candidates.parse_key(c.key)
            if coll not in ("wastes", "waste_acts") or not sel.get("fkko"):
                continue
            # код только из кандидатов (в базе его нет) — сверяем с каталогом:
            # иначе в таблицу лезут «3 11 000 00 00 0» и прочий шум распознавания
            from ecodoc.core import sanitize
            code = norm_fkko(sel["fkko"])
            if code not in rows and not sanitize.check_waste(code).ok:
                continue
            r = row(sel["fkko"])
            if r is None:
                continue
            raw = kind_of(c.file) or "other"
            k = bucket(raw)
            r.note(k, file=_file_of(c.file), raw_kind=raw,
                   name=c.value if attr == "name" else "",
                   hazard=c.value if attr == "hazard_class" else None)
            if raw == "biotest":
                r.has_biotest = True
            if coll == "wastes" and attr == "generated" and k in _PROJECT:
                s = r.src(k)
                val = _dec(c.value)
                if val is not None and (s["norm_t"] is None
                                        or c.state == candidates.ACCEPTED):
                    s["norm_t"] = val

    # имя/класс для строк, которых нет в ctx.wastes — из любого источника
    for r in rows.values():
        if not r.name:
            for k in ("passport", "oos", "pnoolr", "act", "protocol",
                      "inventory_waste", "journal", "other"):
                names = r.sources.get(k, {}).get("names") or set()
                if names:
                    r.name = sorted(names)[0]
                    break
        if not r.hazard_class:
            for k in ("passport", "oos", "pnoolr", "act"):
                cl = r.sources.get(k, {}).get("classes") or set()
                if cl:
                    r.hazard_class = sorted(cl)[0]
                    break


def _issues(r: _Row, any_project: bool) -> list[str]:
    out: list[str] = []
    proj = {k: r.sources[k] for k in _PROJECT if k in r.sources}
    in_oos = bool(proj)
    act = r.sources.get("act")
    has_acts = bool(act and (act["files"] or act["fact_t"] is not None
                             or act["names"] or act["classes"]))
    ref_names = {_norm_name(n) for k in ("oos", "pnoolr", "passport")
                 for n in r.sources.get(k, {}).get("names", ())}
    act_names = {_norm_name(n) for n in (act or {}).get("names", ())}
    # (а) в ООС есть, актов нет
    if in_oos and not has_acts:
        out.append("в ООС/ПНООЛР предусмотрен, справок-актов за период нет")
    # (б) акты есть, в ООС нет (только когда ООС вообще загружен)
    if has_acts and not in_oos and any_project:
        out.append("передаётся по актам, но в ООС/ПНООЛР не предусмотрен")
    # (в) наименование в актах отличается от ООС/паспорта
    if act_names and ref_names and not (act_names & ref_names):
        a = sorted(act_names)[0]
        b = sorted(ref_names)[0]
        out.append(f"наименование в актах («{a}») отличается от ООС/паспорта («{b}»)")
    # (г) класс опасности расходится между источниками
    by_kind = {k: s["classes"] for k, s in r.sources.items() if s["classes"]}
    all_cls = set().union(*by_kind.values()) if by_kind else set()
    if len(all_cls) > 1:
        parts = ", ".join(f"{k}: {'/'.join(_fkko.roman(c) for c in sorted(cl))}"
                          for k, cl in sorted(by_kind.items()))
        out.append(f"класс опасности расходится между источниками ({parts})")
    # (д) факт по актам > норматива ООС более чем на 10 %
    norm = next((s["norm_t"] for k in _PROJECT
                 for s in [r.sources.get(k)] if s and s["norm_t"] is not None), None)
    fact = act["fact_t"] if act else None
    if norm is not None and fact is not None and norm > 0 and fact > norm * OVERRUN:
        out.append(f"факт по актам {fact.normalize()} т превышает норматив "
                   f"ООС/ПНООЛР {norm.normalize()} т более чем на 10 %")
    # (е) для I–IV класса нет паспорта
    has_passport = "passport" in r.raw_kinds or bool(r.sources.get("passport", {}).get("files")) \
        or "passport" in r.sources
    if 1 <= r.hazard_class <= 4 and not has_passport:
        out.append(f"класс {_fkko.roman(r.hazard_class)} — паспорта отхода нет")
    # (ж) для паспорта нет протокола; для V класса — нет биотеста
    has_protocol = "protocol" in r.sources
    if has_passport and not has_protocol:
        out.append("для паспорта нет протокола КХА (состав должен быть подтверждён "
                   "протоколом на основе ООС)")
    if r.hazard_class == 5 and not r.has_biotest:
        out.append("V класс — нет протокола биотестирования")
    # (з) состав есть, но источник состава — не ООС/протокол/паспорт
    bad = r.composition_kinds - _COMPOSITION_OK
    if bad and not (r.composition_kinds & _COMPOSITION_OK):
        files = ", ".join(sorted(r.composition_files)) or "неизвестный документ"
        out.append(f"состав отхода взят не из ООС/протокола ({files})")
    return out


def build(ctx, site_dir: str | Path | None) -> dict:
    """Сверка по каждому коду ФККО: что говорит каждый источник + замечания.

    {"rows": [{fkko, fkko_fmt, name, hazard_class, sources: {kind: {files,
    names, classes, norm_t, fact_t}}, issues: [...]}], "totals": {fkko,
    with_issues, oos_only, acts_only}, "no_oos": bool}."""
    site_dir = Path(site_dir) if site_dir else None
    rows: dict[str, _Row] = {}
    kind_cache: dict[str, str] = {}
    _rows_from_ctx(ctx, site_dir, rows, kind_cache)
    # есть ли вообще ООС/ПНООЛР среди источников площадки
    any_project = any(k in _PROJECT for k in kind_cache.values()) or any(
        k in r.sources for r in rows.values() for k in _PROJECT)
    if site_dir and not any_project:
        any_project = any(bucket(rec.get("doc_type")) in _PROJECT
                          for rec in sources.load(site_dir)["docs"].values())
    out_rows = []
    oos_only = acts_only = 0
    for code in sorted(rows):
        r = rows[code]
        issues = _issues(r, any_project)
        in_oos = any(k in r.sources for k in _PROJECT)
        has_acts = "act" in r.sources
        oos_only += in_oos and not has_acts
        acts_only += has_acts and not in_oos
        out_rows.append({
            "fkko": r.fkko, "fkko_fmt": _fkko.fmt(r.fkko), "name": r.name,
            "hazard_class": r.hazard_class,
            "sources": {k: _plain(s) for k, s in r.sources.items()},
            "issues": issues})
    return {"rows": out_rows,
            "totals": {"fkko": len(out_rows),
                       "with_issues": sum(1 for r in out_rows if r["issues"]),
                       "oos_only": oos_only, "acts_only": acts_only},
            "no_oos": not any_project}
