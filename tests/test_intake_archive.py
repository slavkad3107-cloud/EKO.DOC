"""Проверки распаковки архивов при приёме документов."""
import zipfile

from ecodoc.core import workspace
from ecodoc.intake import intake


def _ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "ws"))
    workspace.add_org("Орг", address="адрес")
    workspace.add_site("Орг", "СПб, пр. Тест, 1", address="СПб, пр. Тест, 1")
    return "Орг", "СПб, пр. Тест, 1"


def test_zip_extraction_basic(tmp_path, monkeypatch):
    org, site = _ws(tmp_path, monkeypatch)
    z = tmp_path / "архив.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("акт.txt", "ФККО 4 71 101 01 52 1 лампы")
        zf.writestr("видео.mp4", b"\x00" * 10)   # не документ
    names, log = intake.store([str(z)], org, site)
    assert len(names) == 1                        # видео отфильтровано
    assert names[0].endswith("акт.txt")


def test_zip_duplicate_basenames(tmp_path, monkeypatch):
    """Два файла с одинаковым именем в разных папках — оба сохраняются."""
    org, site = _ws(tmp_path, monkeypatch)
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("п1/акт.txt", "первый")
        zf.writestr("п2/акт.txt", "второй")
    names, _ = intake.store([str(z)], org, site)
    assert len(names) == 2


def test_zip_slip_neutralised(tmp_path, monkeypatch):
    """Путь ../ в имени не выводит запись за пределы attachments."""
    org, site = _ws(tmp_path, monkeypatch)
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../уход.txt", "traversal")
    names, _ = intake.store([str(z)], org, site)
    att = workspace.site_dir(org, site) / "attachments"
    # файл сохранён ВНУТРИ attachments (имя срезано до basename)
    assert all((att / n).resolve().is_relative_to(att.resolve()) for n in names)
    assert not (tmp_path / "уход.txt").exists()


def test_nested_zip(tmp_path, monkeypatch):
    org, site = _ws(tmp_path, monkeypatch)
    inner = tmp_path / "in.zip"
    with zipfile.ZipFile(inner, "w") as izf:
        izf.writestr("внутр.txt", "данные")
    z = tmp_path / "внешний.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("верх.txt", "данные")
        zf.write(inner, "вложенный.zip")
    names, _ = intake.store([str(z)], org, site)
    assert len(names) == 2   # верх.txt + внутр.txt из вложенного
