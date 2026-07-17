"""Общая база в OneDrive: выбор корня и одноразовый перенос локальной базы."""
import json
import os
import time
from pathlib import Path

from ecodoc.core import workspace


def _make_site(root: Path, org: str, site: str, year: int):
    d = root / org / site
    d.mkdir(parents=True)
    (root / org / "org.json").write_text(
        json.dumps({"name": org}), encoding="utf-8")
    (d / "context.json").write_text(
        json.dumps({"period": {"year": year}}), encoding="utf-8")
    (d / "attachments").mkdir()
    return d


def test_root_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "custom"))
    assert workspace.root() == tmp_path / "custom"


def test_merge_moves_missing_and_renames_local(tmp_path):
    local, shared = tmp_path / "ЭКО.DOC", tmp_path / "OneDrive" / "ЭКО.DOC"
    _make_site(local, "ОРГ", "Площадка", 2025)
    log = workspace._merge_local_into_shared(local, shared)
    assert (shared / "ОРГ" / "Площадка" / "context.json").exists()
    assert (shared / "ОРГ" / "org.json").exists()
    assert not local.exists()                       # переименована
    assert (tmp_path / "ЭКО.DOC.перенесено-в-OneDrive").is_dir()
    assert any("перенесена" in s for s in log)


def test_merge_conflict_newer_local_wins_with_backup(tmp_path):
    local, shared = tmp_path / "ЭКО.DOC", tmp_path / "od" / "ЭКО.DOC"
    _make_site(shared, "ОРГ", "Площадка", 2024)     # общая — старее
    old = time.time() - 3600
    os.utime(shared / "ОРГ" / "Площадка" / "context.json", (old, old))
    _make_site(local, "ОРГ", "Площадка", 2025)      # локальная — свежее
    workspace._merge_local_into_shared(local, shared)
    data = json.loads((shared / "ОРГ" / "Площадка" / "context.json")
                      .read_text(encoding="utf-8"))
    assert data["period"]["year"] == 2025           # свежая победила
    backups = [p for p in (shared / "ОРГ").iterdir() if "бэкап" in p.name]
    assert backups                                   # прежняя не потеряна


def test_merge_conflict_newer_shared_kept(tmp_path):
    local, shared = tmp_path / "ЭКО.DOC", tmp_path / "od" / "ЭКО.DOC"
    _make_site(local, "ОРГ", "Площадка", 2024)      # локальная — старее
    old = time.time() - 3600
    os.utime(local / "ОРГ" / "Площадка" / "context.json", (old, old))
    _make_site(shared, "ОРГ", "Площадка", 2025)
    workspace._merge_local_into_shared(local, shared)
    data = json.loads((shared / "ОРГ" / "Площадка" / "context.json")
                      .read_text(encoding="utf-8"))
    assert data["period"]["year"] == 2025           # общая осталась
    assert not any("бэкап" in p.name for p in (shared / "ОРГ").iterdir())
