"""Исключение отхода пользователем — «удалить позицию» насовсем.

Замечание эколога (07.09.2026): после удаления позиции во вкладке ОБЪЕКТ →
Отходы она возвращалась — из кандидатов («Сверка по источникам», «Проблемы
исходников»), из справок-актов (движение пересчитывается из актов) и из
таблиц ООС. Поэтому удаление — это не splice в браузере, а операция базы:

  * позиция, её акты, паспорт, сведения, строки ООС и подсказки кодов
    убираются из context.json;
  * кандидаты с этим кодом помечаются «отклонено» с причиной;
  * код заносится в extra.waste_excluded — приём (analyzer), сверка и
    проверка данных его больше не воскрешают, пока пользователь не снимет
    исключение (`restore`).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ecodoc.core.waste_agg import norm_fkko


def excluded_codes(ctx) -> set[str]:
    extra = ctx.extra if isinstance(getattr(ctx, "extra", None), dict) else {}
    out = set()
    for row in extra.get("waste_excluded") or []:
        code = norm_fkko(row.get("fkko") if isinstance(row, dict) else row)
        if code:
            out.add(code)
    return out


def is_excluded(ctx, fkko) -> bool:
    code = norm_fkko(fkko)
    return bool(code) and code in excluded_codes(ctx)


def _same(code: str, value) -> bool:
    return bool(code) and norm_fkko(value) == code


def forget(ctx, site_dir: str | Path | None, fkko: str) -> dict:
    """Удалить отход с кодом fkko отовсюду и исключить его. Контекст НЕ
    сохраняется здесь (вызывающий решает, когда писать на диск)."""
    code = norm_fkko(fkko)
    res = {"fkko": code, "wastes": 0, "acts": 0, "passports": 0, "oos": 0,
           "details": 0, "extras": 0, "candidates": 0}
    if not code:
        res["error"] = "не указан код ФККО"
        return res
    if not isinstance(ctx.extra, dict):
        ctx.extra = {}
    extra = ctx.extra

    before = len(ctx.wastes)
    ctx.wastes = [w for w in ctx.wastes if not _same(code, w.fkko_code)]
    res["wastes"] = before - len(ctx.wastes)

    before = len(ctx.waste_acts)
    ctx.waste_acts = [a for a in ctx.waste_acts if not _same(code, a.fkko_code)]
    res["acts"] = before - len(ctx.waste_acts)

    for key, field in (("waste_passports", "fkko"), ("oos_wastes", "fkko"),
                       ("fkko_seen", "fkko"), ("disposal_acts", "fkko")):
        items = extra.get(key)
        if not isinstance(items, list):
            continue
        kept = [it for it in items
                if not (isinstance(it, dict) and _same(code, it.get(field)))]
        gone = len(items) - len(kept)
        extra[key] = kept
        if key == "waste_passports":
            res["passports"] += gone
        elif key == "oos_wastes":
            res["oos"] += gone
        else:
            res["extras"] += gone

    details = extra.get("waste_details")
    if isinstance(details, dict):
        for k in [k for k in details if _same(code, k)]:
            details.pop(k, None)
            res["details"] += 1

    # кандидаты: всё с этим кодом — отклонено (не воскреснет в сверке/проверке)
    if site_dir:
        from ecodoc.intake import candidates
        store = candidates.Store(site_dir)
        for c in store.items:
            _coll, sel, _attr = candidates.parse_key(c.key)
            if _same(code, sel.get("fkko")) and c.state != candidates.REJECTED:
                c.state = candidates.REJECTED
                c.reason = "удалено пользователем (позиция исключена)"
                res["candidates"] += 1
        if res["candidates"]:
            store.save()

    rows = [r for r in (extra.get("waste_excluded") or []) if isinstance(r, dict)]
    if not any(norm_fkko(r.get("fkko")) == code for r in rows):
        rows.append({"fkko": code, "when": date.today().isoformat()})
    extra["waste_excluded"] = rows
    return res


def restore(ctx, fkko: str) -> bool:
    """Снять исключение (сам отход придётся загрузить/ввести заново)."""
    code = norm_fkko(fkko)
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    rows = [r for r in (extra.get("waste_excluded") or []) if isinstance(r, dict)]
    kept = [r for r in rows if norm_fkko(r.get("fkko")) != code]
    extra["waste_excluded"] = kept
    return len(kept) != len(rows)
