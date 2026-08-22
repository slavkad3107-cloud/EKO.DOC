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


def build_package(report, out_root, year=None, force: bool = False) -> dict:
    """Собрать папку пакета к подаче. Возвращает {dir, files, issues, errors, checklist}.

    При ошибках preflight файлы НЕ выпускаются без force: пакет с ошибками
    выглядит готовым к подаче, а его завернут в приёмке."""
    ctx = report.ctx
    o = ctx.organization
    year = year or ctx.period.year
    stem = f"{report.code}_{year}" if year else f"ЧЕРНОВИК_{report.code}"
    pkg = Path(out_root) / f"{(o.inn or 'org')}_{stem}"
    pkg.mkdir(parents=True, exist_ok=True)

    issues = report.validate()
    errors = [i for i in issues if i.level == "error"]

    files: dict[str, Path] = {}
    if errors and not force:
        checklist = _write_checklist(pkg, report, issues, files, {})
        return {"dir": pkg, "files": files, "issues": issues, "errors": errors,
                "checklist": checklist, "mchd": {}, "blocked": True,
                "note": (f"Файлы не выпущены: {len(errors)} ошибок preflight. "
                         f"Исправьте данные (см. ЧЕКЛИСТ.md) или соберите "
                         f"пакет принудительно.")}

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
            "checklist": checklist, "mchd": mchd, "blocked": False}


_LKPP_STEPS = [
    f"1. Войдите в ЛКПП ({_LKPP_INSTR.rsplit('/', 1)[0]}) через ЕСИА/Госуслуги.",
    "2. **Мои отчёты → «Новый отчёт»** → выберите форму → **«Импорт XML»/"
    "«Загрузить из файла»** и укажите XML из этого пакета.",
    "3. Проверьте подтянувшиеся данные, при необходимости дозаполните в интерфейсе.",
    "4. Подпишите отчёт **УКЭП** и отправьте. Статус — в «Мои отчёты» (цель «Принято»).",
    f"5. Требования к формату XML — {_LKPP_OPER} и {_LKPP_INSTR}.",
]


def _destination(code: str) -> dict:
    """Куда и как подаётся конкретная форма.

    Раньше чек-лист всем предлагал «Импорт XML в ЛКПП» — включая кадастр СПб
    (подсистема правительства города) и статистические формы Росстата."""
    lk_xml = "XML для загрузки в ЛКПП (конверт Модуля природопользователя)"
    inner = ("внутренний XML программы — для ЛКПП не годится, "
             "подавайте печатную форму")
    if code in ("declaration-nvos", "pek", "2tp-waste"):
        return {"where": "Личный кабинет природопользователя (ЛКПП РПН)",
                "xml_label": lk_xml, "steps": _LKPP_STEPS}
    if code == "waste-report-iii":
        # Отдельной подачи нет: п. 7 ст. 18 ФЗ-89 — сведения об отходах для
        # III категории подаются в составе отчёта ПЭК (Приказ № 173). XML этой
        # справки — внутренний, ЛКПП его не примет, поэтому шагов «импортируйте
        # XML в ЛКПП» быть не должно.
        return {
            "where": "справочный документ — отдельно не подаётся; данные "
                     "переносятся в раздел 4 отчёта ПЭК (форма «pek»)",
            "xml_label": inner,
            "steps": [
                "1. Отдельной формы для этих сведений нет (приказ № 30 отменён с "
                "01.01.2021): по п. 7 ст. 18 ФЗ-89 они входят в отчёт ПЭК.",
                "2. Перенесите листы «Движение отходов» (табл. 4.2) и «Получатели» "
                "(табл. 4.3) в раздел 4 отчёта ПЭК — сформируйте форму «pek».",
                "3. Отчёт ПЭК подаётся до 25 марта в ЛКПП (федеральный надзор) "
                "или в орган субъекта РФ (региональный надзор).",
            ]}
    if code == "cadastre-spb":
        return {
            "where": "подсистема «Ведение регионального кадастра отходов» ГИС СПб "
                     "(или kadastr@kpoos.gov.spb.ru)",
            "xml_label": inner,
            "steps": [
                "1. Войдите в подсистему кадастра отходов на портале Правительства СПб "
                "(вход по УКЭП организации).",
                "2. Заполните формы 1–5 по данным печатной формы из этого пакета.",
                "3. Подпишите УКЭП и отправьте; при недоступности подсистемы — "
                "подписанный .xlsx на kadastr@kpoos.gov.spb.ru.",
                "4. Для ЛО и других регионов действует свой порядок — сверьте с "
                "региональным НПА.",
            ]}
    if code in ("2tp-air", "2tp-water", "4-oos"):
        org = ("Бассейновое водное управление Росводресурсов"
               if code == "2tp-water" else "территориальный орган Росстата")
        return {
            "where": f"{org} (форма статистического наблюдения)",
            "xml_label": inner,
            "steps": [
                f"1. Форма сдаётся в {org}, а не в ЛКПП.",
                "2. Используйте систему сбора отчётности респондента "
                "(Модуль респондента Росстата / ГИС ЦП «Вода») или личный кабинет "
                "респондента websbor.rosstat.gov.ru.",
                "3. Перенесите данные из печатной формы пакета, подпишите УКЭП, отправьте.",
            ]}
    return {"where": "уточните адресата по основанию формы",
            "xml_label": inner,
            "steps": ["1. Способ подачи для этой формы в программе не описан — "
                      "сверьте с НПА из раздела «основание»."]}


def _deadline(code: str, year) -> str:
    try:
        from ecodoc.calendar.engine import deadline_note
        return deadline_note(code, year or 0)
    except Exception:
        return ""


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
    dest = _destination(report.code)
    lines = []
    lines.append(f"# Чек-лист подачи — {report.title}\n")
    lines.append(f"Организация: **{o.name}** (ИНН {o.inn})  ·  отчётный год: "
                 f"{report.ctx.period.year or '— НЕ УКАЗАН'}\n")
    lines.append(f"**Куда подавать:** {dest['where']}\n")
    note = _deadline(report.code, report.ctx.period.year)
    if note:
        lines.append(f"**Срок:** {note}\n")

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
    if not files:
        lines.append("- (файлы не выпущены: сначала исправьте ошибки из раздела 1)")
    for kind, p in files.items():
        label = {"xml": dest["xml_label"],
                 "print": "Печатная форма (проверка глазами, не для подачи)"}.get(kind, kind)
        lines.append(f"- `{Path(p).name}` — {label}")
    if not any(k == "xml" for k in files) and files:
        lines.append("- (XML не формируется — эта форма загрузкой файла не подаётся)")
    lines.append("")

    lines.append(f"## 3. Как подать: {dest['where']}\n")
    for step in dest["steps"]:
        lines.append(step)
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
