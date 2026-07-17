"""Общие фикстуры: каждый тест получает ИЗОЛИРОВАННОЕ рабочее пространство.

Без этого workspace.root() на машине с OneDrive указал бы на реальную общую
базу пользователя (и мог бы запустить одноразовый перенос ~/ЭКО.DOC).
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "_ws_default"))
