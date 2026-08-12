"""Рабочее пространство: несколько организаций, у каждой — несколько площадок.

Структура на диске (корень — $ECODOC_WORKSPACE или ./ecodoc_workspace):

    <корень>/
      <организация>/
        org.json            реквизиты организации (общие для площадок)
        <площадка>/
          context.json      контекст площадки (организация подставляется из org.json)
          attachments/      принятые входящие документы
          out/              сгенерированные формы

Любая команда CLI вместо -i context.json может принять --org/--site:
контекст собирается из org.json + context.json площадки.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path

from ecodoc.core import serialize
from ecodoc.core.models import Organization, ReportContext


def _onedrive() -> Path | None:
    """Папка OneDrive этой машины (env OneDrive → ~/OneDrive), если есть."""
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        p = os.environ.get(var)
        if p and Path(p).is_dir():
            return Path(p)
    p = Path.home() / "OneDrive"
    return p if p.is_dir() else None


_MERGE_LOCK = __import__("threading").Lock()
_MOVED_MARKER = "ПЕРЕНЕСЕНО-в-OneDrive.txt"
_ROOT_CACHE: Path | None = None    # решение принимается ОДИН раз на процесс


def root() -> Path:
    """Корень рабочего пространства.

    Приоритет: $ECODOC_WORKSPACE → ./ecodoc_workspace (если уже создан,
    обратная совместимость) → **OneDrive/ЭКО.DOC** (общая база для всех
    компьютеров пользователя; локальная ~/ЭКО.DOC при первом запуске
    вливается в неё) → ~/ЭКО.DOC (без OneDrive).
    """
    global _ROOT_CACHE
    env = os.environ.get("ECODOC_WORKSPACE")
    if env:
        return Path(env)
    local_ws = Path("ecodoc_workspace")
    if local_ws.is_dir():
        return local_ws
    if _ROOT_CACHE is not None:
        return _ROOT_CACHE
    with _MERGE_LOCK:
        if _ROOT_CACHE is not None:
            return _ROOT_CACHE
        # выбор пользователя: «общая база в OneDrive» или «только этот компьютер»
        # (ТЗ: «реализовать ВОЗМОЖНОСТЬ сохранять на онедрайве»)
        if storage_mode() == "local":
            _ROOT_CACHE = Path.home() / "ЭКО.DOC"
            return _ROOT_CACHE
        od = _onedrive()
        legacy = Path.home() / "ЭКО.DOC"
        if od is None:
            _ROOT_CACHE = legacy
            return _ROOT_CACHE
        shared = od / "ЭКО.DOC"
        # одноразовый перенос локальной базы этого компьютера в общую
        if (legacy.is_dir() and legacy.resolve() != shared.resolve()
                and not (legacy / _MOVED_MARKER).exists()):
            try:
                _merge_local_into_shared(legacy, shared)
            except Exception as e:              # перенос не должен ронять запуск
                print(f"⚠ Перенос базы в OneDrive не удался: {e} — "
                      f"работаем с локальной {legacy}")
                _ROOT_CACHE = legacy
                return _ROOT_CACHE
        _ROOT_CACHE = shared
        return _ROOT_CACHE


def storage_mode() -> str:
    """Где держать базу: 'shared' (OneDrive, по умолчанию) или 'local'."""
    mode = str(_ui_config().get("storage", "")).lower()
    return "local" if mode == "local" else "shared"


def set_storage_mode(mode: str) -> dict:
    """Переключить хранилище и перенести данные в выбранную сторону.

    Возвращает {'mode', 'root', 'log'}. Перенос — то же слияние, что при
    первом запуске: чего нет — копируется, при конфликте площадки побеждает
    более свежая, проигравшая версия сохраняется рядом в папке-бэкапе."""
    global _ROOT_CACHE
    mode = "local" if str(mode).lower() == "local" else "shared"
    was = root()
    od = _onedrive()
    shared = (od / "ЭКО.DOC") if od else None
    local = Path.home() / "ЭКО.DOC"
    if mode == "shared" and shared is None:
        raise RuntimeError("OneDrive на этом компьютере не найден — общая база "
                           "недоступна. Оставлено хранение только на этом ПК.")
    target = shared if mode == "shared" else local
    log: list[str] = []
    with _MERGE_LOCK:
        if was.exists() and target.resolve() != was.resolve():
            log = _merge_local_into_shared(was, target, keep_source=True)
        cfg = _ui_config()
        cfg["storage"] = mode
        _ui_path().parent.mkdir(parents=True, exist_ok=True)
        _ui_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        _ROOT_CACHE = target
    return {"mode": mode, "root": str(target), "log": log}


def _merge_local_into_shared(local: Path, shared: Path,
                             keep_source: bool = False) -> list[str]:
    """Влить локальную базу в общую (OneDrive) и переименовать локальную.

    Правила: организации/площадки, которых нет в общей, — копируются целиком;
    при конфликте площадки побеждает более свежий context.json (последняя
    работа), проигравшая версия сохраняется рядом в папке-бэкапе.
    После переноса локальная папка переименовывается в
    «ЭКО.DOC.перенесено-в-OneDrive» (данные не удаляются)."""
    import shutil
    import socket
    from datetime import datetime

    log: list[str] = []
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    shared.mkdir(parents=True, exist_ok=True)
    for org_d in sorted(local.iterdir()):
        if not org_d.is_dir() or not (org_d / "org.json").exists():
            continue
        dst_org = shared / org_d.name
        dst_org.mkdir(exist_ok=True)
        if not (dst_org / "org.json").exists():
            shutil.copy2(org_d / "org.json", dst_org / "org.json")
            log.append(f"организация {org_d.name}: перенесена")
        for site_d in sorted(org_d.iterdir()):
            if not site_d.is_dir() or not (site_d / "context.json").exists():
                continue
            dst_site = dst_org / site_d.name
            _no_out = shutil.ignore_patterns("out")   # готовые документы — не данные
            if not dst_site.exists():
                shutil.copytree(site_d, dst_site, ignore=_no_out)
                log.append(f"площадка {org_d.name}/{site_d.name}: перенесена")
                continue
            # конфликт: та же площадка есть в общей базе — свежая побеждает
            lm = (site_d / "context.json").stat().st_mtime
            try:
                sm = (dst_site / "context.json").stat().st_mtime
            except OSError:
                sm = 0.0
            if lm > sm + 1:                      # локальная свежее (запас 1 с)
                backup = dst_org / f"{site_d.name}.бэкап-{stamp}"
                shutil.move(str(dst_site), str(backup))
                shutil.copytree(site_d, dst_site, ignore=_no_out)
                log.append(f"площадка {org_d.name}/{site_d.name}: локальная свежее — "
                           f"перенесена, прежняя в {backup.name}")
            else:
                log.append(f"площадка {org_d.name}/{site_d.name}: в общей базе "
                           f"свежее — оставлена общая")
    if keep_source:
        # переключение хранилища вручную: исходную папку не трогаем —
        # пользователь сам решит, удалять ли её
        log.append(f"источник оставлен как есть: {local}")
        return log
    # локальную папку переименовываем (не удаляем) — повторный перенос не нужен.
    # Если папка занята другим процессом (старый сервер, OneDrive-синк) —
    # оставляем её с файлом-маркером: данные уже в общей базе, работа
    # продолжается с ней, а перенос при следующих запусках не повторяется.
    moved = local.with_name("ЭКО.DOC.перенесено-в-OneDrive")
    if moved.exists():
        moved = local.with_name(f"ЭКО.DOC.перенесено-в-OneDrive-{stamp}")
    try:
        shutil.move(str(local), str(moved))
        log.append(f"локальная база переименована: {moved}")
    except OSError as e:
        (local / _MOVED_MARKER).write_text(
            f"База перенесена в {shared} ({stamp}).\n"
            f"Эта папка больше НЕ используется программой — её можно удалить.\n"
            f"(переименовать не удалось: {e})", encoding="utf-8")
        log.append(f"локальная папка занята — оставлена с маркером {_MOVED_MARKER}")
    try:
        host = socket.gethostname()
        (shared / f"перенос-{host}-{stamp}.txt").write_text(
            "\n".join(log), encoding="utf-8")
    except OSError:
        pass
    print("База ЭКО.DOC теперь в OneDrive (" + str(shared) + "):\n  " +
          "\n  ".join(log))
    return log


def _ui_path() -> Path:
    """Файл локальных настроек машины (папка результатов, режим хранения).

    Путь вычисляется КАЖДЫЙ раз и уважает ECODOC_HOME — иначе тесты писали бы
    в настоящий конфиг пользователя (уже случалось: тест переключил режим
    хранения базы на живой машине).
    """
    from ecodoc.ai.config import config_dir
    return config_dir() / "ui.json"


def _ui_config() -> dict:
    try:
        return json.loads(_ui_path().read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def set_results_root(path: str) -> Path:
    _ui_path().parent.mkdir(parents=True, exist_ok=True)
    cfg = _ui_config()
    cfg["results_dir"] = str(path)
    _ui_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return Path(path)


def results_root() -> Path:
    """Куда сохранять ГОТОВЫЕ документы (не в базу!).

    База (OneDrive) хранит только данные: context.json, org.json, отчёты
    приёма. Сгенерированные формы — расходный материал, их всегда можно
    пересоздать; кладём в локальную папку результатов (по умолчанию
    Загрузки/ЭКО.DOC, меняется в Сервисе или env ECODOC_RESULTS)."""
    env = os.environ.get("ECODOC_RESULTS")
    if env:
        return Path(env)
    cfg = _ui_config().get("results_dir")
    if cfg:
        return Path(cfg)
    return Path.home() / "Downloads" / "ЭКО.DOC"


def results_dir(org: str, site: str) -> Path:
    d = results_root() / slug(org) / slug(site)
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup_base(days: int = 7) -> dict:
    """Освободить место в базе: удалить готовые документы (out) и исходники
    в attachments старше `days` дней (свежие могут ждать анализа).
    Отчёты приёма (приём_*) и context/org.json не трогаются; записи реестра
    удалённых файлов чистятся, чтобы повторная загрузка работала."""
    import shutil
    import time as _t

    freed = files = 0
    cutoff = _t.time() - days * 86400
    rt = root()
    if not rt.exists():
        return {"freed": 0, "files": 0}

    def _size(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

    for org_d in rt.iterdir():
        if not org_d.is_dir() or not (org_d / "org.json").exists():
            continue
        for site_d in org_d.iterdir():
            if not site_d.is_dir():
                continue
            out = site_d / "out"
            if out.is_dir():
                freed += _size(out)
                files += sum(1 for f in out.rglob("*") if f.is_file())
                shutil.rmtree(out, ignore_errors=True)
            att = site_d / "attachments"
            if not att.is_dir():
                continue
            removed = set()
            for f in att.rglob("*"):
                if (not f.is_file() or f.name.startswith("приём_")
                        or f.name == "intake.json"):
                    continue
                try:
                    if f.stat().st_mtime < cutoff:
                        freed += f.stat().st_size
                        rel = str(f.relative_to(att))
                        f.unlink()
                        files += 1
                        removed.add(rel)
                        removed.add(f.name)
                except OSError:
                    pass
            # реестр: убрать записи удалённых файлов (иначе sha1-дедуп
            # молча пропустит повторную загрузку того же документа)
            reg_p = att / "intake.json"
            if removed and reg_p.exists():
                try:
                    reg = json.loads(reg_p.read_text(encoding="utf-8-sig"))
                    keep = [r for r in reg if r.get("file") not in removed]
                    reg_p.write_text(json.dumps(keep, ensure_ascii=False,
                                                indent=1), encoding="utf-8")
                except (OSError, json.JSONDecodeError):
                    pass
    # .корзину не трогаем: туда складываются удалённые площадки и организации,
    # и интерфейс обещает, что оттуда их можно вернуть. Чистка места не должна
    # уничтожать единственную резервную копию — для корзины есть своя команда.
    trash = rt / ".корзина"
    trash_mb = round(_size(trash) / (1024 * 1024), 1) if trash.is_dir() else 0
    return {"freed": freed, "files": files, "trash_mb": trash_mb}


def empty_trash(days: int = 0) -> dict:
    """Очистить корзину (по умолчанию — всю; days>0 — только старше N дней).

    Отдельная команда: пользователь должен решать это осознанно."""
    import time
    rt = root()
    trash = rt / ".корзина"
    if not trash.is_dir():
        return {"freed": 0, "items": 0}
    freed = items = 0
    edge = time.time() - days * 86400
    for item in list(trash.iterdir()):
        try:
            if days and item.stat().st_mtime > edge:
                continue
            size = _size(item) if item.is_dir() else item.stat().st_size
            shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink()
            freed += size
            items += 1
        except OSError:
            continue
    return {"freed": freed, "items": items}


def slug(name: str) -> str:
    """Имя организации/площадки → имя каталога на диске (публичный API).

    Длину каталога ограничиваем (~64 симв.): площадки называются полным
    адресом, а длинные пути ломают Word/Excel и упираются в лимит Windows.
    Полный адрес хранится в context.json (extra.site_address).

    Если имя пришлось обрезать, в конец добавляется короткий отпечаток полного
    имени: у соседних участков адреса совпадают первые 64 символа, и без
    отпечатка две РАЗНЫЕ площадки получали одну папку — данные первой молча
    затирались данными второй.
    """
    s = re.sub(r"[\\/:*?\"<>|]+", "", name).strip()
    s = re.sub(r"\s+", "_", s).strip(". ")  # «..» и трейлинг-точки — не имя
    if len(s) > 64:
        import hashlib
        tail = hashlib.sha1(s.encode("utf-8")).hexdigest()[:6]
        s = s[:57].rstrip("_. ") + "~" + tail
    return s or "org"


_slug = slug  # обратная совместимость


def org_dir(org: str) -> Path:
    return root() / _slug(org)


def site_dir(org: str, site: str) -> Path:
    return org_dir(org) / _slug(site)


def add_org(name: str, **requisites) -> Path:
    d = org_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    org = Organization(name=name, **{k: v for k, v in requisites.items()
                                     if k in Organization.__dataclass_fields__})
    path = d / "org.json"
    if path.exists():
        raise FileExistsError(f"Организация уже существует: {path}")
    path.write_text(json.dumps(asdict(org), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def add_site(org: str, site: str, address: str = "") -> Path:
    """Создать площадку. site — название, address — полный адрес площадки."""
    if not (org_dir(org) / "org.json").exists():
        raise FileNotFoundError(f"Сначала создайте организацию: ecodoc org add \"{org}\"")
    d = site_dir(org, site)
    (d / "attachments").mkdir(parents=True, exist_ok=True)
    (d / "out").mkdir(exist_ok=True)
    ctx_path = d / "context.json"
    if not ctx_path.exists():
        ctx = ReportContext()
        ctx.extra["site_name"] = site
        ctx.extra["site_address"] = address
        serialize.to_json(ctx, ctx_path)
    elif address:
        ctx = serialize.from_json(ctx_path)
        if not ctx.extra.get("site_address"):
            ctx.extra["site_address"] = address
            serialize.to_json(ctx, ctx_path)
    return ctx_path


def load_context(org: str, site: str) -> ReportContext:
    """Контекст площадки; организация всегда берётся из org.json."""
    ctx_path = site_dir(org, site) / "context.json"
    if not ctx_path.exists():
        raise FileNotFoundError(f"Нет площадки: {ctx_path}. "
                                f"Создайте: ecodoc site add \"{org}\" \"{site}\"")
    ctx = serialize.from_json(ctx_path)
    org_json = org_dir(org) / "org.json"
    if org_json.exists():
        try:
            data = json.loads(org_json.read_text(encoding="utf-8-sig"))
            known = Organization.__dataclass_fields__
            ctx.organization = Organization(
                **{k: v for k, v in data.items() if k in known})
        except (OSError, json.JSONDecodeError, TypeError) as e:
            # битый org.json не должен закрывать доступ ко ВСЕМ площадкам:
            # реквизиты продублированы в context.json, работаем по ним
            broken = org_json.with_suffix(".json.битый")
            try:
                org_json.replace(broken)
            except OSError:
                pass
            ctx.extra.setdefault("_warnings", []).append(
                f"Файл реквизитов организации повреждён ({e}); отложен в "
                f"{broken.name}, реквизиты взяты из данных площадки — "
                f"проверьте их во вкладке ОРГАНИЗАЦИЯ и сохраните.")
    return ctx


def save_org(org: str, organization: Organization) -> Path:
    """Сохранить реквизиты организации в org.json (канонический источник).

    Пишем атомарно (tmp + replace), как context.json: обрыв записи на этом
    файле оставлял битый JSON, а он закрывает доступ ко всем площадкам."""
    path = org_dir(org) / "org.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(organization), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return path


def save_context(org: str, site: str, ctx: ReportContext) -> Path:
    # реквизиты организации канонично живут в org.json — если правились
    # (во вкладке «Данные»), пишем их туда, иначе правки терялись бы при
    # следующей загрузке (load_context перечитывает организацию из org.json).
    if (org_dir(org) / "org.json").exists():
        save_org(org, ctx.organization)
    return serialize.to_json(ctx, site_dir(org, site) / "context.json")


def _trash_dir() -> Path:
    d = root() / ".корзина"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _to_trash(src: Path, label: str) -> Path:
    """Переместить папку в корзину рабочего пространства (не удалять насовсем)."""
    import shutil
    from datetime import datetime

    if not src.exists():
        raise FileNotFoundError(src)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = _trash_dir() / f"{stamp}__{label}"
    shutil.move(str(src), str(dest))
    return dest


def delete_site(org: str, site: str) -> Path:
    """Удалить площадку (перенос в корзину). Возвращает путь в корзине."""
    d = site_dir(org, site)
    if not d.exists():
        raise FileNotFoundError(f"Нет площадки: {org}/{site}")
    return _to_trash(d, f"{slug(org)}__{slug(site)}")


def delete_org(org: str) -> Path:
    """Удалить организацию со всеми площадками (перенос в корзину)."""
    d = org_dir(org)
    if not d.exists():
        raise FileNotFoundError(f"Нет организации: {org}")
    return _to_trash(d, slug(org))


def list_tree() -> dict[str, list[str]]:
    """{организация: [площадки]} по факту на диске."""
    out: dict[str, list[str]] = {}
    if not root().exists():
        return out
    for od in sorted(root().iterdir()):
        if not (od / "org.json").exists():
            continue
        sites = [sd.name for sd in sorted(od.iterdir())
                 if sd.is_dir() and (sd / "context.json").exists()]
        out[od.name] = sites
    return out


def resolve(args) -> ReportContext:
    """Единая точка для CLI: либо -i context.json, либо --org/--site."""
    if getattr(args, "input", None):
        return serialize.from_json(args.input)
    if getattr(args, "org", None) and getattr(args, "site", None):
        return load_context(args.org, args.site)
    raise SystemExit("Укажите -i context.json ИЛИ --org и --site (см. ecodoc org list)")


def out_dir(args, default: str = "out") -> Path:
    if getattr(args, "outdir", None) and args.outdir != default:
        return Path(args.outdir)
    if getattr(args, "org", None) and getattr(args, "site", None):
        # готовые документы — в папку результатов, НЕ в базу (OneDrive)
        return results_dir(args.org, args.site)
    return Path(getattr(args, "outdir", default) or default)
