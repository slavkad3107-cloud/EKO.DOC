"""Прозрачность приёма: что откуда взято, что сомнительно, чего не хватает.

Три ответа на три вопроса эколога после загрузки документов:
  * intake_map  — по каждому файлу: разобран ли, что из него взято и В КАКОЙ
                  раздел базы (Организация/Объект/Отходы/Выбросы/Сбросы), с
                  листом-источником (снимок листа открывается по ссылке);
  * data_issues — единая «Проверка данных» по категориям: не прочитанные
                  файлы, сомнительные значения, акты без периода, коды не
                  из ФККО, неправдоподобные массы/объёмы, мусорные лицензии,
                  паспорта не из паспортов — каждая позиция с файлом, листом и
                  подсказкой, что ввести/чем заменить;
  * form_gaps   — для каждой формы: чего не хватает для генерации и как это
                  закрыть (ввести значение, перейти во вкладку, определить
                  ОКТМО по адресу).
Ничего не выдумывается: подсказки — только из каталога ФККО, разбора
периода и справочников; решение остаётся за пользователем.
"""
from __future__ import annotations

import re
from pathlib import Path

from ecodoc.core.models import ReportContext

SECTION_BY_COLL = {"organization": "Организация", "period": "Объект", "objects": "Объект",
                   "waste_acts": "Отходы", "wastes": "Отходы", "extra": "Прочее"}
TAB_BY_SECTION = {"Организация": "org", "Объект": "obj", "Отходы": "waste",
                  "Выбросы": "air", "Сбросы": "water", "Прочее": "obj"}


def _section_of(key: str) -> str:
    from ecodoc.intake.candidates import parse_key
    coll, sel, _attr = parse_key(key)
    if coll == "pollutants":
        return "Сбросы" if sel.get("medium") == "water" else "Выбросы"
    return SECTION_BY_COLL.get(coll, "Прочее")


def _image_url(org: str, site: str, doc: str, page: int) -> str:
    """Ссылка на снимок листа (страница /source уже умеет показывать)."""
    if not doc or not page:
        return ""
    from urllib.parse import quote
    return f"/source?org={quote(org)}&site={quote(site)}&doc={doc}&page={int(page)}"


# ── что откуда взято ────────────────────────────────────────────────────
def intake_map(ctx: ReportContext, site_dir: Path, org: str = "", site: str = "") -> dict:
    from ecodoc.intake import candidates, sources
    from ecodoc.intake.candidates import ACCEPTED, MANUAL, NEW, REJECTED
    docs = sources.load(site_dir).get("docs") or {}
    store = candidates.Store(site_dir)
    by_file: dict[str, dict] = {}

    def slot(file: str, doc: str = "") -> dict:
        rec = docs.get(doc) or {}
        return by_file.setdefault(file, {
            "file": file, "doc": doc or sources.sha_by_name(site_dir, file) or "",
            "method": rec.get("method", ""), "pages_total": rec.get("pages_total", 0),
            "status": "nodata", "reason": "", "taken": [], "doubts": [], "rejected": []})

    for sha, rec in docs.items():
        slot(rec.get("file", ""), sha)
    for c in store.items:
        d = slot(c.file or "—", c.doc)
        doc = d["doc"] or c.doc
        item = {"section": _section_of(c.key), "label": c.label or c.key,
                "value": c.value, "page": c.page, "key": c.key,
                "image": _image_url(org, site, doc, c.page) if (doc in docs and
                         str(c.page) in ((docs.get(doc) or {}).get("images") or {})) else ""}
        if c.state in (ACCEPTED, MANUAL):
            d["taken"].append(item)
        elif c.state == REJECTED:
            d["rejected"].append({**item, "reason": "отклонено пользователем"})
        else:                                   # NEW — ждёт решения / сомнение
            d["doubts"].append({**item, "reason": "не подтверждено — выберите значение "
                                                  "во вкладке ОБЪЕКТ → «что взять в базу»"})
    # файлы, оставшиеся в приёме (не прочитаны / ИИ не разобрал)
    att = Path(site_dir) / "attachments"
    if att.is_dir():
        for p in att.iterdir():
            if p.is_file() and not p.name.startswith("приём_") and p.name != "intake.json":
                d = slot(p.name)
                d["status"] = "unread"
                d["reason"] = "файл не разобран: не прочитался или ИИ не ответил — " \
                              "«Повторить анализ» или заведите данные вручную"
    for d in by_file.values():
        if d["status"] == "unread" and (d["taken"] or d["doubts"]):
            # файл остался в приёме (ИИ не осилил часть листов), но что-то из
            # него уже взято — это «частично», а не «не прочитан»
            d["status"] = "partial"
            d["reason"] = ("разобран частично: часть листов не прочиталась или ИИ не "
                           "ответил — «Повторить анализ» доберёт остальное")
        elif d["status"] != "unread":
            d["status"] = "ok" if d["taken"] else ("doubt" if d["doubts"] else "nodata")
        counts: dict[str, int] = {}
        for t in d["taken"]:
            counts[t["section"]] = counts.get(t["section"], 0) + 1
        d["sections"] = counts
    order = {"unread": 0, "partial": 1, "doubt": 2, "nodata": 3, "ok": 4}
    out = sorted(by_file.values(),
                 key=lambda d: (order[d["status"]], -len(d["taken"]), d["file"]))
    return {"docs": out,
            "totals": {"ok": sum(1 for d in out if d["status"] == "ok"),
                       "partial": sum(1 for d in out if d["status"] == "partial"),
                       "unread": sum(1 for d in out if d["status"] == "unread"),
                       "nodata": sum(1 for d in out if d["status"] == "nodata"),
                       "taken": sum(len(d["taken"]) for d in out),
                       "doubts": sum(len(d["doubts"]) for d in out)}}


# ── единая проверка данных по категориям ────────────────────────────────
def _act_source(store_items, act) -> tuple[str, str, int]:
    """Файл/документ/лист акта — по кандидату с тем же ФККО и массой."""
    from ecodoc.core.waste_agg import norm_fkko
    from ecodoc.intake.candidates import _norm_value, parse_key
    code = norm_fkko(act.fkko_code)
    m = _norm_value("x.mass", act.mass)
    for c in store_items:
        coll, sel, _a = parse_key(c.key)
        if coll == "waste_acts" and sel.get("fkko") == code and sel.get("m") == m:
            return c.file, c.doc, c.page
    return "", "", 0


def data_issues(ctx: ReportContext, site_dir: Path, org: str = "", site: str = "") -> dict:
    from ecodoc.core import fkko, sanitize
    from ecodoc.core import sanitize_records as recs
    from ecodoc.core.waste_agg import act_period, norm_fkko
    from ecodoc.intake import candidates, crosscheck, sources
    cats: dict[str, list] = {k: [] for k in ("Отходы", "Выбросы", "Сбросы", "Объект", "Организация")}
    docs = sources.load(site_dir).get("docs") or {}
    store = candidates.Store(site_dir)

    def img(doc, page):
        return _image_url(org, site, doc, page) if (doc in docs and str(page) in
                                                    ((docs.get(doc) or {}).get("images") or {})) else ""

    # 1) не прочитанные файлы — во все категории попадать не должны: одна запись «Объект»
    im = intake_map(ctx, site_dir, org, site)
    for d in im["docs"]:
        if d["status"] == "unread":
            cats["Объект"].append({"kind": "unread", "label": d["file"], "value": "",
                                   "reason": d["reason"], "suggest": "", "file": d["file"],
                                   "doc": d["doc"], "page": 0, "image": "",
                                   "fix": {"type": "tab", "tab": "intake"}})
    # 2) неподтверждённые/спорные кандидаты
    for g in crosscheck.group(store.items, ctx):
        if not g.is_question and g.current:
            continue
        sec = _section_of(g.key)
        vals = g.values or []
        first = vals[0] if vals else {}
        doc = (first.get("docs") or [""])[0] if isinstance(first.get("docs"), list) else ""
        page = (first.get("pages") or [0])[0] if isinstance(first.get("pages"), list) else 0
        cats.setdefault(sec, []).append({
            "kind": "doubt", "label": g.label, "value": " / ".join(str(v.get("value")) for v in vals[:3]),
            "reason": g.hint or ("разные значения в документах" if g.is_question else "ждёт подтверждения"),
            "suggest": str(first.get("value", "")), "file": "", "doc": doc, "page": page,
            "image": img(doc, page),
            "fix": {"type": "decide", "key": g.key,
                    "options": [{"value": str(v.get("value")), "label": ", ".join(v.get("docs") or [])[:60]}
                                for v in vals[:4]]}})
    # 3) отходы: коды не из ФККО, акты без периода, неправдоподобные т/м³, лицензии
    for r in fkko.check_context(ctx):
        if r["ok"] and not r.get("name_mismatch"):
            continue
        sug = (r.get("suggest") or [])
        cats["Отходы"].append({
            "kind": "bad_code", "label": f"{fkko.fmt(r['code'])} {r['our_name'] or ''}"[:80],
            "value": r["code"], "reason": r["problem"] or r["note"] or "наименование расходится с каталогом",
            "suggest": (sug[0]["code_fmt"] + " " + sug[0]["name"][:50]) if sug else "",
            "file": "", "doc": "", "page": 0, "image": "",
            "fix": {"type": "replace", "key": r["code"],
                    "options": [{"value": s["code"], "label": f"{s['code_fmt']} {s['name'][:50]}"} for s in sug]}})
    for i, a in enumerate(ctx.waste_acts):
        y, q, mo = act_period(a)
        f, doc, page = _act_source(store.items, a)
        label = f"акт {fkko.fmt(a.fkko_code)} {(a.name or '')[:30]} — {a.mass} т"
        akey = candidates.act_key(a.fkko_code, a.date, a.receiver, a.mass)
        if not y:
            cats["Отходы"].append({
                "kind": "missing_period", "label": label, "value": a.date or "",
                "reason": "период акта не распознан — без него масса не попадает в разбивку "
                          "и годовые формы", "suggest": "",
                "file": f, "doc": doc, "page": page, "image": img(doc, page),
                "fix": {"type": "input", "key": akey + ".date", "path": f"waste_acts[{i}].date",
                        "placeholder": "15.03.2025 / 3 кв 2025 / март 2025"}})
        prob = recs.act_plausibility_problem(a)
        if prob:
            cats["Отходы"].append({
                "kind": "implausible", "label": label, "value": f"{a.mass} т / {a.volume_m3} м³",
                "reason": prob, "suggest": "", "file": f, "doc": doc, "page": page,
                "image": img(doc, page),
                "fix": {"type": "tab", "tab": "waste", "path": f"waste_acts[{i}].mass"}})
        for fld in ("license", "carrier_license"):
            lp = recs.license_problem(getattr(a, fld))
            if lp:
                cats["Отходы"].append({
                    "kind": "license", "label": label, "value": getattr(a, fld), "reason": lp,
                    "suggest": "", "file": f, "doc": doc, "page": page, "image": img(doc, page),
                    "fix": {"type": "input", "key": akey + "." + fld,
                            "path": f"waste_acts[{i}].{fld}", "placeholder": "№ лицензии, дата"}})
    for r in recs.check_passports(ctx):
        if not r["problems"]:
            continue
        cats["Отходы"].append({
            "kind": "passport_source", "label": f"паспорт {r['fkko_fmt']} {r['name'][:40]}",
            "value": r["src"], "reason": "; ".join(r["problems"]), "suggest": "",
            "file": r["src"], "doc": "", "page": 0, "image": "",
            "fix": {"type": "clean", "only": "passports"} if not r["src_ok"] else {"type": "tab", "tab": "waste"}})
    # 4) вещества: подозрительные/отклонённые по санитару
    aud = sanitize.audit_context(ctx)
    for row in aud["pollutants"]:
        if row["ok"] and not row.get("suspect"):
            continue
        sec = "Сбросы" if row["medium"] == "water" else "Выбросы"
        cats[sec].append({
            "kind": "doubt", "label": f"{row['code'] or '—'} {row['name'][:50]}", "value": row.get("mass", ""),
            "reason": row["reason"], "suggest": row.get("norm_code", ""), "file": "", "doc": "",
            "page": 0, "image": "",
            "fix": {"type": "clean", "only": "pollutants"} if not row["ok"] else
                   {"type": "tab", "tab": TAB_BY_SECTION[sec]}})
    # 5) объект и организация
    for ob in aud.get("objects") or []:
        if ob.get("problem"):
            cats["Объект"].append({"kind": "object_code", "label": ob["code"], "value": ob.get("name", ""),
                                   "reason": ob["problem"], "suggest": "", "file": "", "doc": "",
                                   "page": 0, "image": "", "fix": {"type": "tab", "tab": "obj"}})
    if not ctx.period.year:
        cats["Объект"].append({"kind": "doubt", "label": "Отчётный год", "value": "",
                               "reason": "не указан — без него не собирается ни одна годовая форма",
                               "suggest": "", "file": "", "doc": "", "page": 0, "image": "",
                               "fix": {"type": "input", "key": "period.year", "path": "period.year",
                                       "placeholder": "2025"}})
    orgp = (aud.get("organization") or {}).get("short_name_problem")
    if orgp:
        cats["Организация"].append({"kind": "short_name", "label": "Краткое наименование",
                                    "value": ctx.organization.short_name, "reason": orgp,
                                    "suggest": aud["organization"].get("short_name_suggest", ""),
                                    "file": "", "doc": "", "page": 0, "image": "",
                                    "fix": {"type": "input", "key": "organization.short_name",
                                            "path": "organization.short_name",
                                            "options": [{"value": aud["organization"].get("short_name_suggest", ""),
                                                         "label": "предложение"}]}})
    totals = {k: len(v) for k, v in cats.items()}
    totals["all"] = sum(totals.values())
    return {"categories": cats, "totals": totals}


# ── чего не хватает формам ──────────────────────────────────────────────
def _fix_for(path: str) -> dict:
    """Как закрыть пробел: по адресу поля понятно, куда вести пользователя."""
    p = path.split("|")[0]
    if p == "organization.oktmo":
        return {"type": "action", "action": "oktmo", "path": p}
    if p.startswith("organization."):
        return {"type": "input", "path": p, "tab": "org"}
    if p == "period.year":
        return {"type": "input", "path": p, "tab": "obj", "placeholder": "2025"}
    if p.startswith("objects"):
        return {"type": "tab", "tab": "obj", "path": p}
    if p.startswith(("wastes", "waste_acts")):
        return {"type": "tab", "tab": "waste", "path": p}
    if p.startswith("pollutants") or p.startswith("extra.air"):
        return {"type": "tab", "tab": "air", "path": p}
    if p.startswith("extra.water") or p.startswith("extra.discharge"):
        return {"type": "tab", "tab": "water", "path": p}
    return {"type": "input", "path": p}


def form_gaps(ctx: ReportContext) -> dict:
    from ecodoc.core import registry
    from ecodoc.intake import requirements
    registry.load_all()
    out = {}
    for code, cls in registry.all_reports().items():
        req = requirements.REQUIREMENTS.get(code) or {}
        missing = []
        for entry in req.get("fields") or []:
            path, label = entry[0], entry[1]
            hint = entry[2] if len(entry) > 2 else ""
            if any(requirements._filled(requirements._get_path(ctx, p)) for p in path.split("|")):
                continue
            missing.append({"label": label, "path": path.split("|")[0], "hint": hint,
                            "fix": _fix_for(path)})
        errors, warnings = [], []
        try:
            rep = cls(ctx)
            for i in rep.validate() or []:
                (errors if i.level == "error" else warnings).append(f"[{i.field}] {i.message}")
        except Exception as e:                     # форма не собирается на пустых данных
            errors.append(f"проверка не выполнена: {e}")
        out[code] = {"title": getattr(cls, "title", code),
                     "domain": getattr(cls, "domain", "reporting"),
                     "ok": not missing and not errors, "missing": missing,
                     "errors": errors, "warnings": warnings, "docs": req.get("docs") or []}
    return {"forms": out}
