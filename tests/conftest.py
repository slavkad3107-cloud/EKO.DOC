"""Общие фикстуры: каждый тест получает ИЗОЛИРОВАННОЕ рабочее пространство.

Без этого workspace.root() на машине с OneDrive указал бы на реальную общую
базу пользователя (и мог бы запустить одноразовый перенос ~/ЭКО.DOC).
"""
from pathlib import Path

import pytest


@pytest.fixture()
def make_pdf():
    """Создать PDF с кириллицей: make_pdf(path, ["текст листа 1", ...]).

    Через insert_htmlbox, а не insert_text: при вставке текста шрифтом из файла
    PyMuPDF переиспользует набор глифов первой страницы, и буквы, которых там
    не было, подменяются похожими латинскими — «ИНН» превращается в «UHH», и
    тест начинает проверять не то, что задумано.
    """
    def _make(path, pages):
        import fitz
        doc = fitz.open()
        for text in pages:
            page = doc.new_page()
            page.insert_htmlbox(fitz.Rect(40, 40, 560, 780), f"<p>{text}</p>")
        doc.save(path)
        doc.close()
        return Path(path)
    return _make


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
    # папка бланков-образцов: пустая временная, иначе формы генерировались бы
    # по бланкам конкретного компьютера и тесты зависели бы от его содержимого
    forms = tmp_path / "_forms"
    forms.mkdir(exist_ok=True)
    monkeypatch.setenv("ECODOC_FORMS", str(forms))
    monkeypatch.setenv("ECODOC_FORMS_SEARCH", str(forms))
