"""Определение кода ОКТМО по адресу — БЕСПЛАТНО, без обязательного токена.

ОКТМО — обязательный реквизит места внесения платы за НВОС; чаще всего именно
его не хватает. Готового чистого бесплатного API «ОКТМО по адресу» без ключа
нет (сервис ФНС service.nalog.ru — JS-страница, Росстат — по сессии, DaData —
по токену), поэтому основной путь здесь — ОФФЛАЙН-справочник data/oktmo_ref.json
(без сети и ключа, пополняется экологом). Порядок источников:

  1. оффлайн-справочник по ключевым словам адреса (data/oktmo_ref.json);
  2. DaData — только если задан токен DADATA_TOKEN (необязательно);
  3. иначе — понятная ошибка с предложением вписать ОКТМО вручную.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ecodoc.core.refdata import oktmo_ref


class OktmoError(RuntimeError):
    pass


def by_address(address: str, timeout: int = 15) -> dict:
    """Вернуть {'oktmo', 'okato', 'fias', 'value', 'source'} по адресу.

    Сначала — оффлайн-справочник (бесплатно, без сети). Если не нашли и задан
    токен DaData — спросить DaData. Иначе — OktmoError (вписать вручную).
    """
    hit = _lookup_offline(address)
    if hit:
        return hit
    token = os.environ.get("DADATA_TOKEN", "")
    if token:
        return _dadata(address, token, timeout)
    raise OktmoError(
        "ОКТМО по адресу не найден в оффлайн-справочнике. Впишите ОКТМО вручную "
        "(1 раз — потом добавьте пару «ключевое слово адреса → ОКТМО» в "
        "data/oktmo_ref.json, и он будет подставляться сам). Полный классификатор "
        "ОКТМО — открытые данные Росстата. При желании можно задать бесплатный "
        "токен DaData (переменная DADATA_TOKEN) как онлайн-резерв.")


def _lookup_offline(address: str) -> dict | None:
    """Найти ОКТМО по вхождению ключевого слова справочника в адрес."""
    if not address:
        return None
    text = address.lower()
    ref = oktmo_ref()
    # сначала самые длинные ключи (специфичнее), чтобы «истринский» не перебивал
    for key in sorted(ref, key=len, reverse=True):
        if key.lower() in text:
            e = ref[key]
            return {"oktmo": e.get("oktmo", ""), "okato": e.get("okato", ""),
                    "fias": "", "value": e.get("value", address),
                    "source": "offline"}
    return None


def _dadata(address: str, token: str, timeout: int) -> dict:
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
            "fias": d.get("fias_id", ""), "value": suggestions[0].get("value", ""),
            "source": "dadata"}
