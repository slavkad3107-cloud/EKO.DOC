"""HTTP-сервер GUI: JSON-API поверх существующих модулей ЭКО.DOC.

Слушает ТОЛЬКО 127.0.0.1. Работа с файлами ограничена рабочим
пространством. Долгие операции (ИИ-интейк, сторож форм) идут в потоках
ThreadingHTTPServer — интерфейс не блокируется.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ecodoc import __version__
from ecodoc.core import registry, serialize, workspace

INDEX = Path(__file__).parent / "index.html"


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
        # ОКТМО по адресу (если есть токен DaData) — иначе тихо пропускаем
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
        p = tmpdir / name
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
                            use_ai=bool(body.get("ai")))
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
    report = intake.analyze_stored(body.get("names", []),
                                   body["org"], body["site"],
                                   use_ai=bool(body.get("ai")))
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
    out_dir = workspace.site_dir(body["org"], body["site"]) / "out"
    stem = f"{body['form']}_{ctx.period.year or 'XXXX'}"
    out["xml"] = str(report.render_xml(out_dir / f"{stem}.xml"))
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
    out_dir = workspace.site_dir(body["org"], body["site"]) / "out"
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


def api_compare(params, body):
    """Сравнить отходы/выбросы текущего контекста с сохранённым снимком."""
    import json as _json

    site = workspace.site_dir(body["org"], body["site"])
    snap_dir = site / "history"
    ctx = workspace.load_context(body["org"], body["site"])
    if body.get("save"):
        snap_dir.mkdir(parents=True, exist_ok=True)
        yr = ctx.period.year or "XXXX"
        from ecodoc.core import serialize
        serialize.to_json(ctx, snap_dir / f"snapshot_{yr}.json")
        return {"saved": f"snapshot_{yr}.json"}
    snaps = sorted(snap_dir.glob("snapshot_*.json")) if snap_dir.exists() else []
    if not snaps:
        return {"diffs": [], "note": "Нет сохранённых снимков для сравнения. "
                "Сохраните текущие данные снимком (кнопка «Запомнить период»)."}
    prev = _json.loads(snaps[-1].read_text(encoding="utf-8-sig"))
    diffs = []
    prev_w = {w["fkko_code"]: w for w in prev.get("wastes", [])}
    for w in ctx.wastes:
        p = prev_w.get(w.fkko_code)
        cur = float(w.generated or 0)
        old = float(p.get("generated", 0)) if p else 0
        if cur != old:
            pct = ((cur - old) / old * 100) if old else 100
            diffs.append({"kind": "отход", "name": w.name or w.fkko_code,
                          "prev": old, "cur": cur, "pct": round(pct, 1)})
    return {"diffs": diffs, "snapshot": snaps[-1].name}


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
    from ecodoc.ai.config import has_key, load_config
    cfg = load_config()
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
        save_key(provider, body["key"].strip())
    cfg = load_config()
    cfg.provider = provider
    cfg.model = (body.get("model") or "").strip() or \
        detect.CLOUD_DEFAULT_MODEL.get(provider, "")
    cfg.key_env = DEFAULT_KEY_ENV.get(provider, "")
    fb = (body.get("fallback") or "").strip()
    cfg.fallbacks = ([{"provider": fb, "model": detect.CLOUD_DEFAULT_MODEL.get(fb, "")}]
                     if fb and fb != provider else [])
    save_config(cfg)
    return {"ok": True, "text": detect.describe(load_config())}


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
    out_dir = (workspace.site_dir(org, site) / "out") if org and site \
        else Path("out")
    xl = ex.to_excel(sources, out_dir / "upraza_sources.xlsx")
    js = ex.to_json(sources, out_dir / "upraza_sources.json")
    return {"excel": str(xl), "json": str(js)}


def api_counterparty(params, body):
    from ecodoc.parsers import counterparty
    return {"text": counterparty.render(body["inn"])}


def api_oktmo(params, body):
    from ecodoc.parsers.oktmo import by_address
    return {"result": by_address(body["address"])}


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
              "reference": api_reference, "ai_config": api_ai_config}
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
               "hazard_class": api_hazard_class, "compare": api_compare,
               "devdoc": api_devdoc, "open": api_open}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # тихий лог в консоль
        pass

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
            self._json(fn(params, body))
        except Exception as e:  # ошибка — в интерфейс, не в консоль
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._route(GET_ROUTES, {})
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


def run(port: int = 8737, open_browser: bool = True):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"ЭКО.DOC GUI: {url}  (Ctrl+C — остановить)")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
