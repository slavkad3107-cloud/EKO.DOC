"""Паспорт отходов I–IV классов опасности (Приказ Минприроды России
от 08.12.2020 № 1026, приложение — типовая форма).

Форма воспроизведена по принятым паспортам ООО «ТЕХНОСТРОЙ» (пакет для ГАСН,
2025): лист 1 — гриф «УТВЕРЖДАЮ» + таблица «Сведения об отходах», лист 2 —
таблица «Сведения о лице, которое образовало отходы».

Данные берутся из ReportContext:
  * ctx.wastes — перечень отходов (код ФККО, наименование, класс опасности);
  * ctx.extra['waste_details'][<код>] — состав и реквизиты отхода (ручной ввод);
  * ctx.extra['waste_passports'] — то же, но из ИИ-разбора приложенных паспортов
    и протоколов КХА (fallback, если waste_details не заполнен).

Паспорт оформляется только на отходы I–IV класса: для V класса он не нужен —
требуется подтверждение отнесения к V классу (протокол биотестирования).
"""
from __future__ import annotations

from pathlib import Path

from ecodoc.core.models import Organization, ReportContext, WasteFlow

_AGG = "агрегатное состояние и физическая форма"
_TITLE = "ПАСПОРТ ОТХОДОВ I - IV КЛАССОВ ОПАСНОСТИ,"
_SUBTITLE = "включенных в Федеральный классификационный каталог отходов"

_L_ORIGIN = ("Происхождение отходов (указывается наименование технологического "
             "процесса, в результате которого образовался отход, или процесса, "
             "в результате которого товар (продукция) утратил свои "
             "потребительские свойства, с указанием наименования исходного "
             "товара)")
_L_COMP = ("Химический и (или) компонентный состав (указывается в порядке "
           "убывания содержания компонентов)")
_L_METHOD = ("Способ определения химического и (или) компонентного состава "
             "вида отходов (указывается согласно документации и (или) с "
             "использованием количественного химического анализа)")
_L_HAZARD = ("Класс опасности по степени негативного воздействия на "
             "окружающую среду")
_L_PERSON = ("Фамилия, имя, отчество (при наличии) индивидуального "
             "предпринимателя или полное наименование юридического лица")

_DEFAULT_METHOD = "количественный химический анализ отхода"


def _details(ctx: ReportContext, w: WasteFlow) -> dict:
    """Сведения об отходе: ручной ввод главнее, ИИ-разбор — как запасной."""
    from ecodoc.core.waste_agg import norm_fkko

    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    d = dict((extra.get("waste_details") or {}).get(w.fkko_code) or {})
    if not d.get("components"):
        code = norm_fkko(w.fkko_code or "")
        for p in extra.get("waste_passports") or []:
            if code and norm_fkko(str(p.get("fkko") or "")) == code:
                d.setdefault("components", p.get("components") or [])
                break
    return d


def generate(ctx: ReportContext, out_dir: str | Path) -> list[Path]:
    """Сгенерировать по одному .docx-паспорту на каждый отход I–IV класса."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    for w in ctx.wastes:
        try:
            hazard = int(w.hazard_class)
        except (TypeError, ValueError):
            continue
        if not 1 <= hazard <= 4:
            continue  # паспорт нужен только для I–IV класса
        path = out_dir / f"Паспорт_{(w.fkko_code or 'без кода').replace(' ', '')}.docx"
        _build(ctx.organization, w, hazard, _details(ctx, w)).save(path)
        paths.append(path)
    return paths


def _build(org: Organization, w: WasteFlow, hazard: int, d: dict):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.enum.text import WD_BREAK
    from docx.shared import Cm, Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    # интервал после абзаца по умолчанию раздвигает шапку так, что таблица
    # «Сведения об отходах» перестаёт помещаться на лист — гасим его
    style.paragraph_format.space_after = Pt(0)
    for s in doc.sections:
        s.left_margin, s.right_margin = Cm(2), Cm(1.5)
        s.top_margin, s.bottom_margin = Cm(1.2), Cm(1.2)

    _approval_block(doc, org, AL, Cm, Pt)

    for text, size in ((_TITLE, 13), (_SUBTITLE, 12)):
        p = doc.add_paragraph()
        p.alignment = AL.CENTER
        p.paragraph_format.space_after = Pt(0)
        p.add_run(text).font.size = Pt(size)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)

    comps = _sorted_components(d.get("components") or [])
    method = d.get("method") or _DEFAULT_METHOD
    basis = d.get("basis") or ""
    if basis and basis not in method:
        method = f"{method} ({basis})"

    rows = [
        ("Наименование вида отходов по ФККО", w.name or "—"),
        ("Код вида отходов по ФККО", w.fkko_code or "—"),
        (_L_ORIGIN, d.get("origin") or "‹указать технологический процесс›"),
        ("__COMP__", comps),
        (_L_METHOD, method),
        ("Агрегатное состояние и физическая форма",
         d.get(_AGG) or "‹указать по ФККО›"),
        (_L_HAZARD, _roman(hazard)),
    ]
    _info_table(doc, "Сведения об отходах", rows, AL, Cm)

    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    _person_table(doc, org, d, AL, Cm)
    return doc


def _approval_block(doc, org: Organization, AL, Cm, Pt):
    """Гриф «УТВЕРЖДАЮ» в правом верхнем углу листа."""
    for text in ("УТВЕРЖДАЮ", org.official_title,
                 org.short_name or org.name):
        p = doc.add_paragraph()
        p.alignment = AL.RIGHT
        p.paragraph_format.space_after = Pt(0)
        p.add_run(text).bold = True

    doc.add_paragraph()  # место для подписи и печати

    t = doc.add_table(rows=2, cols=2)
    t.alignment = 2  # WD_TABLE_ALIGNMENT.RIGHT
    _fix_widths(t, (Cm(5.5), Cm(5.5)))
    for row, (left, right, bold) in enumerate((
            ("", org.director_name or "", True),
            ("(подпись)", "(расшифровка)", False))):
        for col, text in enumerate((left, right)):
            cell = t.cell(row, col)
            p = cell.paragraphs[0]
            p.alignment = AL.CENTER
            p.paragraph_format.space_after = Pt(0)
            p.add_run(text).bold = bold
            if row == 0:
                _bottom_border(cell)

    for text, bold in (("«____» ________________ 20____ г.", True),
                       ("М.П.", False), ("(при наличии)", False)):
        p = doc.add_paragraph()
        p.alignment = AL.RIGHT
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(text)
        run.bold = bold
        if not bold:
            run.font.size = Pt(10)
    doc.add_paragraph()


def _info_table(doc, caption: str, rows, AL, Cm):
    """Таблица «Сведения об отходах» (3 колонки: строка состава вложенная)."""
    # строк: обычные — по одной; состав — заголовок + компоненты, причём при
    # ПУСТОМ составе ниже подставляется строка-плейсхолдер (max(1, ...)),
    # иначе таблица окажется на строку короче и падает IndexError
    n = sum(1 + max(1, len(v)) if k == "__COMP__" else 1 for k, v in rows) + 1
    t = doc.add_table(rows=n, cols=3)
    t.style = "Table Grid"
    _fix_widths(t, (Cm(9.3), Cm(4.7), Cm(3.5)))

    head = t.rows[0]
    head.cells[0].merge(head.cells[2]).paragraphs[0].alignment = AL.CENTER
    head.cells[0].paragraphs[0].add_run(caption)

    i = 1
    for label, value in rows:
        if label == "__COMP__":
            first = i
            _set(t.cell(i, 0), _L_COMP, AL.JUSTIFY)
            _set(t.cell(i, 1), "Наименование компонента", AL.CENTER)
            _set(t.cell(i, 2), "Содержание, %", AL.CENTER)
            i += 1
            if not value:
                value = [{"name": "‹состав из протокола КХА›", "percent": ""}]
            for c in value:
                _set(t.cell(i, 1), str(c.get("name", "")), AL.LEFT)
                _set(t.cell(i, 2), _fmt_pct(c.get("percent", "")), AL.CENTER)
                i += 1
            t.cell(first, 0).merge(t.cell(i - 1, 0))
        else:
            _set(t.cell(i, 0), label, AL.JUSTIFY)
            cell = t.cell(i, 1).merge(t.cell(i, 2))
            _set(cell, str(value), AL.LEFT)
            i += 1
    return t


def _person_table(doc, org: Organization, d: dict, AL, Cm):
    rows = [
        (_L_PERSON, org.name),
        ("Сокращенное наименование юридического лица", org.short_name),
        ("Индивидуальный номер налогоплательщика (ИНН)", org.inn),
        ("Код по Общероссийскому классификатору предприятий и организаций "
         "(ОКПО)", org.okpo),
        ("Код по Общероссийскому классификатору видов экономической "
         "деятельности (ОКВЭД)", org.okved),
        ("Место нахождения", org.address),
        ("Почтовый адрес", d.get("postal_address") or org.address),
        ("Адрес (адреса) фактического осуществления деятельности",
         d.get("site_address") or "‹адрес площадки›"),
    ]
    if org.is_individual:
        rows.pop(1)

    t = doc.add_table(rows=len(rows) + 1, cols=2)
    t.style = "Table Grid"
    _fix_widths(t, (Cm(9.3), Cm(8.2)))
    head = t.rows[0]
    head.cells[0].merge(head.cells[1]).paragraphs[0].alignment = AL.CENTER
    head.cells[0].paragraphs[0].add_run("Сведения о лице, которое образовало отходы")

    for i, (label, value) in enumerate(rows, start=1):
        _set(t.cell(i, 0), label, AL.JUSTIFY)
        _set(t.cell(i, 1), str(value or "—"), AL.LEFT)
    return t


def _set(cell, text: str, align):
    p = cell.paragraphs[0]
    p.alignment = align
    p.add_run(text)


def _fix_widths(table, widths):
    """Жёсткая ширина колонок: без неё Word/LibreOffice «схлопывают» подписи.

    Ширину надо проставить до объединения ячеек и продублировать в разметке
    таблицы (tblLayout fixed), иначе автоподбор её игнорирует.
    """
    from docx.oxml.ns import qn

    table.autofit = False
    layout = table._tbl.tblPr.makeelement(qn("w:tblLayout"), {})
    layout.set(qn("w:type"), "fixed")
    table._tbl.tblPr.append(layout)
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = width
    for column, width in zip(table.columns, widths):
        column.width = width


def _bottom_border(cell):
    """Линия под ячейкой — для строки подписи в грифе «УТВЕРЖДАЮ»."""
    from docx.oxml.ns import qn

    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.makeelement(qn("w:tcBorders"), {})
    bottom = borders.makeelement(qn("w:bottom"), {})
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:color"), "000000")
    borders.append(bottom)
    tc_pr.append(borders)


def _sorted_components(comps: list) -> list:
    """Форма требует состав в порядке убывания содержания компонентов."""
    def key(c):
        try:
            return -float(str(c.get("percent", "")).replace(",", ".").strip())
        except (TypeError, ValueError):
            return 0.0
    return sorted([c for c in comps if isinstance(c, dict)], key=key)


def _fmt_pct(v) -> str:
    s = str(v).strip().replace(".", ",")
    return s


def _roman(hazard_class) -> str:
    return {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}.get(int(hazard_class),
                                                            str(hazard_class))
