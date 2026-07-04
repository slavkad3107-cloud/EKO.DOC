"""Определение кода ОКТМО по адресу через DaData (нужен бесплатный токен).

ОКТМО — обязательный реквизит места внесения платы за НВОС; чаще всего
именно его не хватает. DaData возвращает oktmo прямо в подсказке адреса.
Токен бесплатный (регистрация на dadata.ru, до 10 000 запросов/сутки),
задаётся переменной окружения DADATA_TOKEN.
"""
from __future__ import annotations

import json
import os
import urllib.request


class OktmoError(RuntimeError):
    pass


def by_address(address: str, timeout: int = 15) -> dict:
    """Вернуть {'oktmo', 'okato', 'fias', 'value'} по адресу/городу.

    OktmoError — если нет токена, адрес не распознан или сервис недоступен.
    """
    token = os.environ.get("DADATA_TOKEN", "")
    if not token:
        raise OktmoError(
            "ОКТМО по адресу требует бесплатный токен DaData. Получите на "
            "dadata.ru (регистрация → API-ключ) и задайте переменную окружения "
            "DADATA_TOKEN. Либо впишите ОКТМО вручную.")
    req = urllib.request.Request(
        "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address",
        data=json.dumps({"query": address, "count": 1}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": f"Token {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise OktmoError("DaData отклонил токен (проверьте DADATA_TOKEN "
                             "или суточный лимит).")
        raise OktmoError(f"DaData: HTTP {e.code}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise OktmoError(f"DaData недоступен: {e}")
    suggestions = out.get("suggestions") or []
    if not suggestions:
        raise OktmoError(f"адрес не распознан: {address}")
    d = suggestions[0].get("data") or {}
    if not d.get("oktmo"):
        raise OktmoError("ОКТМО для этого адреса не определён — уточните адрес.")
    return {"oktmo": d.get("oktmo", ""), "okato": d.get("okato", ""),
            "fias": d.get("fias_id", ""), "value": suggestions[0].get("value", "")}
