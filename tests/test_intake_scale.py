"""Приём на масштабе: единый реестр, дедуп, устойчивость."""
from ecodoc.core import workspace
from ecodoc.intake import intake


def _ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    workspace.add_org("Орг", address="адрес")
    workspace.add_site("Орг", "СПб, 1", address="СПб, 1")
    return "Орг", "СПб, 1"


def test_registry_single_write_and_dedup(tmp_path, monkeypatch):
    org, site = _ws(tmp_path, monkeypatch)
    d = tmp_path / "src"
    d.mkdir()
    files = []
    for i in range(120):
        p = d / f"f{i}.txt"
        p.write_text(f"док {i} ИНН 7801234564", encoding="utf-8")
        files.append(str(p))
    # приём партиями (как из GUI)
    total = 0
    for k in range(0, 120, 60):
        names, _ = intake.store(files[k:k + 60], org, site)
        total += len(names)
    assert total == 120
    # повторная загрузка тех же — дедуп по sha1, новых нет
    names, _ = intake.store(files[:60], org, site)
    import json
    att = workspace.site_dir(org, site) / "attachments"
    reg = json.loads((att / "intake.json").read_text(encoding="utf-8"))
    assert len(reg) == 120                      # дублей не появилось


def test_same_name_different_content_kept(tmp_path, monkeypatch):
    org, site = _ws(tmp_path, monkeypatch)
    d = tmp_path / "s"
    d.mkdir()
    (d / "акт.txt").write_text("первый", encoding="utf-8")
    intake.store([str(d / "акт.txt")], org, site)
    (d / "акт.txt").write_text("второй — другое содержимое", encoding="utf-8")
    names, _ = intake.store([str(d / "акт.txt")], org, site)
    att = workspace.site_dir(org, site) / "attachments"
    txt = list(att.glob("акт*.txt"))
    assert len(txt) == 2                         # оба сохранены (разное содержимое)
