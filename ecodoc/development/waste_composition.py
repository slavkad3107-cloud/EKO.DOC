"""Справка о компонентном составе отхода по данным ООС/ПНООЛР — проект
протокола определения состава (исходные данные для аккредитованной
лаборатории).

Замечание эколога (07.09.2026): «ООС — основополагающий документ по отходам;
протоколы для паспортов должны быть сделаны на основе данных из него».
Лаборатории для протокола нужен заявленный состав — вот он, по каждому
отходу, с указанием файла и листа, откуда взят.

Структура — по реальным актам приёмки проб и протоколам ИЦ ООО «ТАСИС»
для ООО «ЦЭД» (Формы/Разработка/Протоколы: «акт о.п_ТБО», «прот.ТБО»,
«прот. _бетон_5 кл», «26212_25…»): реквизиты заказчика (наименование,
адрес, ИНН, ОГРН), место отбора проб (фактический адрес площадки), цель —
«Определение количественного состава отхода», наименование вида отхода,
код ФККО, агрегатное состояние и физическая форма пробы, метод
(«Морфологический состав (содержание каждого составляющего компонента
твёрдых отходов производства и потребления)», МИ М-27-2023), таблица
«Наименование определяемого показателя (компонента) — Результат, %»,
итого 100, ответственный за оформление.

Данные: ctx.extra['waste_passports'] (состав, происхождение, агрегатное
состояние из ИИ-разбора ООС/ПНООЛР/паспортов), ctx.wastes (класс,
наименование), кандидаты площадки (файл и лист-источник строки отхода).
Состав приводится к % с суммой ровно 100 (waste_refdata.normalize_components);
если сумма > 105 % — файл не создаётся, отход попадает в gaps.
Оформление — как в waste_passport (Times New Roman 12, «Table Grid»).
"""
from __future__ import annotations

from pathlib import Path

from ecodoc.core import fkko as _fkko
from ecodoc.core import waste_refdata as R
from ecodoc.core.models import ReportContext
from ecodoc.core.waste_agg import norm_fkko
from ecodoc.development.waste_passport import (_AGG, _fix_widths, _set,
                                               aggregate_state)

TITLE = "СПРАВКА О КОМПОНЕНТНОМ СОСТАВЕ ОТХОДА"
SUBTITLE = ("(проект протокола определения состава по данным проектной "
            "документации — раздел ООС / ПНООЛР)")
PURPOSE = "Определение количественного состава отхода"
METHOD_MORPH = ("Морфологический состав (содержание каждого составляющего "
                "компонента твёрдых отходов производства и потребления), "
                "МИ по области аккредитации лаборатории (в протоколах ТАСИС — "
                "М-27-2023) — заявленный состав расчётно, по данным ООС/ПНООЛР")
METHOD_CHEM = ("Химический (компонентный) состав — расчётно, по данным "
               "ООС/ПНООЛР")
NOTE_LAB = ("Настоящая справка составлена по данным проектной документации "
            "(раздел ООС / ПНООЛР) и является исходными данными (заявленным "
            "составом) для отбора проб и протокола аккредитованной "
            "лаборатории. Для паспорта отхода I–IV класса опасности состав "
            "подтверждается протоколом исследований (измерений) "
            "аккредитованной испытательной лаборатории (ст. 14 Федерального "
            "закона от 24.06.1998 № 89-ФЗ; Порядок паспортизации, утв. "
            "приказом Минприроды России от 15.05.2026 № 286).")


def _passport_for(ctx: ReportContext, code: str) -> dict:
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    for p in extra.get("waste_passports") or []:
        if isinstance(p, dict) and norm_fkko(p.get("fkko")) == code:
            return p
    return {}


def _components(p: dict) -> list[dict]:
    return [c for c in (p.get("components") or [])
            if isinstance(c, dict) and str(c.get("name") or "").strip()]


def _pct(v):
    return R.parse_value(v)


def _source_lines(ctx: ReportContext, code: str, p: dict,
                  site_dir: str | Path | None) -> list[str]:
    """«файл (лист N)» — из кандидатов wastes[fkko=…] или из _src паспорта."""
    out: list[str] = []
    if site_dir:
        from ecodoc.intake import candidates
        for c in candidates.Store(site_dir).items:
            coll, sel, _attr = candidates.parse_key(c.key)
            if coll == "wastes" and norm_fkko(sel.get("fkko")) == code and c.file:
                line = c.file + (f" (лист {c.page})" if c.page else "")
                if line not in out:
                    out.append(line)
    src = str(p.get("_src") or "").strip()
    if src and src not in out:
        out.append(src)
    return out


def oos_stage_allowed(ctx: ReportContext, code: str) -> bool:
    """Правило эколога (07.09.2026): справки-протоколы делаются по разделу
    СТРОИТЕЛЬНЫХ отходов ООС; эксплуатационные — только если пользователь
    решил их добавить (extra.oos_wastes[*].decision == "add", см.
    ai/analyzer._merge_oos_wastes). Нет записи в oos_wastes — не мешаем."""
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    rows = [x for x in (extra.get("oos_wastes") or []) if isinstance(x, dict)
            and norm_fkko(x.get("fkko")) == code]
    if not rows:
        return True
    for x in rows:
        stage = str(x.get("stage") or "").lower()
        if "строит" in stage or stage == "construction":
            return True
        if str(x.get("decision") or "").lower() == "add":
            return True
    return False


def _targets(ctx: ReportContext) -> list[tuple[str, str, int, dict]]:
    """(код, наименование, класс, паспорт-словарь) — отходы I–IV класса и
    V класса с известным составом. Записи из ООС/ПНООЛР — только стадии
    строительства (или эксплуатационные с решением «добавить»)."""
    from ecodoc.development.waste_passport import passport_kind

    seen: set[str] = set()
    out = []
    for w in ctx.wastes:
        code = norm_fkko(w.fkko_code)
        if not code or code in seen:
            continue
        seen.add(code)
        try:
            hazard = int(w.hazard_class)
        except (TypeError, ValueError):
            hazard = 0
        p = _passport_for(ctx, code)
        if p and passport_kind(p) == "oos" and not oos_stage_allowed(ctx, code):
            p = {}
        out.append((code, w.name or str(p.get("name") or ""), hazard, p))
    # отходы, которые есть только в справочнике паспортов (ООС загружен, актов нет)
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    for p in extra.get("waste_passports") or []:
        if not isinstance(p, dict):
            continue
        code = norm_fkko(p.get("fkko"))
        if not code or code in seen:
            continue
        if passport_kind(p) == "oos" and not oos_stage_allowed(ctx, code):
            continue
        seen.add(code)
        try:
            hazard = int(p.get("hazard_class") or 0)
        except (TypeError, ValueError):
            hazard = 0
        out.append((code, str(p.get("name") or ""), hazard, p))
    return out


def prepared(ctx: ReportContext) -> list[dict]:
    """Состав по каждому отходу после нормализации: {code, name, hazard,
    passport, components, note} — общий вход для generate() и gaps()."""
    out = []
    for code, name, hazard, p in _targets(ctx):
        raw = _components(p)
        comps, note = R.normalize_components(
            raw, source=str(p.get("_src") or "ООС/ПНООЛР"))
        out.append({"code": code, "name": name, "hazard": hazard, "passport": p,
                    "raw": raw, "components": comps, "note": note})
    return out


def _is_morph(comps: list[dict]) -> bool:
    from ecodoc.development.waste_passport import _MORPH_WORDS
    names = [str(c.get("name") or "").lower() for c in comps]
    morph = sum(1 for n in names if any(k in n for k in _MORPH_WORDS))
    return bool(morph) and morph >= len(names) / 2


def generate(ctx: ReportContext, out_dir: str | Path,
             site_dir: str | Path | None = None) -> list[Path]:
    """По одному .docx на отход I–IV класса (и V — если есть состав) с
    компонентным составом из extra.waste_passports, приведённым к 100 %."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.shared import Cm, Pt

    out_dir = Path(out_dir)
    paths: list[Path] = []
    org = ctx.organization
    obj = next((o for o in ctx.objects if R._OBJ_CODE.match(
        str(o.code or "").strip().upper())), ctx.objects[0] if ctx.objects else None)
    site_address = R.site_address_for(ctx)
    for item in prepared(ctx):
        code, name, hazard, p = (item["code"], item["name"], item["hazard"],
                                 item["passport"])
        comps = item["components"]
        if not comps:
            continue                      # нет состава или сумма не сходится
        if not (1 <= hazard <= 4) and hazard != 5:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        doc = Document()
        st = doc.styles["Normal"]
        st.font.name, st.font.size = "Times New Roman", Pt(12)
        st.paragraph_format.space_after = Pt(0)
        for s in doc.sections:
            s.left_margin, s.right_margin = Cm(2), Cm(1.5)

        # шапка лаборатории — поля под заполнение ИЦ (как в протоколах ТАСИС:
        # наименование, аттестат, № протокола, акт приёмки проб, шифр пробы)
        lab_rows = [("Испытательная лаборатория (центр)",
                     "__________________________________________"),
                    ("Уникальный номер записи об аккредитации (аттестат)",
                     "№ ________________________"),
                    ("Протокол исследований (измерений)",
                     "№ __________ от «____» ________________ 20____ г."),
                    ("Акт приёмки проб", "№ __________ от «____» ________________ 20____ г."),
                    ("Регистрационный номер (шифр) пробы", "__________"),
                    ("Даты выполнения исследований (начало — окончание)",
                     "«____» ____________ 20____ г. — «____» ____________ 20____ г.")]
        tl = doc.add_table(rows=len(lab_rows), cols=2)
        tl.style = "Table Grid"
        _fix_widths(tl, (Cm(7.5), Cm(10)))
        for i, (k, v) in enumerate(lab_rows):
            _set(tl.cell(i, 0), k, AL.LEFT)
            _set(tl.cell(i, 1), v, AL.LEFT)
        doc.add_paragraph()
        # шапка организации (как «Сведения о заказчике» в акте приёмки проб)
        for text, bold in ((org.name or "—", True),
                           (" ".join(x for x in (
                               f"ИНН {org.inn}" if org.inn else "",
                               f"ОГРН {org.ogrn}" if org.ogrn else "") if x), False),
                           (org.address or "", False)):
            if text:
                par = doc.add_paragraph()
                par.alignment = AL.CENTER
                par.add_run(text).bold = bold
        doc.add_paragraph()
        h = doc.add_paragraph()
        h.alignment = AL.CENTER
        h.add_run(TITLE).bold = True
        h2 = doc.add_paragraph()
        h2.alignment = AL.CENTER
        h2.add_run(SUBTITLE)
        doc.add_paragraph()

        agg = (str(p.get("aggregate_state") or "").strip()
               or str(p.get(_AGG) or "").strip() or aggregate_state(code)
               or "—")
        origin = (str(p.get("origin") or "").strip()
                  or R.origin_for(code, name)
                  or "использование по назначению с утратой потребительских свойств")
        method = METHOD_MORPH if _is_morph(comps) else METHOD_CHEM
        rows = [("Объект исследований", "Отходы"),
                ("Сведения о заказчике (наименование, адрес, ИНН, ОГРН)",
                 " ".join(x for x in (
                     org.name, f"({org.address})" if org.address else "",
                     f"ИНН {org.inn}" if org.inn else "",
                     f"ОГРН {org.ogrn}" if org.ogrn else "") if x)),
                ("Место отбора проб (место образования отходов), фактический адрес",
                 " ".join(x for x in (
                     f"{obj.name} ({obj.code})" if obj is not None and obj.name else
                     (obj.code if obj is not None else ""),
                     site_address or org.address) if x) or "—"),
                ("Цель определения состава", PURPOSE),
                ("Наименование вида отхода по ФККО", name or "—"),
                ("Код вида отхода по ФККО", _fkko.fmt(code)),
                ("Класс опасности", _fkko.roman(hazard) or "—"),
                ("Агрегатное состояние и физическая форма", agg),
                ("Происхождение (технологический процесс)", origin),
                ("Метод определения состава", method)]
        t = doc.add_table(rows=len(rows), cols=2)
        t.style = "Table Grid"
        _fix_widths(t, (Cm(7.5), Cm(10)))
        for i, (k, v) in enumerate(rows):
            _set(t.cell(i, 0), k, AL.LEFT)
            _set(t.cell(i, 1), v, AL.LEFT)
        doc.add_paragraph()

        # результаты: компоненты в порядке убывания, итого 100,00
        cap = doc.add_paragraph()
        cap.add_run("Результаты определения состава").bold = True
        t2 = doc.add_table(rows=len(comps) + 2, cols=3)
        t2.style = "Table Grid"
        _fix_widths(t2, (Cm(1.5), Cm(11), Cm(5)))
        for j, head in enumerate(("№", "Наименование определяемого показателя "
                                       "(компонента)", "Содержание, % масс.")):
            _set(t2.cell(0, j), head, AL.CENTER)
        for i, c in enumerate(comps, 1):
            _set(t2.cell(i, 0), str(i), AL.CENTER)
            _set(t2.cell(i, 1), str(c.get("name", "")), AL.LEFT)
            _set(t2.cell(i, 2), R.fmt_pct(c.get("percent", "")), AL.CENTER)
        last = len(comps) + 1
        _set(t2.cell(last, 1), "Итого", AL.RIGHT)
        _set(t2.cell(last, 2), R.fmt_pct(R.components_total(comps)), AL.CENTER)
        ctl = doc.add_paragraph()
        ctl.add_run("Контроль: сумма состава 100 % — сходится"
                    + (f" ({item['note']})" if item["note"] else ""))
        doc.add_paragraph()

        src = _source_lines(ctx, code, p, site_dir)
        doc.add_paragraph("Источник данных: " + ("; ".join(src) if src
                                                  else "проектная документация "
                                                       "(ООС/ПНООЛР)"))
        doc.add_paragraph("Назначение: заявленный состав для отбора проб, "
                          "протокола определения состава (КХА/морфология) и "
                          "паспорта отхода.")
        note = doc.add_paragraph()
        note.add_run("Примечание. ").bold = True
        note.add_run(NOTE_LAB)
        doc.add_paragraph()
        doc.add_paragraph("Ответственный за обращение с отходами "
                          "_______________ /_________________/")
        doc.add_paragraph("Сотрудник лаборатории, ответственный за оформление "
                          "протокола _______________ /_________________/")
        doc.add_paragraph("Дата составления «____» ________________ 20____ г.")
        path = out_dir / f"Состав_{code}.docx"
        doc.save(path)
        paths.append(path)
    return paths


def gaps(ctx: ReportContext) -> list[str]:
    """Отходы I–IV класса без компонентного состава и отходы, чей состав не
    сходится (сумма > 105 %)."""
    out: list[str] = []
    for item in prepared(ctx):
        code, name, hazard = item["code"], item["name"], item["hazard"]
        label = f"{_fkko.fmt(code)} {name or ''}".strip()
        if item["note"] and "не сходится" in item["note"]:
            out.append(f"{label}: {item['note']}")
        elif 1 <= hazard <= 4 and not item["components"]:
            out.append(f"{label}: нет состава — нужен ООС/ПНООЛР или протокол КХА")
    return out
