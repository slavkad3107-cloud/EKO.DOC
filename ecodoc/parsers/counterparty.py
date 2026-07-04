"""Проверка контрагента (получателя отходов) по ИНН.

Открытого бесплатного API «ИНН → лицензия на отходы» нет: реестр лицензий
Росприроднадзора живёт в закрытом портале ГИС ТОР КНД. Поэтому проверяем
то, что доступно без ключей — статус юрлица через ЕГРЮЛ — и даём прямую
ссылку на реестр КНД для ручной проверки лицензии на обращение с отходами.
"""
from __future__ import annotations

from ecodoc.parsers.egrul import EgrulError, lookup

KND_REGISTRY = "https://knd.gov.ru/licenses-registry"


def check(inn: str) -> dict:
    """Вернуть {'inn','name','ogrn','status','license_check_url','note'}.

    Никогда не бросает: недоступность ЕГРЮЛ отражается в note.
    """
    out = {"inn": inn, "name": "", "ogrn": "", "status": "",
           "license_check_url": KND_REGISTRY, "note": ""}
    try:
        r = lookup(inn)
        out["name"] = r.get("short_name") or r.get("name", "")
        out["ogrn"] = r.get("ogrn", "")
        out["status"] = "найден в ЕГРЮЛ/ЕГРИП"
    except EgrulError as e:
        out["note"] = f"ЕГРЮЛ: {e}"
    out["note"] = (out["note"] + " " if out["note"] else "") + (
        "Лицензию на обращение с отходами I–IV класса проверьте в реестре "
        "ГИС ТОР КНД по ИНН: " + KND_REGISTRY)
    return out


def render(inn: str) -> str:
    c = check(inn)
    lines = [f"── Контрагент ИНН {inn} ──"]
    if c["name"]:
        lines.append(f"  {c['name']}   ОГРН {c['ogrn']}   ({c['status']})")
    lines.append(f"  Лицензия на отходы (проверка вручную): {c['license_check_url']}")
    if c["note"] and "ЕГРЮЛ:" in c["note"]:
        lines.append("  " + c["note"].split("Лицензию")[0].strip())
    return "\n".join(lines)
