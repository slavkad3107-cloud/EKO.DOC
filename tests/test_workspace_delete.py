"""Удаление площадки и организации (в корзину)."""
from ecodoc.core import workspace


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    workspace.add_org("Орг", address="адрес")
    workspace.add_site("Орг", "Площадка 1", address="СПб, 1")
    workspace.add_site("Орг", "Площадка 2", address="СПб, 2")


def test_delete_site_moves_to_trash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    dest = workspace.delete_site("Орг", "Площадка 2")
    tree = workspace.list_tree()
    assert "Площадка_2" not in tree.get("Орг", [])
    assert "Площадка_1" in tree["Орг"]
    assert dest.exists()                     # перенесена, не стёрта
    assert ".корзина" in str(dest)


def test_delete_org_moves_to_trash(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    dest = workspace.delete_org("Орг")
    assert "Орг" not in workspace.list_tree()
    assert dest.exists()
    # org.json уехал в корзину вместе с площадками
    assert (dest / "org.json").exists()


def test_delete_missing_raises(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import pytest
    with pytest.raises(FileNotFoundError):
        workspace.delete_site("Орг", "Нет такой")
