"""Реквизиты юрлица/ИП по ИНН из открытого сервиса ФНС (egrul.nalog.ru).

Без ключей и регистрации: POST запрос → токен → JSON с найденными
записями. Используется при создании организации: эколог вводит только
ИНН, остальные реквизиты подтягиваются автоматически (и остаются
редактируемыми — источник открытый, сверка за человеком).
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

_BASE = "https://egrul.nalog.ru"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; EcoDoc)",
       "Accept": "application/json"}


class EgrulError(RuntimeError):
    pass


def _post_query(inn: str, timeout: int) -> str:
    data = urllib.parse.urlencode({
        "vyp3CaptchaToken": "", "page": "", "query": inn, "region": "",
        "PreventChromeAutocomplete": "",
    }).encode()
    req = urllib.request.Request(_BASE + "/", data=data, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode("utf-8"))
    if out.get("captchaRequired"):
        raise EgrulError("ФНС просит капчу — попробуйте позже "
                         "или заполните реквизиты вручную")
    token = out.get("t")
    if not token:
        raise EgrulError(f"неожиданный ответ ФНС: {out}")
    return token


def _get_rows(token: str, timeout: int) -> list[dict]:
    ms = int(time.time() * 1000)
    url = f"{_BASE}/search-result/{token}?r={ms}&_={ms}"
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode("utf-8"))
    return out.get("rows") or []


def lookup(inn: str, timeout: int = 20) -> dict:
    """Вернуть реквизиты по ИНН: name, short_name, inn, kpp, ogrn, address,
    director_name (что нашлось). EgrulError — если не нашли/сервис недоступен.
    """
    inn = "".join(ch for ch in str(inn) if ch.isdigit())
    if len(inn) not in (10, 12):
        raise EgrulError("ИНН должен содержать 10 (юрлицо) или 12 (ИП) цифр")
    try:
        rows = _get_rows(_post_query(inn, timeout), timeout)
        # результат бывает не мгновенным — одна повторная попытка
        if not rows:
            time.sleep(1.2)
            rows = _get_rows(_post_query(inn, timeout), timeout)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise EgrulError(f"сервис ФНС недоступен: {e}")
    row = next((r for r in rows if r.get("i") == inn), rows[0] if rows else None)
    if not row:
        raise EgrulError(f"ИНН {inn} не найден в ЕГРЮЛ/ЕГРИП")
    # поля ответа ФНС: n — полное имя, c — краткое, i — ИНН, p — КПП,
    # o — ОГРН, a — адрес, g — «Должность: ФИО» руководителя
    director, position = "", ""
    g = row.get("g") or ""
    if ":" in g:
        position, director = (s.strip() for s in g.split(":", 1))
    return {k: v for k, v in {
        "name": row.get("n", ""),
        "short_name": row.get("c", ""),
        "inn": row.get("i", inn),
        "kpp": row.get("p", ""),
        "ogrn": row.get("o", ""),
        "address": row.get("a", ""),
        "director_name": director,
        "director_position": position,
    }.items() if v}
