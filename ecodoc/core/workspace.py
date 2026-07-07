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


def root() -> Path:
    """Корень рабочего пространства.

    Приоритет: $ECODOC_WORKSPACE → ./ecodoc_workspace (если уже создан,
    обратная совместимость) → ~/ЭКО.DOC (стабильный путь: GUI и команда
    ecodoc запускаются из любой папки, данные — всегда в одном месте).
    """
    env = os.environ.get("ECODOC_WORKSPACE")
    if env:
        return Path(env)
    local = Path("ecodoc_workspace")
    if local.is_dir():
        return local
    return Path.home() / "ЭКО.DOC"


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
