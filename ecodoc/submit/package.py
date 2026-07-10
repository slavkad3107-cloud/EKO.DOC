"""Сборка пакета к подаче отчёта в ЛК Природопользователя РПН.

Пакет = валидный XML (DATA_PACKET_NI) + печатная форма + при подаче
представителем — файлы МЧД + ЧЕКЛИСТ с пошаговой памяткой «что подписать и
куда загрузить». Автоотправку не делаем (см. ecodoc/submit/__init__.py).

МЧД задаётся в ctx.extra['mchd'] = {
    "path": "путь к EMCHD_1 .xml (схема 003)",
    "sig_path": "путь к откреплённой подписи доверителя .sig (необязательно)",
    "number": "номер доверенности (для поля «Реквизиты доверенности» в ЛКПП)",
    "powers": ["RPNDZ_REPORT", ...],
    "doveritel": "ИП Миних Е.А. (ИНН ...)",
    "predstavitel": "ИП Дубовик В.А. (ИНН ...)"}
"""
from __future__ import annotations

import shutil
from pathlib import Path

_LKPP_INSTR = "https://lk.rpn.gov.ru/instructions"
_LKPP_OPER = "https://lk.rpn.gov.ru/operators-page"

# код полномочия МЧД, без которого нельзя подать отчётность в ЛКПП
_POWER_REPORT = "RPNDZ_REPORT"


def build_package(report, out_root, year=None) -> dict:
    """Собрать папку пакета к подаче. Возвращает {dir, files, issues, errors, checklist}."""
    ctx = report.ctx
    o = ctx.organization
    year = year or ctx.period.year or "XXXX"
    stem = f"{report.code}_{year}"
    pkg = Path(out_root) / f"{(o.inn or 'org')}_{stem}"
    pkg.mkdir(parents=True, exist_ok=True)

    issues = report.validate()
    errors = [i for i in issues if i.level == "error"]

    files: dict[str, Path] = {}
    if getattr(report, "has_xml", True):
        try:
            files["xml"] = report.render_xml(pkg / f"{stem}.xml")
        except NotImplementedError:
            pass
    try:
        files["print"] = report.render_print(pkg / f"{stem}.xlsx")
    except NotImplementedError:
        pass

    mchd = _copy_mchd(ctx, pkg)
    checklist = _write_checklist(pkg, report, issues, files, mchd)
    return {"dir": pkg, "files": files, "issues": issues, "errors": errors,
            "checklist": checklist, "mchd": mchd}


def _copy_mchd(ctx, pkg: Path) -> dict:
    e = ctx.extra if isinstance(ctx.extra, dict) else {}
    m = e.get("mchd") or {}
    if not m:
        return {}
    out = dict(m)
    for key in ("path", "sig_path"):
        src = m.get(key)
        if src and Path(src).exists():
            dst = pkg / Path(src).name
            try:
                shutil.copy2(src, dst)
                out[key + "_copied"] = str(dst)
            except OSError:
                pass
    return out


def _write_checklist(pkg: Path, report, issues, files, mchd) -> Path:
    o = report.ctx.organization
    errors = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warning"]
    is_rep = bool(mchd)
    lines = []
    lines.append(f"# Чек-лист подачи в ЛКПП РПН — {report.title}\n")
    lines.append(f"Организация: **{o.name}** (ИНН {o.inn})  ·  отчётный год: "
                 f"{report.ctx.period.year or '—'}\n")

    lines.append("## 1. Проверка перед подачей (preflight)\n")
    if errors:
        lines.append("**❌ ОШИБКИ — исправьте до подачи (РПН отклонит):**")
        for i in errors:
            lines.append(f"- ✖ [{i.field}] {i.message}")
        lines.append("")
    if warns:
        lines.append("**⚠ Предупреждения — проверьте:**")
        for i in warns:
            lines.append(f"- ⚠ [{i.field}] {i.message}")
        lines.append("")
    if not errors and not warns:
        lines.append("✅ Ошибок и предупреждений нет.\n")

    lines.append("## 2. Файлы пакета\n")
    for kind, p in files.items():
        label = {"xml": "XML для загрузки в ЛКПП (формат Модуля природопользователя)",
                 "print": "Печатная форма (проверка глазами, не для подачи)"}.get(kind, kind)
        lines.append(f"- `{Path(p).name}` — {label}")
    if not any(k == "xml" for k in files):
        lines.append("- (XML не формируется — эта форма в ЛКПП не загружается)")
    lines.append("")

    lines.append("## 3. Как загрузить в ЛК Природопользователя\n")
    lines.append(f"1. Войдите в ЛКПП ({_LKPP_INSTR.rsplit('/',1)[0]}) через ЕСИА/Госуслуги.")
    lines.append("2. **Мои отчёты → «Новый отчёт»** → выберите форму → **«Импорт XML»/"
                 "«Загрузить из файла»** и укажите XML из этого пакета.")
    lines.append("3. Проверьте подтянувшиеся данные, при необходимости дозаполните в интерфейсе.")
    lines.append("4. Подпишите отчёт **УКЭП** и отправьте. Статус смотрите в «Мои отчёты» "
                 "(цель — «Принято»).")
    lines.append(f"5. Требования к формату/структуре XML — {_LKPP_OPER} и {_LKPP_INSTR}.")
    lines.append("")

    if is_rep:
        lines.append("## 4. Подача представителем по МЧД\n")
        powers = [str(p).upper() for p in (mchd.get("powers") or [])]
        has_report = _POWER_REPORT in powers
        lines.append(f"- Доверитель: {mchd.get('doveritel', '—')}")
        lines.append(f"- Представитель (подписант): {mchd.get('predstavitel', '—')}")
        lines.append(f"- Номер МЧД: **{mchd.get('number', '— указать')}**")
        lines.append(f"- Полномочия: {', '.join(powers) or '—'}")
        if not has_report:
            lines.append(f"  - ❌ **НЕТ кода `{_POWER_REPORT}`** — без него отчётность подать "
                         "нельзя. Выпустите/дополните МЧД (код «Формирование и подписание "
                         "отчётности через ЛКП»).")
        else:
            lines.append(f"  - ✅ есть `{_POWER_REPORT}` — покрывает 2-ТП, декларацию НВОС, ПЭК.")
        lines.append("- Порядок в ЛКПП: **Сведения об организации → Должностное лицо → "
                     "«Является руководителем» = НЕТ → «Реквизиты доверенности» = номер МЧД**; "
                     "загрузите файл МЧД (`.xml`) в «Скан-образ доверенности» (+ `.sig` "
                     "доверителя в «Подпись доверенности»). Отчёт подписывается УКЭП "
                     "представителя.")
        lines.append("- Рекомендуется заранее загрузить МЧД в распределённый реестр ФНС/ЕСИА "
                     "(пройдёт форматно-логический контроль). МЧД — формат EMCHD_1, схема 003.")
        lines.append("")
    else:
        lines.append("## 4. Подпись\n")
        lines.append("- Отчёт подписывается **УКЭП** руководителя/ИП. Если подаёт "
                     "представитель — приложите МЧД (задайте `extra.mchd`, код "
                     f"`{_POWER_REPORT}`) и перегенерируйте пакет.")
        lines.append("")

    lines.append("---")
    lines.append("_Автоотправка по API РПН в ЭКО.DOC не реализована намеренно: нужна "
                 "индивидуальная заявка на OD@rpn.gov.ru под ОГРН и подпись через "
                 "КриптоПро. Приложение готовит пакет — подача и подпись за пользователем._")

    path = pkg / "ЧЕКЛИСТ.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
