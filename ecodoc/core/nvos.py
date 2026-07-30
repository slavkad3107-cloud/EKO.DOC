"""Код объекта НВОС: единая проверка формата и разбор.

Формат из ТЗ: **40-0278-013459-П** — 2 цифры (регион) − 4 цифры − 6 цифр −
буква категории. «прочее не то».

До этого проверка была в трёх местах и по-разному: `xmlutil._is_nvos_code`
принимал только П/Т/О/Л, регулярка в `extractor` — любую заглавную букву
(включая латиницу), а промпт ИИ обещал суффикс «Б», который первая проверка
отбрасывала. Теперь правило одно.
"""
from __future__ import annotations

import re

# буквы категорий объектов НВОС (кириллица; латинские аналоги приводим к ней)
CATEGORY_LETTERS = "ПТОЛБ"
_LAT_TO_CYR = str.maketrans({"P": "П", "T": "Т", "O": "О", "L": "Л", "B": "Б",
                             "p": "П", "t": "Т", "o": "О", "l": "Л", "b": "Б"})

# 6 цифр по ТЗ; допускаем 5–7 — в старых свидетельствах встречается и так
CODE_RE = re.compile(r"^\d{2}-\d{4}-\d{5,7}-[" + CATEGORY_LETTERS + r"]$")
STRICT_RE = re.compile(r"^\d{2}-\d{4}-\d{6}-[" + CATEGORY_LETTERS + r"]$")
# для поиска в тексте документа
SEARCH_RE = re.compile(r"\b(\d{2}-\d{4}-\d{5,7}-[A-Za-zА-Яа-я])\b")

CATEGORY_NAME = {"П": "I категория", "Т": "II категория",
                 "О": "III категория", "Л": "IV категория",
                 "Б": "объект без категории"}


def normalize(code) -> str:
    """Привести к каноническому виду: убрать пробелы, латиницу → кириллица."""
    s = re.sub(r"\s+", "", str(code or "")).upper()
    return s.translate(_LAT_TO_CYR)


def is_valid(code, strict: bool = False) -> bool:
    """Валиден ли код объекта НВОС. strict — ровно 6 цифр в третьей группе."""
    s = normalize(code)
    return bool((STRICT_RE if strict else CODE_RE).match(s))


def region(code) -> str:
    """Код региона (первые две цифры) — по нему определяется, куда сдавать."""
    s = normalize(code)
    return s[:2] if is_valid(s) else ""


def category(code) -> str:
    """Категория объекта по последней букве кода."""
    s = normalize(code)
    return CATEGORY_NAME.get(s[-1], "") if is_valid(s) else ""


def find_all(text: str) -> list[str]:
    """Все коды НВОС в тексте документа, в каноническом виде, без повторов."""
    out = []
    for raw in SEARCH_RE.findall(text or ""):
        code = normalize(raw)
        if is_valid(code) and code not in out:
            out.append(code)
    return out


def problem(code) -> str:
    """Человекочитаемое объяснение, почему код не годится («» — код в порядке)."""
    s = normalize(code)
    if not s:
        return "код объекта НВОС не заполнен"
    if CODE_RE.match(s):
        return ""
    if re.match(r"^\d{2}:\d{2}:\d{6,7}:\d+$", s):
        return "это кадастровый номер участка, а не код объекта НВОС"
    return ("код не в формате объекта НВОС: нужно 40-0278-013459-П "
            "(2 цифры − 4 цифры − 6 цифр − буква П/Т/О/Л/Б)")
