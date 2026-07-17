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


def _merge_local_into_shared(local: Path, shared: Path) -> list[str]:
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
            if not dst_site.exists():
                shutil.copytree(site_d, dst_site)
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
                shutil.copytree(site_d, dst_site)
                log.append(f"площадка {org_d.name}/{site_d.name}: локальная свежее — "
                           f"перенесена, прежняя в {backup.name}")
            else:
                log.append(f"площадка {org_d.name}/{site_d.name}: в общей базе "
                           f"свежее — оставлена общая")
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


def slug(name: str) -> str:
    """Имя организации/площадки → имя каталога на диске (публичный API).

    Длину каталога ограничиваем (~64 симв.): площадки называются полным
    адресом, а длинные пути ломают Word/Excel и упираются в лимит Windows.
    Полный адрес хранится в context.json (extra.site_address).
    """
    s = re.sub(r"[\\/:*?\"<>|]+", "", name).strip()
    s = re.sub(r"\s+", "_", s).strip(". ")  # «..» и трейлинг-точки — не имя
    if len(s) > 64:
        s = s[:64].rstrip("_. ")
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
        data = json.loads(org_json.read_text(encoding="utf-8-sig"))
        known = Organization.__dataclass_fields__
        ctx.organization = Organization(**{k: v for k, v in data.items() if k in known})
    return ctx


def save_org(org: str, organization: Organization) -> Path:
    """Сохранить реквизиты организации в org.json (канонический источник)."""
    path = org_dir(org) / "org.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(organization), ensure_ascii=False, indent=2),
                    encoding="utf-8")
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
        return site_dir(args.org, args.site) / "out"
    return Path(getattr(args, "outdir", default) or default)
