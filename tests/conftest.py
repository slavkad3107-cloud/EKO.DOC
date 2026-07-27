"""Общие фикстуры: каждый тест получает ИЗОЛИРОВАННОЕ рабочее пространство.

Без этого workspace.root() на машине с OneDrive указал бы на реальную общую
базу пользователя (и мог бы запустить одноразовый перенос ~/ЭКО.DOC).
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ECODOC_WORKSPACE", str(tmp_path / "_ws_default"))
    # и настройки ИИ: тесты не читают реальный ~/.ecodoc (конфиг и КЛЮЧИ
    # пользователя) и не ходят в сеть под его ключами
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path / "_cfg"))
    # ключи провайдеров из окружения машины тоже прячем — иначе результат
    # тестов зависит от того, у кого какие ключи прописаны
    from ecodoc.ai.config import DEFAULT_KEY_ENV
    for env in DEFAULT_KEY_ENV.values():
        monkeypatch.delenv(env, raising=False)
