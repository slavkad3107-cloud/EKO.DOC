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
             "implemented": bool(getattr(cls, "implemented", True))}
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
    # сразу создаём площадку — без неё работать нельзя
    site = (body.get("site") or "Основная").strip() or "Основная"
    workspace.add_site(name, site)
    # интерфейсу возвращаем имена как на диске (слаги) — для выбора в дереве
    return {"ok": True, "path": str(path),
            "org": workspace.slug(name), "site": workspace.slug(site)}


def api_site_add(params, body):
    path = workspace.add_site(body["org"], body["name"])
    return {"ok": True, "path": str(path),
            "org": workspace.slug(body["org"]),
            "site": workspace.slug(body["name"])}


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
    serialize.from_json(tmp)
    tmp.replace(p)
    return {"ok": True}


def api_intake(params, body):
    """Файлы приходят base64 (браузер) → временная папка → intake.run."""
    import shutil
    from datetime import datetime

    from ecodoc.intake import intake
    tmpdir = Path(tempfile.mkdtemp(prefix="ecodoc_upload_"))
    try:
        paths = []
        for i, f in enumerate(body.get("files", [])):
            name = Path(str(f["name"]).replace("\\", "/")).name  # только имя
            if not name or name in (".", ".."):
                name = f"файл_{i + 1}"
            p = tmpdir / name
            p.write_bytes(base64.b64decode(f["b64"]))
            paths.append(str(p))
        report = intake.run(paths, org=body["org"], site=body["site"],
                            use_ai=bool(body.get("ai")))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    # отчёт приёма — в архив площадки (история: что и когда приносили)
    rep_dir = workspace.site_dir(body["org"], body["site"]) / "attachments"
    rep_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    (rep_dir / f"приём_{stamp}.txt").write_text(report, encoding="utf-8")
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
    from ecodoc.calendar import engine
    ctx = workspace.load_context(params["org"], params["site"])
    year = int(params.get("year") or 0) or \
        (ctx.period.year + 1 if ctx.period.year else 0)
    if not year:
        return {"error": "Укажите год (или заполните period.year в данных)."}
    out = {"text": engine.render_console(ctx, year), "year": year}
    if params.get("ics"):
        out["ics"] = engine.export_ics_text(ctx, year)
    return out


def api_watch(params, body):
    from ecodoc.watch import watcher
    return {"text": watcher.run_check()}


def api_ai_setup(params, body):
    from ecodoc.ai import detect
    cfg = detect.setup(prefer=body.get("provider", ""))
    return {"text": detect.describe(cfg)}


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
                           n=int(body.get("n", 50)))
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
              "context": api_context_get, "calendar": api_calendar}
POST_ROUTES = {"org_add": api_org_add, "org_lookup": api_org_lookup,
               "site_add": api_site_add,
               "context_save": api_context_save, "intake": api_intake,
               "validate": api_validate, "validate_all": api_validate_all,
               "generate": api_generate,
               "watch": api_watch, "ai_setup": api_ai_setup,
               "ai_test": api_ai_test, "dispersion": api_dispersion,
               "dispersion_map": api_dispersion_map,
               "upraza_export": api_upraza_export,
               "counterparty": api_counterparty, "oktmo": api_oktmo,
               "open": api_open}


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
