"""HTTP-сервер GUI: JSON-API поверх существующих модулей ЭКО.DOC.

Слушает ТОЛЬКО 127.0.0.1. Работа с файлами ограничена рабочим
пространством. Долгие операции (ИИ-интейк, сторож форм) идут в потоках
ThreadingHTTPServer — интерфейс не блокируется.
"""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ecodoc import __version__
from ecodoc.core import registry, serialize, workspace

INDEX = Path(__file__).parent / "index.html"
SOURCE = Path(__file__).parent / "source.html"   # просмотр листа-источника


def _forms() -> list[dict]:
    registry.load_all()
    return [{"code": code,
             "title": cls.title,
             "domain": getattr(cls, "domain", "reporting"),
             "implemented": bool(getattr(cls, "implemented", True)),
             "devdoc": bool(getattr(cls, "devdoc", False))}
            for code, cls in registry.all_reports().items()]


def _ctx_path(org: str, site: str) -> Path:
    p = workspace.site_dir(org, site) / "context.json"
    if not p.exists():
        raise FileNotFoundError(f"Нет площадки {org}/{site}")
    return p


# ── обработчики API: name -> fn(params, body) -> dict ────────────────────

def api_meta(params, body):
    from ecodoc.ai.config import load_config
    cfg = load_config()
    return {"version": __version__,
            "forms": _forms(),
            "workspace": str(workspace.root().resolve()),
            "results": str(workspace.results_root()),
            "ai": {"provider": cfg.provider, "model": cfg.model,
                   "fallbacks": cfg.fallbacks}}


def api_orgs(params, body):
    return {"orgs": workspace.list_tree()}


def api_org_lookup(params, body):
    """Реквизиты по ИНН из ЕГРЮЛ (открытый сервис ФНС)."""
    from ecodoc.parsers.egrul import lookup
    return {"requisites": lookup(body["inn"])}


def api_org_add(params, body):
    known = ("short_name", "inn", "kpp", "ogrn", "oktmo", "address",
             "director_name", "director_position")
    name = (body.get("name") or "").strip()
    req = {k: body.get(k, "") for k in known}
    if not name and body.get("inn"):
        # только ИНН — подтягиваем реквизиты из ЕГРЮЛ
        from ecodoc.parsers.egrul import lookup
        found = lookup(body["inn"])
        name = found.get("short_name") or found.get("name", "")
        for k in known:
            req[k] = req[k] or found.get(k, "")
        # ОКТМО по адресу: оффлайн-справочник (бесплатно) → DaData (если токен);
        # не нашли — тихо пропускаем, впишется вручную
        if req.get("address") and not req.get("oktmo"):
            try:
                from ecodoc.parsers.oktmo import by_address
                req["oktmo"] = by_address(req["address"]).get("oktmo", "")
            except Exception:
                pass
    if not name:
        return {"error": "Укажите название или ИНН."}
    path = workspace.add_org(name, **req)
    # площадка — по полному адресу (свой ввод или юрадрес из ЕГРЮЛ)
    site_addr = (body.get("site_address") or "").strip() or req.get("address", "")
    out = {"ok": True, "path": str(path), "org": workspace.slug(name), "site": ""}
    if site_addr:
        site_name = (body.get("site_name") or "").strip() or site_addr
        workspace.add_site(name, site_name, address=site_addr)
        out["site"] = workspace.slug(site_name)
    else:
        out["note"] = ("Площадка не создана: укажите полный адрес площадки "
                       "(поле «адрес площадки»).")
    return out


def api_site_add(params, body):
    address = (body.get("address") or "").strip()
    name = (body.get("name") or "").strip() or address
    if not name:
        return {"error": "Укажите полный адрес площадки."}
    path = workspace.add_site(body["org"], name, address=address or name)
    return {"ok": True, "path": str(path),
            "org": workspace.slug(body["org"]),
            "site": workspace.slug(name)}


def api_site_del(params, body):
    dest = workspace.delete_site(body["org"], body["site"])
    return {"ok": True, "trash": str(dest)}


def api_org_del(params, body):
    dest = workspace.delete_org(body["org"])
    return {"ok": True, "trash": str(dest)}


def api_context_get(params, body):
    p = _ctx_path(params["org"], params["site"])
    return {"context": json.loads(p.read_text(encoding="utf-8-sig")),
            "path": str(p)}


def api_context_save(params, body):
    from ecodoc.intake import intake
    if intake.is_busy(body["org"], body["site"]):
        return {"error": "Идёт приём документов по этой площадке — дождитесь "
                         "окончания анализа и повторите сохранение (иначе "
                         "правки перезапишут друг друга)."}
    p = _ctx_path(body["org"], body["site"])
    # прогон через модель: битый JSON/типы отловятся до записи
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(body["context"], ensure_ascii=False, indent=2),
                   encoding="utf-8")
    ctx = serialize.from_json(tmp)
    tmp.unlink(missing_ok=True)
    # save_context также пишет реквизиты организации в org.json (иначе
    # правки блока organization во вкладке «Данные» терялись бы)
    workspace.save_context(body["org"], body["site"], ctx)
    return {"ok": True}


def _decode_to_tmp(files: list[dict], tmpdir: Path) -> list[str]:
    paths = []
    for i, f in enumerate(files):
        name = Path(str(f["name"]).replace("\\", "/")).name  # только имя
        if not name or name in (".", ".."):
            name = f"файл_{i + 1}"
        # каждый файл в свой подкаталог: при загрузке «папки целиком»
        # одноимённые файлы из разных подпапок не должны затирать друг друга
        sub = tmpdir / str(i)
        sub.mkdir(exist_ok=True)
        p = sub / name
        p.write_bytes(base64.b64decode(f["b64"]))
        paths.append(str(p))
    return paths


def _save_report(org: str, site: str, report: str) -> None:
    from datetime import datetime
    rep_dir = workspace.site_dir(org, site) / "attachments"
    rep_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    (rep_dir / f"приём_{stamp}.txt").write_text(report, encoding="utf-8")


def api_intake(params, body):
    """Небольшой пакет файлов: сохранить + сразу проанализировать."""
    import shutil

    from ecodoc.intake import intake
    tmpdir = Path(tempfile.mkdtemp(prefix="ecodoc_upload_"))
    try:
        paths = _decode_to_tmp(body.get("files", []), tmpdir)
        report = intake.run(paths, org=body["org"], site=body["site"],
                            use_ai=bool(body.get("ai")),
                            scope=body.get("scope", "all"))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    _save_report(body["org"], body["site"], report)
    return {"report": report}


def api_intake_upload(params, body):
    """Партия файлов большой папки: только сохранить в attachments."""
    import shutil

    from ecodoc.intake import intake
    tmpdir = Path(tempfile.mkdtemp(prefix="ecodoc_upload_"))
    try:
        paths = _decode_to_tmp(body.get("files", []), tmpdir)
        names, log = intake.store(paths, body["org"], body["site"])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return {"stored": names, "log": log}


def api_intake_run(params, body):
    """Анализ ранее сохранённых файлов (после всех партий)."""
    from ecodoc.intake import intake
    if intake.is_busy(body["org"], body["site"]):
        return {"error": "Приём по этой площадке уже идёт — дождитесь окончания."}
    report = intake.analyze_stored(body.get("names", []),
                                   body["org"], body["site"],
                                   use_ai=bool(body.get("ai")),
                                   scope=body.get("scope", "all"))
    _save_report(body["org"], body["site"], report)
    return {"report": report}


def _get_form(code: str):
    registry.load_all()
    try:
        return registry.get(code)
    except KeyError:
        raise ValueError(f"Неизвестная форма: {code}")


def api_validate(params, body):
    cls = _get_form(body["form"])
    ctx = workspace.load_context(body["org"], body["site"])
    issues = cls(ctx).validate()
    return {"issues": [{"level": i.level, "field": i.field, "message": i.message}
                       for i in issues]}


def api_validate_all(params, body):
    """Проверить контекст сразу под все реализованные формы."""
    registry.load_all()
    ctx = workspace.load_context(body["org"], body["site"])
    out = {}
    for code, cls in registry.all_reports().items():
        if not getattr(cls, "implemented", True):
            continue
        issues = cls(ctx).validate()
        out[code] = [{"level": i.level, "field": i.field, "message": i.message}
                     for i in issues]
    return {"results": out}


def api_generate(params, body):
    cls = _get_form(body["form"])
    ctx = workspace.load_context(body["org"], body["site"])
    report = cls(ctx)
    if not getattr(report, "implemented", True):
        return {"error": f"Форма «{report.title}» — каркас, генерация недоступна."}
    issues = report.validate()
    errors = [i for i in issues if i.level == "error"]
    out = {"issues": [{"level": i.level, "field": i.field, "message": i.message}
                      for i in issues]}
    from ecodoc.calendar.engine import deadline_note
    note = deadline_note(body["form"], ctx.period.year)
    if note:
        out["deadline"] = note
    if errors and not body.get("force"):
        out["error"] = "Есть ошибки — исправьте данные или включите «принудительно»."
        return out
    out_dir = workspace.results_dir(body["org"], body["site"])
    stem = f"{body['form']}_{ctx.period.year or 'XXXX'}"
    if getattr(report, "has_xml", True):
        out["xml"] = str(report.render_xml(out_dir / f"{stem}.xml"))
    else:
        out["xml_note"] = "форма не выгружается в ЛКПП — только печатная форма"
    try:
        print_path = report.render_print(out_dir / f"{stem}.xlsx")
        out["print"] = str(print_path)
        if body.get("pdf"):
            from ecodoc.render.pdf import to_pdf
            try:
                out["pdf"] = str(to_pdf(print_path))
            except RuntimeError as e:
                out["pdf_error"] = str(e)
    except NotImplementedError:
        pass
    return out


def api_submit(params, body):
    """Собрать пакет к подаче в ЛКПП: XML + печать + МЧД + ЧЕКЛИСТ.md."""
    from ecodoc.submit import build_package
    cls = _get_form(body["form"])
    ctx = workspace.load_context(body["org"], body["site"])
    report = cls(ctx)
    if not getattr(report, "implemented", True):
        return {"error": f"Форма «{report.title}» — каркас, подача недоступна."}
    out_dir = workspace.results_dir(body["org"], body["site"])
    res = build_package(report, out_dir)
    return {
        "dir": str(res["dir"]),
        "files": {k: str(v) for k, v in res["files"].items()},
        "checklist": str(res["checklist"]),
        "issues": [{"level": i.level, "field": i.field, "message": i.message}
                   for i in res["issues"]],
        "errors": len(res["errors"]),
    }


def api_settings(params, body):
    """Настройки хранения: папка результатов (локальная для этой машины)."""
    if body.get("results_dir"):
        p = Path(body["results_dir"]).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"error": f"Не удалось создать папку: {e}"}
        workspace.set_results_root(str(p))
    return {"results": str(workspace.results_root()),
            "workspace": str(workspace.root().resolve())}


def api_cleanup(params, body):
    """Освободить место в базе: удалить out и старые исходники attachments."""
    res = workspace.cleanup_base(days=int(body.get("days", 7)))
    mb = res["freed"] / (1024 * 1024)
    return {"freed_mb": round(mb, 1), "files": res["files"]}


def api_waste_summary(params, body):
    """Сводная таблица по отходам из справок-актов (форма «Справки-2025»)."""
    from ecodoc.core.waste_summary import build_xlsx
    ctx = workspace.load_context(body["org"], body["site"])
    if not ctx.waste_acts:
        return {"error": "Справок-актов нет — заполните таблицу «Справки-акты» "
                         "в Данных или загрузите справки в Приёме."}
    out_dir = workspace.results_dir(body["org"], body["site"])
    year = ctx.period.year or ""
    path = build_xlsx(ctx, out_dir / f"сводная_отходы_{year or 'все_годы'}.xlsx")
    return {"path": str(path), "acts": len(ctx.waste_acts)}


def api_missing(params, body):
    """Чего не хватает по формам — для чек-листов модулей."""
    from ecodoc.intake import requirements
    src = body if (body or {}).get("org") else params
    ctx = workspace.load_context(src["org"], src["site"])
    out = {}
    for form in requirements.REQUIREMENTS:
        missing, docs_hint = requirements.check(ctx, form)
        out[form] = {"missing": missing, "docs": docs_hint}
    return {"forms": out}


def api_calendar(params, body):
    from datetime import date

    from ecodoc.calendar import engine
    ctx = workspace.load_context(params["org"], params["site"])
    year = int(params.get("year") or 0) or \
        (ctx.period.year + 1 if ctx.period.year else 0)
    if not year:
        return {"error": "Укажите год (или заполните period.year в данных)."}
    periodic, possession = engine.build_calendar(ctx, year)
    today = date.today()
    rows = []
    for e in periodic:
        days = (e.due - today).days
        status = ("overdue" if days < 0 else "soon" if days <= 30 else "ok")
        rows.append({"date": e.due.strftime("%d.%m.%Y"), "title": e.title,
                     "where": e.where, "coverage": e.coverage,
                     "days": days, "status": status})
    docs = [{"title": e.title, "where": e.where, "basis": e.basis}
            for e in possession]
    out = {"rows": rows, "docs": docs, "year": year,
           "text": engine.render_console(ctx, year)}
    if params.get("ics"):
        out["ics"] = engine.export_ics_text(ctx, year)
    return out


def api_reference(params, body):
    """Справочники для автоподстановки: вещества и частые отходы."""
    from ecodoc.core.refdata import common_wastes, substances
    return {"substances": substances(), "wastes": common_wastes()}


def api_devdoc(params, body):
    """Сгенерировать документ разработки (.docx): НМУ или программа ПЭК."""
    ctx = workspace.load_context(body["org"], body["site"])
    out_dir = workspace.results_dir(body["org"], body["site"])
    kind = body.get("kind")
    if kind == "nmu":
        from ecodoc.development import nmu
        path = nmu.generate(ctx, out_dir / "план_НМУ.docx")
    elif kind == "pek-program":
        from ecodoc.development import pek_program
        path = pek_program.generate(ctx, out_dir / "программа_ПЭК.docx")
    else:
        return {"error": f"неизвестный документ: {kind}"}
    return {"path": str(path)}


def api_hazard_class(params, body):
    from ecodoc.development.hazard_class import Component, calculate
    comps = [Component(name=c.get("name", ""), ci=float(c.get("ci") or 0),
                       wi=float(c.get("wi") or 0))
             for c in body.get("components", []) if c.get("name")]
    if not comps:
        return {"error": "Добавьте компоненты отхода (наименование, Ci, Wi)."}
    r = calculate(comps)
    return {"k_total": r.k_total, "hazard_class": r.hazard_class,
            "components": r.components, "warnings": r.warnings}


def api_watch(params, body):
    from ecodoc.watch import watcher
    return {"text": watcher.run_check()}


def api_ai_setup(params, body):
    from ecodoc.ai import detect
    cfg = detect.setup(prefer=body.get("provider", ""))
    return {"text": detect.describe(cfg)}


def api_ai_config(params, body):
    """Всё для панели выбора ИИ: провайдеры, модели, наличие ключей, текущий выбор."""
    from ecodoc.ai import detect
    from ecodoc.ai.config import has_key
    # заодно приводим конфиг к рабочему виду: не настроен — настроить,
    # локальный при наличии бесплатного ключа — перевести на облако (1 раз)
    cfg = detect.ensure_configured()
    providers = []
    for pid in detect.PROVIDER_LABEL:
        local = pid in ("ollama", "lmstudio")
        providers.append({
            "id": pid, "label": detect.PROVIDER_LABEL[pid],
            "local": local, "has_key": True if local else has_key(pid),
            "models": detect.KNOWN_MODELS.get(pid, []),
            "default": detect.CLOUD_DEFAULT_MODEL.get(pid, "")})
    return {"provider": cfg.provider, "model": cfg.model,
            "fallbacks": cfg.fallbacks, "providers": providers,
            "ollama_models": detect._ollama_models(),
            "lmstudio_models": []}


def api_ai_save(params, body):
    """Сохранить выбор провайдера/модели (+ключ и запасной провайдер)."""
    from ecodoc.ai import detect
    from ecodoc.ai.config import (DEFAULT_KEY_ENV, load_config, save_config,
                                  save_key)
    provider = (body.get("provider") or "").strip()
    if provider not in detect.PROVIDER_LABEL:
        return {"error": f"Неизвестный провайдер: {provider}"}
    if body.get("key"):
        # shared=True — ключ в общую базу (OneDrive): один раз на всех компах
        save_key(provider, body["key"].strip(), shared=bool(body.get("shared")))
    cfg = load_config()
    cfg.provider = provider
    cfg.model = (body.get("model") or "").strip() or \
        detect.CLOUD_DEFAULT_MODEL.get(provider, "")
    cfg.key_env = DEFAULT_KEY_ENV.get(provider, "")
    fb = (body.get("fallback") or "").strip()
    cfg.fallbacks = ([{"provider": fb, "model": detect.CLOUD_DEFAULT_MODEL.get(fb, "")}]
                     if fb and fb != provider else [])
    # выбор сделан руками — авто-переход на бесплатное облако больше не нужен
    det = cfg.detected if isinstance(cfg.detected, dict) else {}
    det["free_migrated"] = True
    cfg.detected = det
    save_config(cfg)
    return {"ok": True, "text": detect.describe(load_config())}


_SHA_RE = re.compile(r"^[0-9a-f]{16,40}$")


def _source_paths(src: dict) -> tuple[Path, str, int, dict]:
    """Проверить параметры запроса листа-источника и вернуть безопасный путь.

    Защита как в api_open: sha1 — только hex, номер листа — целое,
    итоговый путь обязан лежать внутри папки площадки."""
    from ecodoc.intake import sources
    from ecodoc.parsers import page_image
    org, site = src.get("org", ""), src.get("site", "")
    doc = str(src.get("doc", "")).lower()
    if not org or not site or not _SHA_RE.match(doc):
        raise ValueError("неверные параметры листа-источника")
    raw_page = src.get("page")
    try:
        # именно так, а не `or 1`: явный 0 — это ошибка, а не «первый лист»
        page = 1 if raw_page in (None, "") else int(raw_page)
    except (TypeError, ValueError):
        raise ValueError("неверный номер листа")
    if not 1 <= page <= 9999:
        raise ValueError("неверный номер листа")
    site_dir = workspace.site_dir(org, site).resolve()
    rec = sources.doc_by_sha(site_dir, doc) or {}
    name = (rec.get("images") or {}).get(str(page), "")
    if not name:
        return Path(), doc, page, rec
    path = (page_image.pages_dir(site_dir) / name).resolve()
    path.relative_to(site_dir)                     # бросит, если вышли наружу
    return path, doc, page, rec


def api_source_page(params, body):
    """Картинка листа-источника (image/jpeg)."""
    path, _doc, _page, _rec = _source_paths(body if (body or {}).get("doc") else params)
    if not path or not path.is_file():
        return {"error": "лист не сохранён (исходник уже удалён или формат без картинки)"}
    return Raw(path.read_bytes(), "image/jpeg")


def api_source_meta(params, body):
    """Сведения о документе и листе: имя файла, способ разбора, что найдено."""
    src = body if (body or {}).get("doc") else params
    path, doc, page, rec = _source_paths(src)
    ctx = workspace.load_context(src["org"], src["site"])
    found = []
    for fld, info in (ctx.provenance.get("_pages") or {}).get(rec.get("file"), {}).items():
        if isinstance(info, dict) and int(info.get("page") or 0) == page:
            found.append({"field": fld, "exact": bool(info.get("exact"))})
    images = rec.get("images") or {}
    nums = sorted(int(k) for k in images)
    return {"file": rec.get("file", ""), "method": rec.get("method", ""),
            "page_kind": rec.get("page_kind", "page"),
            "pages_total": rec.get("pages_total", 0),
            "doc_type": rec.get("doc_type", ""), "page": page,
            "has_image": bool(path and path.is_file()),
            "found": found, "doc": doc,
            "prev": max([n for n in nums if n < page], default=0),
            "next": min([n for n in nums if n > page], default=0)}


def api_org_verify(params, body):
    """Сверить реквизиты организации с ЕГРЮЛ: что совпало, что разошлось.

    Требование ТЗ: «если есть из загрузки необходимые данные то сверь с базой
    налоговой; если нет предложи ввести ИНН и загрузи»."""
    from ecodoc.parsers.egrul import lookup
    org_name, site = body.get("org", ""), body.get("site", "")
    ctx = workspace.load_context(org_name, site) if org_name and site else None
    org = ctx.organization if ctx else None
    inn = (body.get("inn") or (org.inn if org else "")).strip()
    if not inn:
        return {"error": "Укажите ИНН — по нему подтянем реквизиты из ЕГРЮЛ.",
                "need_inn": True}
    try:
        found = lookup(inn)
    except Exception as e:
        return {"error": f"ЕГРЮЛ недоступен: {str(e)[:160]}"}
    if not found:
        return {"error": f"В ЕГРЮЛ ничего не найдено по ИНН {inn}"}
    fields = ("name", "short_name", "inn", "kpp", "ogrn", "address",
              "director_name", "director_position")
    rows = []
    for f in fields:
        ours = str(getattr(org, f, "") or "") if org else ""
        theirs = str(found.get(f, "") or "")
        if not theirs and not ours:
            continue
        same = _norm_req(ours) == _norm_req(theirs)
        rows.append({"field": f, "ours": ours, "egrul": theirs,
                     "same": same, "empty": not ours})
    return {"inn": inn, "rows": rows, "egrul": found,
            "diff": sum(1 for r in rows if not r["same"] and not r["empty"]),
            "empty": sum(1 for r in rows if r["empty"] and r["egrul"])}


def _norm_req(value: str) -> str:
    return re.sub(r"[\s\"'«»,.]+", " ", str(value or "")).strip().lower()


def api_object_check(params, body):
    """Проверка объекта: формат кода НВОС + ОКТМО/ОКАТО по адресу."""
    from ecodoc.core import nvos
    code = (body.get("code") or "").strip()
    address = (body.get("address") or "").strip()
    out = {"code": nvos.normalize(code), "valid": nvos.is_valid(code),
           "problem": nvos.problem(code), "region": nvos.region(code),
           "category": nvos.category(code)}
    if address:
        try:
            from ecodoc.parsers.oktmo import by_address
            hit = by_address(address)
            out["oktmo"] = hit.get("oktmo", "")
            out["okato"] = hit.get("okato", "")
            out["oktmo_source"] = hit.get("source", "")
        except Exception as e:
            out["oktmo_error"] = str(e)[:200]
    return out


def api_candidates(params, body):
    """Найденные данные на выбор: значение, источник (файл + лист), статус."""
    from ecodoc.intake import candidates, crosscheck
    src = body if (body or {}).get("org") else params
    org, site = src["org"], src["site"]
    site_dir = workspace.site_dir(org, site)
    ctx = workspace.load_context(org, site)
    store = candidates.Store(site_dir)
    groups = crosscheck.group(store.items, ctx)
    pending = {g.key for g in groups}
    out_groups = []
    for g in groups:
        out_groups.append({
            "key": g.key, "label": g.label, "status": g.status, "hint": g.hint,
            "current": g.current,
            "values": [{"value": v["value"], "docs": v["docs"],
                        "pages": v["pages"][:3]} for v in g.values],
            "question": g.is_question})
    asks = [{"path": a.path, "label": a.label, "question": a.question,
             "forms": a.forms, "docs": a.docs}
            for a in crosscheck.asks(ctx, None, pending)]
    return {"groups": out_groups, "asks": asks,
            "lab_gaps": crosscheck.lab_gaps(ctx),
            "counts": {"total": len(store.items),
                       "questions": sum(1 for g in groups if g.is_question),
                       "asks": len(asks)}}


def api_candidate_decide(params, body):
    """Решение пользователя: взять это значение в базу или отклонить группу."""
    from ecodoc.intake import candidates, crosscheck, intake
    org, site = body["org"], body["site"]
    if intake.is_busy(org, site):
        return {"error": "Идёт загрузка документов по этой площадке — "
                         "дождитесь окончания."}
    site_dir = workspace.site_dir(org, site)
    ctx = workspace.load_context(org, site)
    store = candidates.Store(site_dir)
    applied, failed = [], []
    for d in body.get("decisions") or []:
        key = d.get("key") or ""
        if d.get("action") == "reject":
            crosscheck.decide(ctx, store, key, "", accept=False)
            continue
        ok = crosscheck.decide(ctx, store, key, str(d.get("value", "")))
        (applied if ok else failed).append(key)
    if applied:
        workspace.save_context(org, site, ctx)
    return {"applied": applied, "failed": failed}


def api_candidate_manual(params, body):
    """Пользователь ввёл значение сам (в документах его не нашлось)."""
    from ecodoc.intake import candidates, crosscheck, intake
    org, site = body["org"], body["site"]
    if intake.is_busy(org, site):
        return {"error": "Идёт загрузка документов — дождитесь окончания."}
    site_dir = workspace.site_dir(org, site)
    ctx = workspace.load_context(org, site)
    store = candidates.Store(site_dir)
    key = body.get("key") or body.get("path") or ""
    if not crosscheck.manual(ctx, store, key, str(body.get("value", "")),
                             body.get("label", "")):
        return {"error": f"Не удалось записать значение в поле {key}"}
    workspace.save_context(org, site, ctx)
    return {"ok": True, "key": key}


def api_sources(params, body):
    """Разобранные документы площадки: что нашли и с каких листов (для ЗАГРУЗКИ)."""
    from ecodoc.intake import sources
    src = body if (body or {}).get("org") else params
    site_dir = workspace.site_dir(src["org"], src["site"])
    ctx = workspace.load_context(src["org"], src["site"])
    by_file = ctx.provenance.get("_pages") or {}
    out = []
    for sha, rec in sources.load(site_dir)["docs"].items():
        fields = by_file.get(rec.get("file"), {})
        pages = sorted({int(v["page"]) for v in fields.values()
                        if isinstance(v, dict) and v.get("page")})
        images = {int(k): v for k, v in (rec.get("images") or {}).items()}
        out.append({"doc": sha, "file": rec.get("file", ""),
                    "method": rec.get("method", ""),
                    "page_kind": rec.get("page_kind", "page"),
                    "pages_total": rec.get("pages_total", 0),
                    "found": len(fields), "fields": sorted(fields),
                    "pages": pages,
                    "image_pages": sorted(images),
                    "size": rec.get("size", 0)})
    out.sort(key=lambda r: (-r["found"], r["file"]))
    return {"docs": out, "total": len(out)}


def api_intake_url(params, body):
    """Загрузка исходника ПО ССЫЛКЕ (требование ТЗ: doc/pdf/jpg/XML/zip/папка/ссылка)."""
    import shutil
    import tempfile
    import urllib.request

    from ecodoc.intake import intake
    url = (body.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return {"error": "Укажите ссылку, начинающуюся с http:// или https://"}
    tmpdir = Path(tempfile.mkdtemp(prefix="ecodoc_url_"))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EcoDoc/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            head = resp.headers
            name = ""
            disp = head.get("Content-Disposition") or ""
            m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disp)
            if m:
                name = urllib.parse.unquote(m.group(1)).strip()
            if not name:
                name = Path(urllib.parse.urlparse(url).path).name or "файл_по_ссылке"
            size = int(head.get("Content-Length") or 0)
            if size > 300 * 1024 * 1024:
                return {"error": f"файл больше 300 МБ ({size // 1024 // 1024} МБ)"}
            dst = tmpdir / Path(name).name
            with open(dst, "wb") as f:
                shutil.copyfileobj(resp, f, 1024 * 256)
        names, log = intake.store([str(dst)], body["org"], body["site"])
        return {"stored": names, "log": log, "file": dst.name}
    except Exception as e:
        return {"error": f"не удалось скачать: {str(e)[:200]}"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def api_ai_health(params, body):
    """Состояние всех моделей: работает / лимит / нет ключа + кто выбран.

    По умолчанию отдаём кэш (проверка всех моделей — это десятки сетевых
    запросов); `refresh: true` — прогнать проверку заново и выбрать лучшую.
    """
    from ecodoc.ai import health, registry
    src = body if (body or {}).get("refresh") is not None else params
    refresh = str((src or {}).get("refresh", "")).lower() in ("1", "true", "yes")
    if refresh:
        results = health.check_all()
        cfg = health.apply_best(results)
    else:
        results = health.fresh()
        cfg = None
    checked, _ = health.load_cache()
    rows = []
    for h in sorted(results, key=lambda x: (not x.ok, x.tier, x.sec or 999)):
        spec = registry.by_id(h.id) or registry.by_id(h.provider)
        rows.append({"id": h.id, "provider": h.provider, "model": h.model,
                     "tier": h.tier, "tier_label": registry.tier_label(h.tier),
                     "ok": h.ok, "sec": h.sec, "reason": h.reason,
                     "limit": spec.limit if spec else "",
                     "score": spec.score if spec else "",
                     "label": spec.label if spec else h.id})
    working = [h.id for h in health.ranked_working(results)]
    from ecodoc.ai.config import load_config
    cfg = cfg or load_config()
    return {"checked": checked, "items": rows, "working": working,
            "current": {"provider": cfg.provider, "model": cfg.model,
                        "fallbacks": cfg.fallbacks},
            "text": health.summary(results) if results else ""}


def api_ai_task(params, body):
    """Доп. задание модели вручную по данным раздела (окно в каждом разделе)."""
    from ecodoc.ai.task import run_task
    task = (body.get("task") or "").strip()
    if not task:
        return {"error": "Напишите, что нужно сделать с данными раздела."}
    ctx = workspace.load_context(body["org"], body["site"])
    try:
        return run_task(ctx, body.get("scope") or "all", task,
                        apply_changes=bool(body.get("apply")),
                        org=body["org"], site=body["site"])
    except Exception as e:
        return {"error": str(e)[:300]}


def api_ai_test(params, body):
    from ecodoc.ai import load_config
    from ecodoc.ai.providers import chat_with_fallback
    answer, model = chat_with_fallback(
        load_config(), "Отвечай кратко, по-русски.",
        body.get("prompt") or "Назови класс опасности отработанных ртутных ламп.")
    return {"model": model, "answer": answer}


def api_dispersion(params, body):
    from ecodoc.development import dispersion as dp
    known = dp.PointSource.__dataclass_fields__
    data = body.get("data") or {}
    raw = data.get("sources", []) if isinstance(data, dict) else data
    sources = [dp.PointSource(**{k: v for k, v in s.items() if k in known})
               for s in raw]
    if not sources:
        return {"error": "Нет источников."}
    pdk = data.get("pdk") if isinstance(data, dict) else None
    return {"text": dp.report(sources, pdk)}


def _map_sources(body):
    from ecodoc.development.dispersion_map import MapSource
    data = body.get("data") or {}
    raw = data.get("sources", []) if isinstance(data, dict) else data
    known = MapSource.__dataclass_fields__
    return [MapSource(**{k: v for k, v in s.items() if k in known}) for s in raw]


def api_dispersion_map(params, body):
    from ecodoc.development import dispersion_map as dm
    sources = _map_sources(body)
    if not sources:
        return {"error": "Нет источников."}
    grid = dm.compute_grid(sources, substance=body.get("substance"),
                           n=int(body.get("n", 40)), dirs=int(body.get("dirs", 16)))
    return {"svg": dm.render_svg(grid), "summary": dm.summary(grid),
            "share_max": grid.share_max, "cmax": grid.cmax}


def api_upraza_export(params, body):
    from ecodoc.development import dispersion_export as ex
    sources = _map_sources(body)
    if not sources:
        return {"error": "Нет источников."}
    org, site = body.get("org"), body.get("site")
    out_dir = workspace.results_dir(org, site) if org and site else Path("out")
    xl = ex.to_excel(sources, out_dir / "upraza_sources.xlsx")
    js = ex.to_json(sources, out_dir / "upraza_sources.json")
    return {"excel": str(xl), "json": str(js)}


def api_counterparty(params, body):
    from ecodoc.parsers import counterparty
    return {"text": counterparty.render(body["inn"])}


def api_oktmo(params, body):
    from ecodoc.parsers.oktmo import OktmoError, by_address
    try:
        return {"result": by_address(body["address"])}
    except OktmoError as e:
        return {"error": str(e)}


def api_open(params, body):
    """Открыть папку/файл в проводнике — только внутри workspace."""
    target = Path(body["path"]).resolve()
    root = workspace.root().resolve()
    try:
        target.relative_to(root)  # строго внутри (префикс-трюки не проходят)
    except ValueError:
        return {"error": "Путь вне рабочего пространства."}
    if not target.exists():
        return {"error": "Не существует."}
    if not hasattr(os, "startfile"):  # не-Windows
        return {"error": f"Откройте вручную: {target}"}
    os.startfile(target if target.is_dir() else target.parent)  # noqa: S606
    return {"ok": True}


GET_ROUTES = {"meta": api_meta, "orgs": api_orgs,
              "context": api_context_get, "calendar": api_calendar,
              "reference": api_reference, "ai_config": api_ai_config,
              "ai_health": api_ai_health,
              "source_page": api_source_page,
              "source_meta": api_source_meta,
              "sources": api_sources, "candidates": api_candidates}
POST_ROUTES = {"org_add": api_org_add, "org_lookup": api_org_lookup,
               "site_add": api_site_add, "site_del": api_site_del,
               "org_del": api_org_del,
               "context_save": api_context_save, "intake": api_intake,
               "intake_upload": api_intake_upload, "intake_run": api_intake_run,
               "validate": api_validate, "validate_all": api_validate_all,
               "generate": api_generate,
               "watch": api_watch, "ai_setup": api_ai_setup,
               "ai_config": api_ai_config, "ai_save": api_ai_save,
               "ai_test": api_ai_test, "dispersion": api_dispersion,
               "dispersion_map": api_dispersion_map,
               "upraza_export": api_upraza_export,
               "counterparty": api_counterparty, "oktmo": api_oktmo,
               "hazard_class": api_hazard_class,
               "devdoc": api_devdoc, "submit": api_submit, "open": api_open,
               "waste_summary": api_waste_summary, "missing": api_missing,
               "settings": api_settings, "cleanup": api_cleanup,
               "ai_health": api_ai_health, "ai_task": api_ai_task,
               "intake_url": api_intake_url,
               "source_page": api_source_page,
               "source_meta": api_source_meta, "sources": api_sources,
               "candidates": api_candidates,
               "candidate_decide": api_candidate_decide,
               "candidate_manual": api_candidate_manual,
               "org_verify": api_org_verify,
               "object_check": api_object_check}


class Raw:
    """Не-JSON ответ (картинка листа-источника, страница просмотра)."""

    def __init__(self, data: bytes, ctype: str, max_age: int = 86400):
        self.data, self.ctype, self.max_age = data, ctype, max_age


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # тихий лог в консоль
        pass

    def _raw(self, r: "Raw"):
        self.send_response(200)
        self.send_header("Content-Type", r.ctype)
        self.send_header("Content-Length", str(len(r.data)))
        if r.max_age:
            self.send_header("Cache-Control", f"max-age={r.max_age}")
        self.end_headers()
        self.wfile.write(r.data)

    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _route(self, routes, body):
        u = urllib.parse.urlparse(self.path)
        name = u.path.removeprefix("/api/")
        params = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        fn = routes.get(name)
        if not fn:
            return self._json({"error": f"нет такого API: {name}"}, 404)
        try:
            out = fn(params, body)
            return self._raw(out) if isinstance(out, Raw) else self._json(out)
        except Exception as e:  # ошибка — в интерфейс, не в консоль
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._route(GET_ROUTES, {})
        # отдельная страница просмотра листа-источника
        if urllib.parse.urlparse(self.path).path == "/source":
            data = SOURCE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        # всё остальное — одна страница
        data = INDEX.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self._json({"error": "POST только в /api/"}, 404)
        # защита от CSRF/DNS-rebinding: чужой сайт в браузере может слать
        # fetch на 127.0.0.1 без preflight (text/plain). Требуем настоящий
        # JSON-запрос и локальный Host.
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self._json({"error": "запрос не с localhost"}, 403)
        ctype = (self.headers.get("Content-Type") or "")
        if not ctype.startswith("application/json"):
            return self._json({"error": "нужен Content-Type: application/json"}, 415)
        length = int(self.headers.get("Content-Length") or 0)
        if length > 512 * 1024 * 1024:  # base64-пакет папки; больше — явно не то
            return self._json({"error": "запрос больше 512 МБ — загрузите частями"}, 413)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except json.JSONDecodeError as e:
            return self._json({"error": f"битый JSON: {e}"}, 400)
        self._route(POST_ROUTES, body)


def _startup_ai_check():
    """Проверка моделей при запуске (требование ТЗ) — в фоне, чтобы окно
    открывалось сразу. Если прошлая проверка ещё свежа, ничего не опрашиваем."""
    try:
        from ecodoc.ai import health
        if health.fresh():
            return
        results = health.check_all()
        cfg = health.apply_best(results)
        working = health.ranked_working(results)
        if working:
            print(f"ИИ: выбрана {cfg.provider}/{cfg.model} "
                  f"(рабочих моделей {len(working)} из {len(results)})")
        else:
            print("ИИ: ни одна модель не ответила — Сервис → Модели ИИ")
    except Exception as e:                      # проверка не должна ломать запуск
        print(f"ИИ: проверка моделей не выполнена ({e})")


def run(port: int = 8737, open_browser: bool = True):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"ЭКО.DOC GUI: {url}  (Ctrl+C — остановить)")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    threading.Thread(target=_startup_ai_check, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
