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


def render_index() -> bytes:
    """index.html с подставленной версией — интерфейс сверяет её с API и
    просит Ctrl+F5, если браузер показал устаревшую страницу."""
    return INDEX.read_bytes().replace(b"__ECODOC_VERSION__", __version__.encode("utf-8"))
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
            "startup": dict(STARTUP_NOTES),
            "ai": {"provider": cfg.provider, "model": cfg.model,
                   "fallbacks": cfg.fallbacks,
                   "picked_by": (cfg.detected or {}).get("picked_by", "")
                   if isinstance(cfg.detected, dict) else "",
                   "auto_pick": (cfg.detected or {}).get("auto_pick", True) is not False
                   if isinstance(cfg.detected, dict) else True}}


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


def _ctx_version(p: Path) -> str:
    """Отпечаток файла данных: по нему ловим правку из другого окна/компьютера."""
    try:
        st = p.stat()
        return f"{int(st.st_mtime_ns)}-{st.st_size}"
    except OSError:
        return ""


def api_context_get(params, body):
    p = _ctx_path(params["org"], params["site"])
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    # подпись периода для каждого акта («3 кв 2025», «март 2025», дата) —
    # GUI группирует акты по годам и показывает период вместо сырой даты;
    # считаем здесь, чтобы у старых актов без полей year/quarter/month
    # подпись тоже была (разбор даты/текста периода)
    try:
        from ecodoc.core.models import WasteAct
        from ecodoc.core.waste_agg import act_period, period_label
        for a in data.get("waste_acts") or []:
            if not isinstance(a, dict):
                continue
            act = WasteAct(date=str(a.get("date") or ""), year=int(a.get("year") or 0),
                           quarter=int(a.get("quarter") or 0), month=int(a.get("month") or 0))
            y, q, mo = act_period(act)
            a["year"], a["quarter"], a["month"] = y, q, mo
            a["period_label"] = period_label(act)
    except Exception:
        pass
    return {"context": data, "path": str(p), "version": _ctx_version(p)}


def api_context_save(params, body):
    from ecodoc.intake import intake
    if intake.is_busy(body["org"], body["site"]):
        return {"error": "Идёт приём документов по этой площадке — дождитесь "
                         "окончания анализа и повторите сохранение (иначе "
                         "правки перезапишут друг друга)."}
    p = _ctx_path(body["org"], body["site"])
    # база лежит в общей папке OneDrive и открывается с нескольких компьютеров:
    # если файл изменился с момента чтения, молча затирать чужие правки нельзя
    want = str(body.get("version") or "")
    have = _ctx_version(p)
    if want and have and want != have:
        return {"error": "Данные этой площадки изменились в другом окне или на "
                         "другом компьютере после того, как вы их открыли. "
                         "Чтобы не затереть чужие правки, нажмите «Перечитать», "
                         "сверьте и внесите своё заново.",
                "conflict": True, "version": have}
    # прогон через модель: битый JSON/типы отловятся до записи
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(body["context"], ensure_ascii=False, indent=2),
                   encoding="utf-8")
    ctx = serialize.from_json(tmp)
    tmp.unlink(missing_ok=True)
    # пустые строки актов («+ акт» без заполнения) в базу не пишем
    before = len(ctx.waste_acts)
    ctx.waste_acts = [a for a in ctx.waste_acts
                      if (a.fkko_code or "").strip() or (a.name or "").strip()
                      or a.mass or a.volume_m3]
    dropped = before - len(ctx.waste_acts)
    # save_context также пишет реквизиты организации в org.json (иначе
    # правки блока organization во вкладке «Данные» терялись бы)
    workspace.save_context(body["org"], body["site"], ctx)
    _ISSUES_CACHE.pop((body["org"], body["site"]), None)
    return {"ok": True, "version": _ctx_version(p), "dropped_empty_acts": dropped}


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
    """Отчёт приёма на диск.

    Большая папка грузится частями, и все отчёты за сеанс дописываются в ОДИН
    файл: при метке времени до минуты части затирали друг друга, и список
    непрочитанных файлов терялся."""
    from datetime import datetime
    rep_dir = workspace.site_dir(org, site) / "attachments"
    rep_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = rep_dir / f"приём_{now:%Y-%m-%d}.txt"
    head = f"\n\n{'=' * 60}\n[{now:%H:%M:%S}] партия\n{'=' * 60}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(head + report)


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
        names, log = intake.store(paths, body["org"], body["site"],
                                  batch=str(body.get("batch") or ""))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return {"stored": names, "log": log}


def api_intake_run(params, body):
    """Анализ ранее сохранённых файлов (после всех партий)."""
    from ecodoc.intake import intake
    if intake.is_busy(body["org"], body["site"]):
        return {"error": "Приём по этой площадке уже идёт — дождитесь окончания."}
    struct: dict = {}
    report = intake.analyze_stored(body.get("names", []),
                                   body["org"], body["site"],
                                   use_ai=bool(body.get("ai")),
                                   scope=body.get("scope", "all"),
                                   struct=struct)
    _save_report(body["org"], body["site"], report)
    return {"report": report, "sections": struct}


def api_models_refresh(params, body):
    """Обновить список моделей OpenRouter вручную (Сервис → Выбор ИИ)."""
    from ecodoc.ai import detect
    res = detect.refresh_openrouter_models(timeout=int(body.get("timeout") or 15))
    STARTUP_NOTES["models"] = res
    return res


def api_ai_autopick(params, body):
    """Кнопка «Автовыбор по результатам проверки»: взять свежие результаты
    (или проверить заново), применить лучшую и подтвердить."""
    from ecodoc.ai import health
    from ecodoc.ai import registry as _reg
    from ecodoc.ai.config import load_config, save_config
    results = health.fresh() if not body.get("recheck") else []
    if not results:
        results = health.check_all(_reg.all_specs())
    cfg = health.apply_best(results)
    working = health.ranked_working(results)
    note = _ai_note(cfg, results, f"выбрана оптимальная: {cfg.provider}/{cfg.model} "
                    f"(рабочих моделей {len(working)} из {len(results)})", False)
    STARTUP_NOTES["ai"] = note
    # автовыбор по кнопке — снова «авто» (галочку не трогаем)
    c2 = load_config()
    det = c2.detected if isinstance(c2.detected, dict) else {}
    det["picked_by"] = "health"
    c2.detected = det
    save_config(c2)
    return note


def api_intake_forget(params, body):
    """Удалить файл из приёма вместе с тем, что из него взято (ЗАГРУЗКА)."""
    from ecodoc.intake import intake
    if intake.is_busy(body["org"], body["site"]):
        return {"error": "Идёт приём по этой площадке — дождитесь окончания."}
    name = Path(str(body.get("file") or "").replace("\\", "/")).name
    if not name:
        return {"error": "не указан файл"}
    return intake.forget(body["org"], body["site"], name)


def api_intake_unexclude(params, body):
    """Снять исключение с документа (после «удалить файл»), чтобы его можно
    было загрузить заново."""
    from ecodoc.intake import sources
    sha = str(body.get("sha") or "").lower()
    if not _SHA_RE.match(sha):
        return {"error": "неверный идентификатор документа"}
    ok = sources.unexclude(workspace.site_dir(body["org"], body["site"]), sha)
    return {"ok": ok}


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


def _inside(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)      # строго внутри (префикс-трюки не проходят)
        return True
    except ValueError:
        return False


def _keep_previous(out_dir: Path, stem: str, out: dict) -> None:
    """Отложить прежнюю версию документа вместо молчаливой перезаписи.

    Готовую форму часто дорабатывают руками в Excel; повторная генерация
    затирала её без следа. Прежний файл переименовывается с меткой времени."""
    from datetime import datetime
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    saved = []
    for ext in (".xlsx", ".xml", ".pdf"):
        old = out_dir / f"{stem}{ext}"
        if not old.exists():
            continue
        try:
            keep = out_dir / f"{stem}_до-{stamp}{ext}"
            old.replace(keep)
            saved.append(keep.name)
        except OSError:
            # файл открыт в Excel — скажем об этом человеческим языком
            out["busy"] = (f"Файл {old.name} открыт в другой программе — "
                           f"закройте его и повторите генерацию.")
    if saved:
        out["kept"] = saved


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
    # без отчётного года документ сдать нельзя: помечаем его черновиком, а не
    # выпускаем молча с «XXXX» в имени и нулевым годом внутри
    year = ctx.period.year
    stem = (f"{body['form']}_{year}" if year
            else f"ЧЕРНОВИК_{body['form']}_год-не-указан")
    if not year:
        out["draft"] = ("Отчётный год не указан — выпущен ЧЕРНОВИК. Заполните "
                        "год во вкладке ОТЧЁТНОСТЬ и сгенерируйте заново.")
    _keep_previous(out_dir, stem, out)
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
    res = build_package(report, out_dir, force=bool(body.get("force")))
    return {
        "dir": str(res["dir"]),
        "files": {k: str(v) for k, v in res["files"].items()},
        "checklist": str(res["checklist"]),
        "issues": [{"level": i.level, "field": i.field, "message": i.message}
                   for i in res["issues"]],
        "errors": len(res["errors"]),
        "blocked": bool(res.get("blocked")),
        "note": res.get("note", ""),
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


def api_storage(params, body):
    """Где держать базу: общая (OneDrive) или только на этом компьютере."""
    mode = (body or {}).get("mode")
    if mode:
        try:
            res = workspace.set_storage_mode(mode)
        except Exception as e:
            return {"error": str(e)[:300]}
        return {**res, "results": str(workspace.results_root())}
    return {"mode": workspace.storage_mode(),
            "root": str(workspace.root().resolve()),
            "results": str(workspace.results_root()),
            "onedrive": bool(workspace._onedrive())}


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


def api_audit_data(params, body):
    """Разбор данных площадки: что мусор, что спорно, где дубли (не меняет)."""
    from ecodoc.core import sanitize
    src = body if (body or {}).get("org") else params
    ctx = workspace.load_context(src["org"], src["site"])
    return sanitize.audit_context(ctx)


def api_clean_data(params, body):
    """Убрать мусор из данных площадки. Перед правкой — резервная копия."""
    import shutil
    from datetime import datetime

    from ecodoc.core import sanitize
    org, site = body["org"], body["site"]
    ctx = workspace.load_context(org, site)
    path = workspace.site_dir(org, site) / "context.json"
    backup = ""
    if path.exists():                       # данные эколога — сначала копия
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        bak = path.with_name(f"context.до-очистки-{stamp}.json")
        shutil.copy2(path, bak)
        backup = str(bak)
    only = str(body.get("only") or "")
    if only == "passports":
        # кнопка «Убрать не из паспортов» во вкладке ОТХОДЫ — трогаем только
        # паспорта, остальное (вещества/отходы/акты) не пересматриваем
        from ecodoc.core import sanitize_records as recs
        rep = {"removed_passports": recs.clean_passports(
            ctx, drop_bad_source=body.get("drop_bad", True),
            drop_dupes=body.get("drop_dupes", True))}
    else:
        rep = sanitize.clean_context(
            ctx,
            drop_bad=body.get("drop_bad", True),
            drop_dupes=body.get("drop_dupes", True),
            drop_empty=bool(body.get("drop_empty")))
    workspace.save_context(org, site, ctx)
    rep["backup"] = backup
    rep["left"] = {"pollutants": len(ctx.pollutants), "wastes": len(ctx.wastes)}
    return rep


def api_disk_usage(params, body):
    """Сколько места занимает база и что именно в ней лежит."""
    root = workspace.root()
    if not root.exists():
        return {"total_mb": 0, "rows": []}

    def size_of(p: Path) -> int:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

    rows, total = [], 0
    for org_d in sorted(root.iterdir()):
        if not org_d.is_dir() or org_d.name.startswith("."):
            continue
        for site_d in sorted(org_d.iterdir()):
            if not site_d.is_dir() or not (site_d / "context.json").exists():
                continue
            att = site_d / "attachments"
            pages = site_d / "pages"
            src = size_of(att) if att.is_dir() else 0
            pg = size_of(pages) if pages.is_dir() else 0
            data = size_of(site_d) - src - pg
            files = sum(1 for f in att.rglob("*") if f.is_file()) if att.is_dir() else 0
            total += src + pg + data
            rows.append({"org": org_d.name, "site": site_d.name,
                         "sources_mb": round(src / 1048576, 1),
                         "sources_files": files,
                         "pages_mb": round(pg / 1048576, 1),
                         "data_mb": round(data / 1048576, 1)})
    trash = root / ".корзина"
    trash_mb = round(size_of(trash) / 1048576, 1) if trash.is_dir() else 0
    return {"total_mb": round(total / 1048576, 1), "rows": rows,
            "trash_mb": trash_mb, "root": str(root)}


def api_waste_table(params, body):
    """«Табличка по отходам» (т/м³ по классам) — по бланку пользователя."""
    from ecodoc.core.waste_table import build_xlsx, rows
    ctx = workspace.load_context(body["org"], body["site"])
    data = rows(ctx)
    if not data:
        return {"error": "Перечень отходов пуст — загрузите справки-акты или "
                         "заполните вкладку «ОТХОДЫ»."}
    out_dir = workspace.results_dir(body["org"], body["site"])
    year = ctx.period.year or ""
    path = build_xlsx(ctx, out_dir / f"табличка_отходы_{year or 'все_годы'}.xlsx")
    no_rho = sum(1 for r in data if r["mass"] and not r["density"])
    return {"path": str(path), "rows": len(data), "no_density": no_rho}


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
        if e.done:
            status = "done"
        else:
            status = ("overdue" if days < 0 else "soon" if days <= 30 else "ok")
        row = {"date": e.due.strftime("%d.%m.%Y"), "title": e.title,
               "where": e.where, "coverage": e.coverage, "code": e.code,
               "days": days, "status": status, "done": e.done}
        if e.due_norm and e.due_norm != e.due:
            row["moved_from"] = e.due_norm.strftime("%d.%m")
        rows.append(row)
    docs = [{"title": e.title, "where": e.where, "basis": e.basis}
            for e in possession]
    out = {"rows": rows, "docs": docs, "year": year,
           "text": engine.render_console(ctx, year)}
    if params.get("ics"):
        out["ics"] = engine.export_ics_text(ctx, year)
    return out


def api_mark_submitted(params, body):
    """Отметить обязанность как сданную (или снять отметку)."""
    org, site = body["org"], body["site"]
    ctx = workspace.load_context(org, site)
    code, year = str(body.get("code") or ""), int(body.get("year") or 0)
    if not code or not year:
        return {"error": "не указаны форма и год"}
    marks = (ctx.extra or {}).setdefault("submitted", {})
    key = f"{code}:{year}"
    note = str(body.get("note") or "").strip()
    if note:
        marks[key] = note
    else:
        marks.pop(key, None)
    workspace.save_context(org, site, ctx)
    return {"ok": True, "marks": marks}


def api_reference(params, body):
    """Справочники для автоподстановки: вещества и частые отходы."""
    from ecodoc.core.refdata import common_wastes, substances
    return {"substances": substances(), "wastes": common_wastes()}


def _year_suffix(ctx) -> str:
    """«_2025» или пусто — чтобы в имени файла не болтался хвост «_»."""
    return f"_{ctx.period.year}" if ctx.period.year else ""


def api_devdoc(params, body):
    """Сгенерировать документ разработки (.docx): НМУ или программа ПЭК."""
    ctx = workspace.load_context(body["org"], body["site"])
    out_dir = workspace.results_dir(body["org"], body["site"])
    kind = body.get("kind")
    if kind == "nmu":
        from ecodoc.development import nmu
        path = nmu.generate(ctx, out_dir / "план_НМУ.docx")
        return {"path": str(path), "gaps": nmu.gaps(ctx)}
    elif kind == "pek-program":
        from ecodoc.development import pek_program
        path = pek_program.generate(ctx, out_dir / "программа_ПЭК.docx")
        return {"path": str(path), "gaps": pek_program.gaps(ctx)}
    elif kind == "waste-inventory":
        # отчёт .docx (титул, разделы, таблицы) + перечень .xlsx рядом
        from ecodoc.development import waste_inventory
        return waste_inventory.generate_all(ctx, out_dir)
    elif kind == "air-inventory":
        from ecodoc.development import air_inventory
        path = air_inventory.generate(
            ctx, out_dir / f"инвентаризация_выбросов{_year_suffix(ctx)}.xlsx")
    elif kind == "pnoolr":
        # текстовая часть .docx по приказу № 1021 + расчётная часть .xlsx
        from ecodoc.development import pnoolr
        return pnoolr.generate_all(ctx, out_dir)
    elif kind == "tu-waste":
        from ecodoc.development import tu_waste
        receiver = str(body.get("receiver") or "")
        stage = str(body.get("stage") or "строительство")
        path = tu_waste.generate(ctx, out_dir / f"запрос_ТУ{_year_suffix(ctx)}.docx",
                                 receiver=receiver, purpose=str(body.get("purpose") or ""),
                                 stage=stage)
        return {"path": str(path), "gaps": tu_waste.gaps(ctx, receiver, stage)}
    elif kind == "oos":
        from ecodoc.development import oos
        path = oos.generate(ctx, out_dir / f"раздел_ООС{_year_suffix(ctx)}.docx",
                            stage=body.get("stage", "эксплуатация"))
        return {"path": str(path), "gaps": oos.gaps(ctx)}
    elif kind == "plarn":
        from ecodoc.development import plarn
        path = plarn.generate(ctx, out_dir / "ПЛАРН.docx")
        return {"path": str(path), "gaps": plarn.gaps(ctx)}
    elif kind == "dvos":
        from ecodoc.development import dvos
        path = dvos.generate(ctx, out_dir / f"ДВОС{_year_suffix(ctx)}.docx")
        return {"path": str(path), "gaps": dvos.gaps(ctx)}
    elif kind == "waste-passport":
        from ecodoc.development import waste_passport
        made = waste_passport.generate(ctx, out_dir / "паспорта")
        if not made:
            return {"error": "Нет отходов I–IV класса — паспорта не требуются."}
        # использованные сведения (состав в %, происхождение, адрес) — в базу:
        # расчёт класса и справки состава видят сгенерированные паспорта
        try:
            waste_passport.remember_details(ctx)
            workspace.save_context(body["org"], body["site"], ctx)
        except Exception:
            pass
        return {"path": str(made[0].parent), "files": [p.name for p in made],
                "gaps": waste_passport.gaps(ctx)}
    elif kind == "waste-composition":
        # справка о составе по ООС/ПНООЛР — проект для протокола КХА
        from ecodoc.development import waste_composition
        site_dir = workspace.site_dir(body["org"], body["site"])
        made = waste_composition.generate(ctx, out_dir / "состав_отходов",
                                          site_dir=site_dir)
        note = _oos_note(ctx, site_dir)
        if not made:
            return {"error": "Нет отходов с компонентным составом — загрузите "
                             "ООС/ПНООЛР или протоколы КХА.",
                    "note": note, "gaps": [note] * bool(note) + waste_composition.gaps(ctx)}
        return {"path": str(made[0].parent), "files": [p.name for p in made],
                "note": note, "gaps": waste_composition.gaps(ctx)}
    else:
        return {"error": f"неизвестный документ: {kind}"}
    return {"path": str(path)}


def _hazard_class_from_passport(body):
    """Режим «по паспорту» (замечание эколога «не работает»): тело
    {org, site, passport: <ФККО|индекс>|fkko, passport_name?, wi?: {имя: Wi},
    save?} → состав из базы (ручной ввод → протокол состава → паспорт →
    ООС, приведён к 100 %) → Ci = % × 10 000, Wi из справочника
    waste_refdata → K и класс → .docx в out_dir/класс_опасности/.
    Ответ: {k, k_total, hazard_class, components, warnings, missing_wi,
    note, source, path} либо {error}."""
    from ecodoc.development.hazard_class import (calculate,
                                                 components_from_percent,
                                                 for_waste, generate)
    ctx = workspace.load_context(body["org"], body["site"])
    selector = body.get("passport")
    if selector in (None, ""):
        selector = body.get("fkko") or ""
    info = for_waste(ctx, selector)
    if info.get("error") and "не найден" in info["error"] and body.get("passport_name"):
        by_name = for_waste(ctx, str(body["passport_name"]))
        if not by_name.get("error"):
            info = by_name
    if info.get("error"):
        return info
    comps, missing = components_from_percent(info["components"], body.get("wi"))
    if not comps:
        return {"error": f"у отхода {info.get('fkko')} {info.get('name')} нет "
                         f"компонентов с числовым содержанием"}
    r = calculate(comps)
    out = {"k": r.k_total, "k_total": r.k_total, "hazard_class": r.hazard_class,
           "declared_class": info.get("hazard_class"),
           "components": r.components, "warnings": list(r.warnings),
           "missing_wi": missing, "source": info["source"],
           "name": info["name"], "fkko": info["fkko"],
           "note": " ; ".join(x for x in (
               f"состав — {info['source']}", info.get("note") or "") if x)}
    if missing:
        out["warnings"].append(
            "без Wi (в K не учтены): " + ", ".join(missing)
            + " — введите Wi из БДО и пересчитайте")
    if body.get("save", 1):
        out_dir = workspace.results_dir(body["org"], body["site"]) / "класс_опасности"
        code = re.sub(r"\D", "", str(info.get("fkko") or "")) or re.sub(
            r'[\\/:*?"<>|]', "_", str(info.get("name") or "отход"))[:60]
        proto = info.get("protocol") or {}
        basis = (f"Компонентный состав отхода — {info['source']}"
                 + (f" ({proto.get('lab')})" if proto.get("lab") else "")
                 + "; содержание приведено к 100 % и переведено в мг/кг; "
                   "Wi — по приложению № 4 и п. 11 Критериев (пр. № 158), "
                   "справочные значения БДО помечены в графе «Источник Wi».")
        path = generate(comps, out_dir / f"расчёт_класса_{code}.docx",
                        waste_name=info.get("name", ""), fkko=info.get("fkko", ""),
                        org_name=ctx.organization.name, org_inn=ctx.organization.inn,
                        basis=basis, protocol=proto, missing_wi=missing,
                        declared_class=info.get("hazard_class"))
        out["path"] = str(path)
    return out


def _oos_status(ctx, site_dir) -> dict:
    """Состояние ООС по площадке: есть ли документ, извлечены ли нормативы,
    можно ли переразобрать без исходника — и человеческая подсказка."""
    from ecodoc.intake import sources, textcache
    docs = sources.load(site_dir).get("docs") or {}
    oos = [(sha, rec) for sha, rec in docs.items()
           if str(rec.get("doc_type") or "") in ("oos", "pnoolr")
           or any(k in str(rec.get("file") or "").upper() for k in ("ООС", "ПМООС", "ПНООЛР"))]
    have = bool(isinstance(ctx.extra, dict) and ctx.extra.get("oos_wastes"))
    st = {"has_norms": have, "has_oos_doc": bool(oos), "file": "", "sha": "",
          "can_reanalyze": False, "note": "",
          "norms": len(ctx.extra.get("oos_wastes") or []) if isinstance(ctx.extra, dict) else 0}
    if oos:
        sha, rec = oos[0]
        st["file"], st["sha"] = rec.get("file", ""), sha
        st["can_reanalyze"] = textcache.has(site_dir, sha) or \
            (Path(site_dir) / "attachments" / rec.get("file", "")).exists()
    if have:
        st["note"] = (f"нормативы из ООС «{st['file']}»: {st['norms']} отход(ов)"
                      if st["file"] else f"нормативы ООС: {st['norms']} отход(ов)")
        return st
    if not oos:
        st["note"] = ("ООС/ПНООЛР не загружен — загрузите его в ЗАГРУЗКЕ с категорией "
                      "«отходы: ООС/ПНООЛР/паспорта/протоколы/акты»")
    elif st["can_reanalyze"]:
        st["note"] = (f"ООС «{st['file']}» разобран прежней версией программы — таблица "
                      f"отходов из него не извлечена: нажмите «Переразобрать ООС»")
    else:
        st["note"] = (f"ООС «{st['file']}» был загружен и разобран прежней версией "
                      f"программы, исходник и текст не сохранены — загрузите файл заново "
                      f"(ЗАГРУЗКА, категория «отходы»)")
    return st


def _oos_note(ctx, site_dir) -> str:
    st = _oos_status(ctx, site_dir)
    return "" if st["has_norms"] else st["note"]


def api_oos_status(params, body):
    org, site = body["org"], body["site"]
    return _oos_status(workspace.load_context(org, site), workspace.site_dir(org, site))


def api_feedback(params, body):
    """Замечание пользователя из шапки → файл в очереди автозадач."""
    from ecodoc.core import feedback
    org, site = str(body.get("org") or ""), str(body.get("site") or "")
    site_dir = workspace.site_dir(org, site) if (org and site) else None
    payload = dict(body)
    payload.setdefault("version", __version__)
    path = feedback.save(payload, site_dir)
    return {"ok": True, "path": str(path), "pending": len(feedback.pending())}


def api_doc_preview(params, body):
    """Предпросмотр сформированного документа (docx/xlsx/xml) в интерфейсе."""
    from ecodoc.gui import preview
    raw = str(body.get("path") or "")
    if not raw:
        return {"error": "не указан файл"}
    p = Path(raw).resolve()
    roots = [workspace.results_root().resolve(), workspace.root().resolve()]
    if not any(str(p).startswith(str(r)) for r in roots):
        return {"error": "предпросмотр только для файлов из папки результатов"}
    return preview.render(p)




def api_waste_forget(params, body):
    """Удалить отход насовсем: позиция, акты, паспорт, сведения, строки ООС,
    кандидаты → отклонено; код исключается (extra.waste_excluded)."""
    from ecodoc.core import waste_exclude
    from ecodoc.core.waste_agg import apply_acts
    from ecodoc.intake import intake
    org, site = body["org"], body["site"]
    if intake.is_busy(org, site):
        return {"error": "Идёт приём по этой площадке — дождитесь окончания."}
    ctx = workspace.load_context(org, site)
    res = waste_exclude.forget(ctx, workspace.site_dir(org, site), str(body.get("fkko") or ""))
    if res.get("error"):
        return res
    apply_acts(ctx)
    workspace.save_context(org, site, ctx)
    _ISSUES_CACHE.pop((org, site), None)
    return res


def api_waste_restore(params, body):
    from ecodoc.core import waste_exclude
    org, site = body["org"], body["site"]
    ctx = workspace.load_context(org, site)
    ok = waste_exclude.restore(ctx, str(body.get("fkko") or ""))
    if ok:
        workspace.save_context(org, site, ctx)
    return {"ok": ok}


def api_waste_compositions(params, body):
    """Составы отходов из всех источников (ручные сведения, сгенерированные
    паспорта, паспорта-сканы, протоколы) — для «Оформить расчёт по паспорту»."""
    from ecodoc.core import fkko as _fkko
    from ecodoc.core import waste_refdata as R
    from ecodoc.core.waste_agg import norm_fkko
    from ecodoc.development import waste_passport
    ctx = workspace.load_context(body["org"], body["site"])
    labels = {"manual": "сведения, введённые вручную", "protocol": "протокол состава",
              "passport": "паспорт отхода (скан)", "oos": "ООС/ПНООЛР",
              "pnoolr": "ООС/ПНООЛР", "generated": "сгенерированный паспорт"}
    rows, seen = [], set()
    for w in ctx.wastes:
        code = norm_fkko(w.fkko_code)
        if not code or code in seen:
            continue
        d = waste_passport._details(ctx, w)
        comps = d.get("components") or []
        if not comps:
            continue
        norm, note = R.normalize_components(comps)
        if not norm:
            continue
        seen.add(code)
        total = sum(float(str(c.get("percent") or 0).replace(",", ".")) for c in norm)
        rows.append({"fkko": code, "fkko_fmt": _fkko.fmt(code), "name": w.name,
                     "hazard_class": w.hazard_class,
                     "components": [{"name": c.get("name", ""), "percent": c.get("percent", "")}
                                    for c in norm],
                     "source": labels.get(d.get("_comp_kind") or "", d.get("_comp_kind") or "паспорт"),
                     "total": round(total, 2), "note": note or ""})
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    for p in extra.get("waste_passports") or []:
        code = norm_fkko(p.get("fkko") if isinstance(p, dict) else "")
        if not code or code in seen or not (p.get("components") or []):
            continue
        norm, note = R.normalize_components(p["components"])
        if not norm:
            continue
        seen.add(code)
        rows.append({"fkko": code, "fkko_fmt": _fkko.fmt(code), "name": p.get("name", ""),
                     "hazard_class": p.get("hazard_class") or int(code[-1]),
                     "components": [{"name": c.get("name", ""), "percent": c.get("percent", "")}
                                    for c in norm],
                     "source": "паспорт отхода (загруженный)", "total": 100.0, "note": note or ""})
    note = ""
    if not rows:
        if extra.get("passports_generated_at"):
            note = ("паспорта сформированы, но состава нет ни у одного отхода — в них "
                    "состав «определяется по протоколу»: загрузите протоколы состава "
                    "отходов или ООС/ПНООЛР с таблицей характеристики отходов")
        else:
            note = ("составов нет: загрузите протоколы состава отходов, паспорта или "
                    "ООС/ПНООЛР — без состава класс опасности не считается")
    return {"rows": rows, "note": note}


def api_hazard_class(params, body):
    """Расчёт класса опасности (пр. МПР № 158). Два режима:
    * «по паспорту» — без components, но с org/site и passport|fkko
      (см. _hazard_class_from_passport);
    * ручной — components [{name, ci (мг/кг), wi}] (+ save/waste_name/fkko/
      basis/org/site) — контракт калькулятора вкладки «Сервис»; Wi = 0 —
      берётся из справочника waste_refdata, если компонент известен."""
    from ecodoc.development.hazard_class import Component, calculate, generate
    if not body.get("components") and body.get("org") and body.get("site") \
            and (body.get("passport") not in (None, "") or body.get("fkko")):
        return _hazard_class_from_passport(body)
    from ecodoc.core.waste_refdata import wi_for
    comps = []
    for c in body.get("components", []):
        if not c.get("name"):
            continue
        wi = float(c.get("wi") or 0)
        src = "задано вручную" if wi else ""
        if not wi:
            found, src_ref, _canon = wi_for(str(c.get("name")))
            if found:
                wi, src = float(found), src_ref
        comps.append(Component(name=c.get("name", ""), ci=float(c.get("ci") or 0),
                               wi=wi, wi_source=src))
    if not comps:
        return {"error": "Добавьте компоненты отхода (наименование, Ci, Wi)."}
    r = calculate(comps)
    out = {"k_total": r.k_total, "hazard_class": r.hazard_class,
           "components": r.components, "warnings": r.warnings}
    if body.get("save"):                       # оформить расчёт документом
        org_name = org_inn = ""
        if body.get("org") and body.get("site"):
            out_dir = workspace.results_dir(body["org"], body["site"]) / "класс_опасности"
            org = workspace.load_context(body["org"], body["site"]).organization
            org_name, org_inn = org.name, org.inn
        else:                                  # калькулятор без объекта
            out_dir = workspace.results_root() / "расчёты"
        name = re.sub(r'[\\/:*?"<>|]', "_",
                      (body.get("waste_name") or "отход").strip())[:60]
        path = generate(comps, out_dir / f"расчёт_класса_{name}.docx",
                        waste_name=body.get("waste_name", ""),
                        fkko=body.get("fkko", ""), org_name=org_name,
                        org_inn=org_inn, basis=body.get("basis", ""),
                        missing_wi=[c.name for c in comps if not c.wi])
        out["path"] = str(path)
    return out


def api_volume(params, body):
    """Собрать том НДВ/НДС/СЗЗ: наши данные + выгрузки УПРЗА «Эколог».

    Контур обмена с УПРЗА: источники выгружаются кнопкой «Выгрузить для
    УПРЗА», расчёт делает аттестованная программа («Эколог»), её Excel-выгрузки
    возвращаются сюда — и том собирается с настоящими таблицами.

    Файлы: sources_file — таблица источников; dispersion_file — книга
    результатов (многолистовая: концентрации, расчётные точки, вклады —
    листы распознаются по названиям); points_file / contrib_file — те же
    таблицы отдельными файлами. Для НДВ в ответ добавляется gaps — перечень
    того, чего не хватает до проекта по Методике № 581."""
    import shutil

    from ecodoc.development import volume_builder as vb
    ctx = workspace.load_context(body["org"], body["site"])
    vtype = body.get("vtype") or "ndv"
    src = vb.VolumeSources()
    tmpdir = Path(tempfile.mkdtemp(prefix="ecodoc_volume_"))
    notes = []
    try:
        for key, attr in (("sources_file", "sources"),
                          ("dispersion_file", "dispersion"),
                          ("points_file", "points"),
                          ("contrib_file", "contrib")):
            f = body.get(key)
            if not f:
                continue
            try:
                path = Path(_decode_to_tmp([f], tmpdir)[0])
                # книга результатов «Эколога» многолистовая — раскладываем
                # листы по типам; однолистовая идёт в свой слот как раньше
                sheet_notes = vb.ingest_ecolog_workbook(path, src, default=attr)
                notes.append(f"{f.get('name')}: " + "; ".join(sheet_notes))
            except Exception as e:
                notes.append(f"⚠ {f.get('name')}: не прочитан ({e})")
        src.appendices = [str(n) for n in body.get("appendices") or []]
        # без выгрузки «Эколога» таблицы источников берём из своей инвентаризации
        if not src.sources_table:
            from ecodoc.development.air_inventory import sources as inv_sources
            inv = inv_sources(ctx)
            if inv:
                if vtype != "ndv":   # в НДВ таблица 2.6 строится из инвентаризации сама
                    src.sources_header = ["№", "Наименование", "Тип"]
                    src.sources_table = [[s.get("number", ""), s.get("name", ""),
                                          s.get("kind", "")] for s in inv]
                notes.append(f"источники из инвентаризации: {len(inv)}")
        out_dir = workspace.results_dir(body["org"], body["site"])
        names = {"ndv": "НДВ", "nds": "НДС", "szz": "СЗЗ"}
        path = vb.build(vtype, ctx, src,
                        out_dir / (f"{'проект' if vtype == 'ndv' else 'том'}_"
                                   f"{names.get(vtype, vtype)}"
                                   f"{_year_suffix(ctx)}.docx"))
        gaps = vb.gaps(vtype, ctx, src)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if not src.dispersion_table:
        notes.append("⚠ результатов рассеивания нет — в томе остаётся "
                     "заглушка: выполните расчёт в УПРЗА и загрузите выгрузку")
    if gaps:
        notes.append(f"чего не хватает ({len(gaps)}): " + "; ".join(gaps[:8])
                     + ("; …" if len(gaps) > 8 else ""))
    return {"path": str(path), "notes": notes, "gaps": gaps}


def api_soil_class(params, body):
    """Грунт: категория почвы по СанПиН + класс отхода (пр. № 158)."""
    from ecodoc.development.soil_class import (SOIL_NORMS, SoilComponent,
                                               assess, generate)
    comps = [SoilComponent(name=c.get("name", ""),
                           ci=float(c.get("ci") or 0),
                           norm=float(c.get("norm") or 0),
                           background=float(c.get("background") or 0),
                           wi=float(c.get("wi") or 0))
             for c in body.get("components", []) if c.get("name")]
    if not comps:
        return {"error": "Добавьте вещества (наименование и Ci, мг/кг).",
                "norms": SOIL_NORMS}
    r = assess(comps)
    out = {"category": r.category, "zc": r.zc, "use": r.use,
           "exceedances": r.exceedances, "hazard_class": r.hazard_class,
           "k_total": r.k_total, "warnings": r.warnings, "norms": SOIL_NORMS}
    if body.get("save"):
        if body.get("org") and body.get("site"):
            out_dir = workspace.results_dir(body["org"], body["site"])
        else:
            out_dir = workspace.results_root() / "расчёты"
        label = re.sub(r'[\\/:*?"<>|]', "_",
                       (body.get("site_label") or "грунт").strip())[:60]
        path = generate(comps, out_dir / f"оценка_грунта_{label}.docx",
                        site_label=body.get("site_label", ""),
                        basis=body.get("basis", ""))
        out["path"] = str(path)
    return out


def api_org_short_name(params, body):
    """Предложить краткое наименование из полного («ИП Миних Е.А.»)."""
    from ecodoc.core import sanitize_records as recs
    ctx = workspace.load_context(body["org"], body["site"])
    o = ctx.organization
    return {"short_name": recs.suggest_short_name(o.name, o.inn),
            "problem": recs.short_name_problem(o.name, o.short_name, o.inn)}


def api_passports_check(params, body):
    """Сверка паспортов отходов: источник, каталог, наименование/класс, акты."""
    from ecodoc.core import sanitize_records as recs
    ctx = workspace.load_context(body["org"], body["site"])
    rows = recs.check_passports(ctx)
    return {"rows": rows,
            "totals": {"ok": sum(1 for r in rows if not r["problems"]),
                       "bad": sum(1 for r in rows if r["problems"]),
                       "bad_source": sum(1 for r in rows if not r["src_ok"])}}


def api_waste_crosscheck(params, body):
    """Сверка отходов по источникам: ООС/ПНООЛР ↔ паспорта ↔ протоколы ↔ акты
    (по каждому ФККО — что говорит каждый документ и где расхождения)."""
    from ecodoc.core import waste_crosscheck
    org, site = body["org"], body["site"]
    return waste_crosscheck.build(workspace.load_context(org, site),
                                  workspace.site_dir(org, site))


def api_fkko_fix(params, body):
    """Заменить код ФККО (и при желании наименование/класс) во всех записях."""
    from ecodoc.core import fkko
    from ecodoc.core.waste_agg import norm_fkko
    org, site = body["org"], body["site"]
    old, new = norm_fkko(body.get("old")), norm_fkko(body.get("new"))
    if len(old) != 11 or len(new) != 11:
        return {"error": "коды ФККО — по 11 цифр"}
    name, hazard = body.get("name") or "", body.get("hazard")
    if new != old and not fkko.check(new).ok:
        return {"error": f"код {fkko.fmt(new)} не найден в каталоге ФККО — замена отклонена"}
    ctx = workspace.load_context(org, site)
    n = 0
    for coll in (ctx.wastes, ctx.waste_acts):
        for w in coll:
            if norm_fkko(w.fkko_code) == old:
                w.fkko_code = new
                if name:
                    w.name = name
                if hazard:
                    try:
                        w.hazard_class = int(hazard)
                    except (TypeError, ValueError):
                        pass
                n += 1
    for p in (ctx.extra.get("waste_passports") or []):
        if isinstance(p, dict) and norm_fkko(p.get("fkko")) == old:
            p["fkko"] = new
            if name:
                p["name"] = name
            n += 1
    workspace.save_context(org, site, ctx)
    return {"replaced": n, "old": old, "new": new}


def api_intake_map(params, body):
    """ЗАГРУЗКА: по каждому файлу — что взято, в какой раздел, с какого листа."""
    from ecodoc.intake import insight
    org, site = body["org"], body["site"]
    return insight.intake_map(workspace.load_context(org, site),
                              workspace.site_dir(org, site), org, site)


_ISSUES_CACHE: dict = {}


def api_data_issues(params, body):
    """Единая проверка данных по категориям с файлом/листом/подсказкой.

    На большой базе (600 файлов) считается 8–10 с — кэшируем по отпечаткам
    context.json / candidates.json / sources.json: пока данные не менялись,
    вкладка открывается мгновенно."""
    from ecodoc.intake import insight
    org, site = body["org"], body["site"]
    sd = workspace.site_dir(org, site)
    stamp = tuple(_ctx_version(sd / n) for n in ("context.json", "candidates.json",
                                                  "sources.json"))
    hit = _ISSUES_CACHE.get((org, site))
    if hit and hit[0] == stamp and not body.get("refresh"):
        return hit[1]
    out = insight.data_issues(workspace.load_context(org, site), sd, org, site)
    _ISSUES_CACHE[(org, site)] = (stamp, out)
    return out


def api_form_gaps(params, body):
    """Чего не хватает каждой форме и как это закрыть."""
    from ecodoc.intake import insight
    return insight.form_gaps(workspace.load_context(body["org"], body["site"]))


def api_waste_periods(params, body):
    """Разбивка отходов по годам/кварталам/месяцам в т и м³ (из актов)."""
    from ecodoc.core import waste_periods
    ctx = workspace.load_context(body["org"], body["site"])
    return waste_periods.build(ctx)


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
    # панель только ПОКАЗЫВАЕТ конфиг: раньше здесь звался ensure_configured,
    # который заново выбирал «лучшую» модель и молча затирал ручной выбор
    # (замечание 09.09: «сохранить выбор возвращает модель, выбранную автоматом»)
    cfg = load_config()
    if not cfg.provider:
        cfg = detect.ensure_configured()
    providers = []
    for pid in detect.PROVIDER_LABEL:
        local = pid in ("ollama", "lmstudio")
        providers.append({
            "id": pid, "label": detect.PROVIDER_LABEL[pid],
            "local": local, "has_key": True if local else has_key(pid),
            "models": detect.known_models(pid),
            "default": detect.CLOUD_DEFAULT_MODEL.get(pid, "")})
    det = cfg.detected if isinstance(cfg.detected, dict) else {}
    return {"provider": cfg.provider, "model": cfg.model,
            "auto_pick": det.get("auto_pick", True) is not False,
            "picked_by": det.get("picked_by", ""),
            "current_health": _model_health(cfg.provider, cfg.model),
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
    det["picked_by"] = "user"
    # галочка «выбирать оптимальную автоматически при запуске» (по умолчанию да);
    # снята — выбор закреплён, автопроверка его не перебивает
    det["auto_pick"] = bool(body.get("auto_pick", True))
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
    labels = {"name": "Полное наименование", "short_name": "Краткое наименование",
              "inn": "ИНН", "kpp": "КПП", "ogrn": "ОГРН/ОГРНИП",
              "address": "Юридический адрес (по ЕГРЮЛ)",
              "director_name": "Руководитель", "director_position": "Должность руководителя"}
    for r in rows:
        r["label"] = labels.get(r["field"], r["field"])
    notes = []
    # ЕГРИП адрес места жительства ИП не публикует: сервис ФНС его не отдаёт —
    # юридический адрес ИП берётся из договора (раздел «реквизиты сторон»)
    if len(re.sub(r"\D", "", inn)) == 12 and not found.get("address"):
        notes.append("ЕГРИП не публикует адрес индивидуального предпринимателя — "
                     "юридический адрес берётся из договора (раздел «Юридические "
                     "адреса и реквизиты сторон», сторона ЗАКАЗЧИК) или вводится вручную.")
    return {"inn": inn, "rows": rows, "egrul": found, "notes": notes,
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


def api_forms_norms(params, body):
    """Сверка бланков с действующими НПА (+ по интернету, если online)."""
    from ecodoc.core import forms_norms
    online = str((body or {}).get("online", "")).lower() in ("1", "true", "yes")
    return forms_norms.check_all(online=online)


def api_forms_registry(params, body):
    """Бланки-образцы документов: что есть в папке «Формы», чего не хватает."""
    from ecodoc.core import forms_registry as fr
    base = fr.root()
    slots = fr.scan()
    rows = [{"code": s.code, "title": s.title, "kind": s.kind, "folder": s.folder,
             "files": s.files, "has": s.has_sample} for s in slots]
    out = {"root": str(base) if base else "", "rows": rows,
           "have": sum(1 for s in slots if s.has_sample), "total": len(slots)}
    if str((body or {}).get("search", "")).lower() in ("1", "true", "yes"):
        out["found"] = fr.find_missing(slots)
    if str((body or {}).get("check_new", "")).lower() in ("1", "true", "yes"):
        ch = fr.check_new()
        # разницу с прошлого раза могла уже «съесть» проверка при запуске —
        # доливаем её сюда, иначе кнопка покажет пустоту вместо новых бланков
        eaten = STARTUP_NOTES.get("forms_changes") or {}
        for key in ("added", "removed"):
            for title, files in (eaten.get(key) or {}).items():
                have = ch.setdefault(key, {}).setdefault(title, [])
                have += [f for f in files if f not in have]
        out["changes"] = ch
    return out


def api_fkko_check(params, body):
    """Проверка кодов отходов объекта по действующему каталогу ФККО."""
    from ecodoc.core import fkko
    src = body if (body or {}).get("org") else params
    fkko.seed_builtin()
    ctx = workspace.load_context(src["org"], src["site"])
    rows = fkko.check_context(ctx)
    return {"rows": rows, "updated": fkko.updated(),
            "partial": bool(fkko.catalog().get("partial")),
            "size": len(fkko.codes()),
            "bad": sum(1 for r in rows if not r["ok"]),
            "unverified": sum(1 for r in rows if r["ok"] and not r["verified"])}


def api_fkko_update(params, body):
    """Обновить каталог ФККО: из сети или из файла, скачанного пользователем."""
    from ecodoc.core import fkko
    path = (body.get("path") or "").strip()
    try:
        if path:
            n, src = fkko.load_file(path)
        else:
            # сначала папка «Формы» — там каталог обычно и лежит; открытого
            # машиночитаемого ФККО в сети нет, сеть остаётся запасным путём
            found = fkko.from_forms_folder()
            n, src = found if found else fkko.update()
        return {"ok": True, "codes": n, "source": src,
                "partial": bool(fkko.catalog().get("partial"))}
    except Exception as e:
        return {"error": str(e)[:400]}


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
        if ok:
            applied.append(key)
        else:
            # без причины кнопка «Взять» выглядела сломанной: молча ничего
            failed.append({"key": key, "reason": _why_not_written(
                key, str(d.get("value", "")))})
    if applied:
        workspace.save_context(org, site, ctx)
    return {"applied": applied, "failed": failed}


def _why_not_written(key: str, value: str) -> str:
    """Понятная причина, почему значение не попало в базу."""
    from ecodoc.intake import candidates
    try:
        coll, sel, attr = candidates.parse_key(key)
    except Exception:
        return f"не разобран адрес поля «{key}»"
    if attr in candidates._DEC_ATTRS or attr in candidates._INT_ATTRS:
        if candidates._number(value) is None:
            return f"«{value}» — не число, а поле «{attr}» числовое"
    if coll in ("wastes", "waste_acts") and not sel.get("fkko"):
        return "не указан код ФККО — непонятно, к какому отходу относится"
    if coll == "pollutants" and not (sel.get("code") or sel.get("name")):
        return "не указаны ни код, ни наименование вещества"
    return (f"поле «{attr}» не найдено в разделе «{coll}» — возможно, позиция "
            f"была удалена; впишите значение вручную")


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
        # в ссылках на документы часто кириллица («…/Отчёт 2025.pdf») —
        # без процентного кодирования urllib падал на любой такой ссылке
        parts = urllib.parse.urlsplit(url)
        url = urllib.parse.urlunsplit((
            parts.scheme, parts.netloc,
            urllib.parse.quote(parts.path, safe="/%"),
            urllib.parse.quote(parts.query, safe="=&%?+"),
            parts.fragment))
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
        from ecodoc.ai import registry as _reg
        results = health.check_all(_reg.all_specs())
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
    """ОКТМО по адресу: {result:{oktmo,value,source,level,confidence},
    candidates:[{oktmo,value,level,confidence}]} — один уверенный вариант
    GUI подставляет сам, несколько — даёт выбрать; ничего — error."""
    from ecodoc.parsers.oktmo import OktmoError, by_address, resolve
    address = (body.get("address") or "").strip()
    try:
        res = by_address(address)
        cands = res.get("candidates") or [{"oktmo": res["oktmo"], "value": res.get("value", ""),
                                           "level": res.get("level", ""),
                                           "confidence": res.get("confidence", 1.0)}]
        return {"result": res, "candidates": cands}
    except OktmoError as e:
        # не уверены — отдадим кандидатов на выбор (оффлайн + геокодер OSM,
        # они уже собраны в e.candidates); текст ошибки короткий
        cands = getattr(e, "candidates", None)
        try:
            r = resolve(address)
        except Exception:
            r = {}
        if cands is None:
            cands = r.get("candidates") or []
        return {"error": str(e), "candidates": cands,
                "note": r.get("note", ""), "region": r.get("region_name", "")}


def api_rates_check(params, body):
    """Есть ли в интернете акт о ставках платы за НВОС новее вшитого."""
    from ecodoc.core import rates_update
    timeout = float((body or {}).get("timeout") or 10)
    res = rates_update.check_online(timeout=timeout)
    STARTUP_NOTES["rates"] = res
    return res


def api_rates_apply(params, body):
    """Обновить data/rates_nvos.json из документа по ссылке (PDF/HTML/JSON)."""
    from ecodoc.core import rates_update
    url = (body or {}).get("url") or ""
    if not url:
        note = STARTUP_NOTES.get("rates") or {}
        url = note.get("url") or ""
    year = (body or {}).get("year")
    res = rates_update.apply(url, year=int(year) if year else None,
                             medium=(body or {}).get("medium") or "air")
    if res.get("ok"):
        try:
            from ecodoc.core import refdata
            refdata._CACHE.pop("rates_nvos.json", None)
        except Exception:
            pass
    return res


def api_open(params, body):
    """Открыть папку/файл в проводнике.

    Разрешены два корня: база данных и папка результатов. Раньше проверялся
    только первый, а готовые документы кладутся во второй — поэтому кнопка
    «открыть» после генерации не срабатывала никогда."""
    target = Path(body["path"]).resolve()
    roots = [workspace.root().resolve()]
    try:
        roots.append(workspace.results_root().resolve())
    except Exception:
        pass
    if not any(_inside(target, r) for r in roots):
        return {"error": f"Путь вне рабочих папок программы: {target}"}
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
              "sources": api_sources, "candidates": api_candidates,
              "fkko_check": api_fkko_check,
              "forms_registry": api_forms_registry}
POST_ROUTES = {"intake_forget": api_intake_forget,
               "ai_autopick": api_ai_autopick,
               "models_refresh": api_models_refresh,
               "oos_status": api_oos_status, "feedback": api_feedback,
               "doc_preview": api_doc_preview,
               "waste_forget": api_waste_forget, "waste_restore": api_waste_restore,
               "waste_compositions": api_waste_compositions,
               "intake_unexclude": api_intake_unexclude,
               "org_add": api_org_add, "org_lookup": api_org_lookup,
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
               "rates_check": api_rates_check, "rates_apply": api_rates_apply,
               "hazard_class": api_hazard_class,
               "soil_class": api_soil_class,
               "volume": api_volume,
               "devdoc": api_devdoc, "submit": api_submit, "open": api_open,
               "waste_summary": api_waste_summary, "missing": api_missing,
               "waste_table": api_waste_table, "disk_usage": api_disk_usage,
               "mark_submitted": api_mark_submitted,
               "audit_data": api_audit_data, "clean_data": api_clean_data,
               "org_short_name": api_org_short_name,
               "passports_check": api_passports_check,
               "waste_crosscheck": api_waste_crosscheck,
               "fkko_fix": api_fkko_fix, "waste_periods": api_waste_periods,
               "intake_map": api_intake_map, "data_issues": api_data_issues,
               "form_gaps": api_form_gaps,
               "settings": api_settings, "cleanup": api_cleanup,
               "storage": api_storage,
               "ai_health": api_ai_health, "ai_task": api_ai_task,
               "intake_url": api_intake_url,
               "source_page": api_source_page,
               "source_meta": api_source_meta, "sources": api_sources,
               "candidates": api_candidates,
               "candidate_decide": api_candidate_decide,
               "candidate_manual": api_candidate_manual,
               "org_verify": api_org_verify,
               "object_check": api_object_check,
               "fkko_check": api_fkko_check,
               "fkko_update": api_fkko_update,
               "forms_registry": api_forms_registry,
               "forms_norms": api_forms_norms}


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
        # всё остальное — одна страница (без кэша: после обновления программы
        # браузер не должен показывать старый интерфейс)
        data = render_index()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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
        from ecodoc.ai import registry as _reg
        from ecodoc.ai.config import load_config
        # требование пользователя (08.09.2026): при КАЖДОМ запуске проверить
        # модели, выбрать оптимальную и применить — кэш свежести не срезает
        results = health.check_all(_reg.all_specs())
        working = health.ranked_working(results)
        cfg0 = load_config()
        det = cfg0.detected if isinstance(cfg0.detected, dict) else {}
        pinned = det.get("auto_pick") is False and bool(cfg0.provider)
        if pinned:
            cfg = cfg0
            text = (f"модель закреплена вручную: {cfg.provider}/{cfg.model} "
                    f"(рабочих моделей {len(working)} из {len(results)})")
        else:
            cfg = health.apply_best(results)
            text = (f"выбрана оптимальная: {cfg.provider}/{cfg.model} "
                    f"(рабочих моделей {len(working)} из {len(results)})"
                    if working else "ни одна модель не ответила — Сервис → Модели ИИ")
        STARTUP_NOTES["ai"] = _ai_note(cfg, results, text, pinned)
        print("ИИ: " + STARTUP_NOTES["ai"]["text"])
    except Exception as e:                      # проверка не должна ломать запуск
        STARTUP_NOTES["ai"] = f"проверка моделей не выполнена ({e})"
        print(f"ИИ: проверка моделей не выполнена ({e})")


# что нашла фоновая проверка старта — GUI показывает это плашкой (api_meta)
STARTUP_NOTES: dict = {}


def _model_health(provider: str, model: str) -> dict:
    """Что известно о модели по последней проверке (кэш health)."""
    try:
        from ecodoc.ai import health
        checked, items = health.load_cache()
        for h in items:
            if h.provider == provider and h.model == model:
                return {"ok": bool(h.ok), "sec": h.sec, "reason": h.reason or h.error[:120],
                        "checked": checked}
    except Exception:
        pass
    return {}


def _ai_note(cfg, results, text: str, pinned: bool) -> dict:
    """Итог автовыбора с ПОДТВЕРЖДЕНИЕМ: перечитать настройки с диска и
    убедиться, что применена именно эта модель и что по проверке она
    работает (требование 09.09: «перепроверка, действительно ли выбрана»)."""
    from datetime import datetime
    from ecodoc.ai import health
    from ecodoc.ai.config import load_config
    saved = load_config()
    applied = (saved.provider, saved.model) == (cfg.provider, cfg.model)
    hz = next((h for h in results if h.provider == cfg.provider and h.model == cfg.model), None)
    works = bool(hz and hz.ok)
    working = health.ranked_working(results)
    verdict = ("подтверждено: настройки перечитаны, модель применена и по проверке работает"
               if applied and works else
               "⚠ применено, но проверка модели не прошла — смотрите «Сервис → Выбор ИИ»"
               if applied else "⚠ НЕ применено: в настройках другая модель — нажмите «Автовыбор»")
    return {"text": text + " — " + verdict, "provider": cfg.provider, "model": cfg.model,
            "applied": applied, "works": works, "pinned": pinned,
            "working": len(working), "total": len(results),
            "best": [f"{h.provider}/{h.model} ({h.sec} с)" for h in working[:5]],
            "at": datetime.now().strftime("%H:%M:%S")}




def _auto_correct(sources: dict) -> list[str]:
    """Автокоррекция по итогам проверки источников (требование 09.09):
    ставки — подтянуть новый акт, если он машиночитаем; формы — редакции
    выбираются по дате из реестра НПА; ФККО — из папки «Формы»."""
    out: list[str] = []
    changed = {c.get("id", ""): c for c in sources.get("changed") or []}
    if any("став" in (c.get("name") or "").lower() for c in changed.values()):
        try:
            from ecodoc.core import rates_update
            res = rates_update.check_online(timeout=10)
            STARTUP_NOTES["rates"] = res
            if res.get("newer") and res.get("url"):
                try:
                    ap = rates_update.apply(res["url"])
                    out.append("ставки платы: найден новый акт, справочник обновлён автоматически"
                               + (f" ({ap.get('updated')} значений)" if isinstance(ap, dict) else ""))
                except Exception as e:
                    out.append(f"ставки платы: новый акт найден ({res.get('latest_act')}), "
                               f"автообновление не удалось — нажмите «Обновить ставки» ({str(e)[:80]})")
            else:
                out.append("ставки платы: страница изменилась, но акта новее вшитого нет — "
                           "справочник актуален")
        except Exception as e:
            out.append(f"ставки платы: проверка не выполнена ({str(e)[:80]})")
    if any("фкко" in (c.get("name") or "").lower() for c in changed.values()):
        try:
            from ecodoc.core import fkko
            out.append(f"ФККО: сайт каталога изменился — программа работает по каталогу от "
                       f"{fkko.updated() or '?'} ({len(fkko.codes())} кодов); положите свежую "
                       f"выгрузку в папку «Формы» — подхватится при запуске")
        except Exception:
            pass
    forms = sorted({f for c in changed.values() for f in (c.get("forms") or [])})
    if forms:
        try:
            from ecodoc.core import forms_norms
            for code in forms:
                cur = forms_norms.current(code) if hasattr(forms_norms, "current") else None
                if cur:
                    out.append(f"форма {code}: редакция выбирается по дате автоматически — "
                               f"сейчас {cur}")
        except Exception:
            pass
    return out


def _startup_sources_check():
    """Проверка изменений форм и источников (watch) — при запуске, в фоне;
    итог структурой в STARTUP_NOTES['sources'] для плашки на экране."""
    try:
        from ecodoc.watch import watcher
        res = watcher.run_check_struct()
        res["auto"] = _auto_correct(res)
        STARTUP_NOTES["sources"] = res
        print("Источники: " + res.get("summary", ""))
    except Exception as e:
        STARTUP_NOTES["sources"] = {"error": str(e)[:200],
                                    "summary": f"проверка источников не выполнена ({e})"}


def _startup_code_check():
    """Тот ли код запущен, из папки которого стартовали.

    После переноса .venv между версиями её editable-установка указывала на
    СТАРУЮ папку релиза, и ecodoc.exe тихо запускал код v0.42/0.52 из
    папки v0.59 — пользователь тестировал не то, что выложено. Сравниваем
    папку импортированного пакета с текущей и говорим об этом плашкой."""
    try:
        import ecodoc
        code_dir = Path(ecodoc.__file__).resolve().parent.parent
        here = Path.cwd().resolve()
        if (here / "ecodoc" / "__init__.py").exists() and code_dir != here:
            STARTUP_NOTES["code"] = (f"⚠ запущен код из другой папки: {code_dir} "
                                     f"(а не {here}) — запускайте через ЭКО.DOC.bat "
                                     f"или выполните в .venv: pip install -e . --no-deps")
            print(STARTUP_NOTES["code"])
    except Exception:
        pass


def _startup_forms_check():
    """Проверка форм и справочников при запуске (требование ТЗ:
    «проверять на наличие новых форм при запуске приложения»)."""
    _startup_code_check()
    try:
        from ecodoc.core import fkko, forms_registry
        n = fkko.sync_from_forms()             # свежий ФККО из «Форм» — в базу
        if n:
            STARTUP_NOTES["fkko"] = f"каталог ФККО обновлён из «Форм»: {n} кодов"
            print(STARTUP_NOTES["fkko"])
        else:
            # файл в «Формах» старше действующего каталога — скажем об этом:
            # пользователь думает, что его выгрузка главная, а она устарела
            try:
                from datetime import date as _date
                f = fkko.find_in_forms()
                if f is not None:
                    file_day = _date.fromtimestamp(f.stat().st_mtime).isoformat()
                    cat_day = str(fkko.catalog().get("updated", ""))
                    if cat_day and file_day < cat_day:
                        STARTUP_NOTES["fkko"] = (
                            f"файл «{f.name}» в папке форм устарел (от {file_day}) — "
                            f"работаем по каталогу программы от {cat_day} "
                            f"({len(fkko.codes())} кодов); старый файл можно удалить")
            except OSError:
                pass
        ch = forms_registry.check_new()
        # разницу «съедает» эта проверка: сохраняем её, чтобы кнопка реестра
        # бланков показала то же самое, а не пустоту
        if ch.get("added") or ch.get("removed"):
            STARTUP_NOTES["forms_changes"] = ch
        notes = []
        if not ch.get("first_run"):
            for title, files in (ch.get("added") or {}).items():
                notes.append(f"новые бланки «{title}»: {', '.join(files)}")
            for title, files in (ch.get("removed") or {}).items():
                notes.append(f"пропали бланки «{title}»: {', '.join(files)}")
        slots = forms_registry.scan()
        miss = [s.title for s in slots if not s.has_sample]
        if miss:
            notes.append("нет образцов: " + ", ".join(miss))
        if notes:
            STARTUP_NOTES["forms"] = notes
            print("Формы: " + "; ".join(notes[:3])
                  + ("…" if len(notes) > 3 else ""))
    except Exception as e:                      # проверка не должна ломать запуск
        print(f"Формы: проверка при запуске не выполнена ({e})")


def _startup_rates_check():
    """Ставки платы за НВОС: при запуске спросить интернет, нет ли акта новее
    вшитого (требование эколога «искать ставки в интернете и использовать
    всегда»). Фоновый поток, таймаут 10 с, старт GUI не ждёт; итог — в
    STARTUP_NOTES['rates'] (плашка + карточка «Ставки платы» в Сервисе)."""
    try:
        from ecodoc.core import rates_update
        res = rates_update.check_online(timeout=10)
        STARTUP_NOTES["rates"] = res
        print("Ставки НВОС: " + res.get("text", ""))
        if res.get("latest_date") and not res.get("error"):
            rates_update.mark_checked(res)
    except Exception as e:                      # проверка не должна ломать запуск
        STARTUP_NOTES["rates"] = {"error": str(e)[:200], "newer": False,
                                  "text": f"ставки платы за НВОС: проверка не выполнена ({e})"}


MAINTENANCE_EVERY = 24 * 3600     # сек: обновление списка моделей, ставок, проверка моделей


def _maintenance_once(first: bool = False) -> dict:
    """Один проход обслуживания (требование пользователя 08.09: «проверять и
    обновлять автоматом при запуске и периодически»): живой список моделей
    OpenRouter → проверка ставок платы → проверка «здоровья» моделей, если
    прошлая устарела. Каждый шаг в своём try — один сбой не гасит остальные."""
    from datetime import datetime
    out = {"at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    try:
        from ecodoc.ai import detect
        res = detect.refresh_openrouter_models(timeout=10)
        STARTUP_NOTES["models"] = res
        out["models"] = res.get("text") or res.get("error")
        print("Модели OpenRouter: " + str(out["models"]))
    except Exception as e:
        STARTUP_NOTES["models"] = {"error": str(e)[:200]}
    try:
        _startup_rates_check()
        out["rates"] = (STARTUP_NOTES.get("rates") or {}).get("text")
    except Exception as e:
        out["rates"] = str(e)[:120]
    try:
        _startup_sources_check()
        out["sources"] = (STARTUP_NOTES.get("sources") or {}).get("summary")
    except Exception as e:
        out["sources"] = str(e)[:120]
    if not first:
        try:
            from ecodoc.ai import health
            if not health.fresh():
                _startup_ai_check()
                out["health"] = "проверка моделей выполнена"
        except Exception as e:
            out["health"] = str(e)[:120]
    STARTUP_NOTES["maintenance"] = out
    return out


def _maintenance_loop():
    import time
    time.sleep(3)                         # окно уже открыто — не мешаем старту
    _maintenance_once(first=True)
    while True:
        time.sleep(MAINTENANCE_EVERY)
        try:
            _maintenance_once()
        except Exception:
            pass


def run(port: int = 8737, open_browser: bool = True):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"ЭКО.DOC GUI: {url}  (Ctrl+C — остановить)")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    threading.Thread(target=_startup_ai_check, daemon=True).start()
    threading.Thread(target=_startup_forms_check, daemon=True).start()
    # список моделей + ставки при старте и раз в сутки (ставки — внутри цикла)
    threading.Thread(target=_maintenance_loop, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
