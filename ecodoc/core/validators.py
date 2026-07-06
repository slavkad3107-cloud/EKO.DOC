"""Проверки российских реквизитов (контрольные суммы).

Ловят опечатки и ошибки OCR в ИНН/КПП/ОГРН до генерации документов —
неверный ИНН в декларации грозит штрафом по ст. 8.5 КоАП.
"""
from __future__ import annotations


def inn_valid(inn: str) -> bool:
    """Проверка контрольной суммы ИНН (10 — юрлицо, 12 — ИП/физлицо)."""
    inn = (inn or "").strip()
    if not inn.isdigit():
        return False
    if len(inn) == 10:
        w = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        c = sum(int(inn[i]) * w[i] for i in range(9)) % 11 % 10
        return c == int(inn[9])
    if len(inn) == 12:
        w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        c1 = sum(int(inn[i]) * w1[i] for i in range(10)) % 11 % 10
        c2 = sum(int(inn[i]) * w2[i] for i in range(11)) % 11 % 10
        return c1 == int(inn[10]) and c2 == int(inn[11])
    return False


def ogrn_valid(ogrn: str) -> bool:
    """Контрольная цифра ОГРН (13) / ОГРНИП (15)."""
    ogrn = (ogrn or "").strip()
    if not ogrn.isdigit():
        return False
    if len(ogrn) == 13:
        return int(ogrn[:12]) % 11 % 10 == int(ogrn[12])
    if len(ogrn) == 15:
        return int(ogrn[:14]) % 13 % 10 == int(ogrn[14])
    return False
