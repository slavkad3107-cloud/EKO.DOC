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
    return Path(os.environ.get("ECODOC_WORKSPACE", "ecodoc_workspace"))


def _slug(name: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|]+", "", name).strip()
    s = re.sub(r"\s+", "_", s).strip(". ")  # «..» и трейлинг-точки — не имя
    return s or "org"


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


def add_site(org: str, site: str) -> Path:
    if not (org_dir(org) / "org.json").exists():
        raise FileNotFoundError(f"Сначала создайте организацию: ecodoc org add \"{org}\"")
    d = site_dir(org, site)
    (d / "attachments").mkdir(parents=True, exist_ok=True)
    (d / "out").mkdir(exist_ok=True)
    ctx_path = d / "context.json"
    if not ctx_path.exists():
        ctx = ReportContext()
        ctx.extra["site_name"] = site
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


def save_context(org: str, site: str, ctx: ReportContext) -> Path:
    return serialize.to_json(ctx, site_dir(org, site) / "context.json")


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
