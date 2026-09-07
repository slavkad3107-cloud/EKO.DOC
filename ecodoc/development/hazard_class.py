"""Расчёт класса опасности отхода по критериям Минприроды России.

Действующие критерии — приказ Минприроды от 31.03.2025 № 158 (в силе
с 01.09.2025, заменил приказ № 536 от 04.12.2014; шкала K не менялась).

Компонентный метод (раздел II Критериев): по каждому компоненту отхода
известен коэффициент степени опасности Wi (мг/кг), рассчитывается
K = Σ(Ci / Wi), где Ci — концентрация компонента (мг/кг). Класс — по
приложению № 1 к Критериям:
  10^6 ≥ K > 10^4 → I класс (чрезвычайно опасные)
  10^4 ≥ K > 10^3 → II класс (высокоопасные)
  10^3 ≥ K > 10^2 → III класс (умеренно опасные)
  10^2 ≥ K > 10   → IV класс (малоопасные)
  K ≤ 10          → V класс (практически неопасные)
Верхняя граница каждого диапазона включается, нижняя — нет:
K = 10^4 — это II класс, K = 10 — это V.

Wi компонентов — из справочника core/waste_refdata.WI_TABLE (п. 11 и
приложение № 4 к Критериям, БДО — с указанием источника у каждого) либо
задаётся вручную. Состав (Ci) — из протокола состава отхода / паспорта /
ООС (extra.waste_passports), в % → мг/кг (× 10 000). Биотестирование (для
подтверждения V класса) в расчёт не входит — это отдельная процедура
(раздел III Критериев).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Component:
    name: str
    ci: float          # концентрация компонента в отходе, мг/кг
    wi: float          # коэффициент степени опасности Wi, мг/кг
    percent: float | None = None   # содержание, % (если известно)
    wi_source: str = ""            # откуда взят Wi (приказ/БДО/вручную)


@dataclass
class HazardResult:
    k_total: float
    hazard_class: int
    components: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# официальное имя действующих критериев — для документов и сообщений
NPA = "приказ Минприроды России от 31.03.2025 № 158"
SCALE = ("10⁶ ≥ K > 10⁴ — I класс; 10⁴ ≥ K > 10³ — II класс; "
         "10³ ≥ K > 10² — III класс; 10² ≥ K > 10 — IV класс; K ≤ 10 — V класс")


def _class_by_k(k: float) -> int:
    # приложение № 1 к Критериям: верхняя граница включается, нижняя — нет
    if k > 1e4:
        return 1                       # 10^6 >= K > 10^4
    if k > 1e3:
        return 2                       # 10^4 >= K > 10^3
    if k > 1e2:
        return 3                       # 10^3 >= K > 10^2
    if k > 10:
        return 4                       # 10^2 >= K > 10
    return 5                           # K <= 10


def calculate(components: list[Component]) -> HazardResult:
    """K = Σ(Ci/Wi) и класс опасности по действующим Критериям (пр. № 158)."""
    res = HazardResult(k_total=0.0, hazard_class=5)
    total_ci = sum(c.ci for c in components)
    if total_ci and abs(total_ci - 1_000_000) / 1_000_000 > 0.05:
        res.warnings.append(
            f"Сумма концентраций компонентов {total_ci:.0f} мг/кг ≠ 1 000 000 "
            f"(100%) — проверьте состав отхода")
    k = 0.0
    for c in components:
        if c.wi <= 0:
            res.warnings.append(f"{c.name}: Wi ≤ 0 — компонент пропущен")
            ki = 0.0
        else:
            ki = c.ci / c.wi
            k += ki
        pct = c.percent if c.percent is not None else c.ci / 10_000.0
        res.components.append({"name": c.name, "ci": c.ci, "wi": c.wi,
                               "ki": round(ki, 4), "percent": round(pct, 4),
                               "wi_source": c.wi_source})
    res.k_total = k
    res.hazard_class = _class_by_k(k)
    return res


def binf_score(n: int) -> int:
    """Балл показателя информационного обеспечения (приложение № 3 к
    Критериям): n/12 < 0,5 (n < 6) → 1; 0,5–0,7 (n = 6–8) → 2;
    0,71–0,9 (n = 9–10) → 3; > 0,9 (n ≥ 11) → 4."""
    n = int(n)
    if n < 6:
        return 1
    if n <= 8:
        return 2
    if n <= 10:
        return 3
    return 4


def wi_from_indicators(scores: list) -> dict:
    """Wi по первичным показателям опасности компонента (пп. 7–10 Критериев,
    приложения № 2–3): scores — баллы Bj (1..4) по оценённым показателям.
      Xi = (ΣBj + Binf) / (n + 1);   Zi = 4·Xi/3 − 1/3;
      lg Wi = 4 − 4/Zi (1 < Zi < 2);  lg Wi = Zi (2 ≤ Zi ≤ 4);
      lg Wi = 2 + 4/(6 − Zi) (4 < Zi < 5).
    Возвращает {n, binf, xi, zi, lg_wi, wi}; пустой список — ValueError."""
    b = []
    for s in scores or []:
        try:
            v = int(round(float(str(s).replace(",", "."))))
        except (TypeError, ValueError):
            continue
        if 1 <= v <= 4:
            b.append(v)
    if not b:
        raise ValueError("нет баллов первичных показателей (Bj = 1..4)")
    n = len(b)
    binf = binf_score(n)
    xi = (sum(b) + binf) / (n + 1)
    zi = 4 * xi / 3 - 1 / 3
    if zi <= 1:
        lg = 0.0
    elif zi < 2:
        lg = 4 - 4 / zi
    elif zi <= 4:
        lg = zi
    elif zi < 5:
        lg = 2 + 4 / (6 - zi)
    else:
        lg = 6.0
    return {"n": n, "binf": binf, "xi": round(xi, 4), "zi": round(zi, 4),
            "lg_wi": round(lg, 4), "wi": round(math.pow(10, lg), 2)}


def wi_from_logk(log_k: float) -> float:
    """Wi из унифицированного показателя lg(Wi) (приложения к Критериям):
    Wi = 10^(lg Wi). Хелпер, если известен lg Wi компонента."""
    return math.pow(10, log_k)


# ─────────────────────── состав → компоненты с Wi ───────────────────────

def components_from_percent(comps: list[dict],
                            wi_overrides: dict | None = None
                            ) -> tuple[list[Component], list[str]]:
    """Нормализованный состав ({name, percent}) → компоненты расчёта:
    Ci = % × 10 000 мг/кг, Wi — из справочника waste_refdata (или из
    wi_overrides {имя: Wi} / поля wi компонента). Возвращает (компоненты,
    имена без Wi): компонент без Wi в K не входит, но остаётся в таблице
    с пометкой."""
    from ecodoc.core import waste_refdata as R

    over = {R._key(k): float(v) for k, v in (wi_overrides or {}).items()
            if v not in (None, "", 0)}
    out: list[Component] = []
    missing: list[str] = []
    for c in comps or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        pct = R.parse_value(c.get("percent", c.get("value")))
        if not name or pct is None:
            continue
        wi = None
        src = ""
        manual = R.parse_value(c.get("wi"))
        if manual:
            wi, src = manual, "задано вручную"
        elif R._key(name) in over:
            wi, src = over[R._key(name)], "задано вручную"
        elif c.get("scores") or c.get("indicators"):
            # первичные показатели опасности введены — Wi по формуле пп. 7–10
            try:
                calc = wi_from_indicators(c.get("scores") or c.get("indicators"))
                wi = calc["wi"]
                src = (f"расчёт по первичным показателям (n = {calc['n']}, "
                       f"Binf = {calc['binf']}, Xi = {calc['xi']}, "
                       f"Zi = {calc['zi']}, lg Wi = {calc['lg_wi']})")
            except ValueError:
                wi = None
        if wi is None:
            wi, src, canon = R.wi_for(name)
            if wi is not None and canon and canon.lower() != name.lower():
                src = f"{src} [по справочнику: {canon}]"
        if wi is None:
            missing.append(name)
            wi, src = 0.0, "Wi не определён — взять из БДО"
        out.append(Component(name=name, ci=pct * 10_000.0, wi=wi,
                             percent=pct, wi_source=src))
    return out, missing


def for_waste(ctx, selector) -> dict:
    """Состав отхода из базы для расчёта одной кнопкой: selector — код ФККО
    (в любом написании) или индекс в extra.waste_passports. Берётся то же,
    что печатает паспорт (waste_passport._details: ручной ввод → протокол
    состава → справочник паспортов/ООС), состав приведён к 100 %.
    Возвращает {name, fkko, hazard_class, components, source, protocol}
    либо {'error': …}."""
    from ecodoc.core.models import WasteFlow
    from ecodoc.core.waste_agg import norm_fkko
    from ecodoc.development import waste_passport as wp

    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    passports = [p for p in extra.get("waste_passports") or [] if isinstance(p, dict)]
    import re as _re

    code, rec = "", {}
    sel = str(selector).strip() if selector is not None else ""
    if isinstance(selector, int) or (sel.isdigit() and len(sel) < 11):
        idx = int(selector)
        if not 0 <= idx < len(passports):
            return {"error": f"нет паспорта с индексом {idx}"}
        rec = passports[idx]
        code = norm_fkko(rec.get("fkko"))
    elif _re.search(r"[а-яёa-z]", sel, _re.I):
        # по наименованию (паспорт без кода ФККО или выбор по имени)
        low = sel.lower()
        rec = next((p for p in passports
                    if str(p.get("name") or "").strip().lower() == low), {})
        if not rec:
            rec = next((p for p in passports if low[:40] in
                        str(p.get("name") or "").strip().lower()), {})
        if not rec:
            return {"error": f"паспорт «{sel[:60]}» не найден в справочнике "
                             f"паспортов"}
        code = norm_fkko(rec.get("fkko"))
    else:
        code = norm_fkko(sel)
        if not code:
            return {"error": "не указан код ФККО отхода"}
        rec = next((p for p in passports if norm_fkko(p.get("fkko")) == code), {})
    w = next((x for x in ctx.wastes if code and norm_fkko(x.fkko_code) == code),
             None)
    if w is None:
        if not rec:
            return {"error": f"отход {selector} не найден ни в перечне отходов, "
                             f"ни в справочнике паспортов"}
        try:
            hz = int(rec.get("hazard_class") or 0)
        except (TypeError, ValueError):
            hz = 0
        w = WasteFlow(fkko_code=code, name=str(rec.get("name") or ""),
                      hazard_class=hz)
    d = wp._details(ctx, w)
    comps = d.get("components") or []
    if not comps:
        return {"error": f"у отхода {w.fkko_code} {w.name} нет состава — нужен "
                         f"протокол состава или ООС/ПНООЛР",
                "gaps": d.get("_gaps") or []}
    proto = d.get("protocol") if isinstance(d.get("protocol"), dict) else {}
    src = {"manual": "ручной ввод состава", "protocol": "протокол состава отхода",
           "passport": "паспорт отхода (загруженный)",
           "oos": "проектная документация (ООС/ПНООЛР)"}.get(
        str(d.get("_comp_kind") or ""), "справочник паспортов")
    return {"name": w.name, "fkko": w.fkko_code, "hazard_class": w.hazard_class,
            "components": comps, "source": src, "protocol": proto,
            "note": d.get("_comp_note") or ""}


# ────────────────────────────── документ ──────────────────────────────

def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    if abs(v) >= 1000:
        return f"{v:,.0f}".replace(",", " ")
    if abs(v) >= 1:
        return f"{v:.4g}".replace(".", ",")
    return f"{v:.3g}".replace(".", ",")


def generate(components: list[Component], out_path,
             waste_name: str = "", fkko: str = "", org_name: str = "",
             basis: str = "", org_inn: str = "", protocol: dict | None = None,
             missing_wi: list[str] | None = None,
             declared_class=None) -> Path:
    """Оформить расчёт документом (.docx) — прикладывается к паспорту отхода
    и к материалам отнесения отхода к классу опасности.

    Структура: титул (организация, отход, ФККО) → метод и формулы →
    исходные данные (таблица: компонент, C %, Ci мг/кг, Wi и его источник,
    Ki) → K = ΣKi → шкала классов → вывод (для V класса — о биотестировании)
    → протокол-основание состава → подпись. basis — откуда взят состав."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.shared import Cm, Pt

    from ecodoc.core import fkko as _fkko

    r = calculate(components)
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    style.paragraph_format.space_after = Pt(0)
    for s in doc.sections:
        s.left_margin, s.right_margin = Cm(2.5), Cm(1.5)
        s.top_margin, s.bottom_margin = Cm(2), Cm(2)

    # ── титул ──
    for text, bold in ((org_name, True), (f"ИНН {org_inn}" if org_inn else "", False)):
        if text:
            head = doc.add_paragraph()
            head.alignment = AL.CENTER
            head.add_run(text).bold = bold
    doc.add_paragraph()
    title = doc.add_paragraph()
    title.alignment = AL.CENTER
    run = title.add_run("РАСЧЁТ КЛАССА ОПАСНОСТИ ОТХОДА")
    run.bold = True
    run.font.size = Pt(14)
    sub = doc.add_paragraph()
    sub.alignment = AL.CENTER
    sub.add_run("по степени негативного воздействия на окружающую среду "
                f"(Критерии, утв. {NPA})")
    doc.add_paragraph()
    code_fmt = _fkko.fmt(fkko) if fkko else ""
    t0 = doc.add_table(rows=2, cols=2)
    t0.style = "Table Grid"
    for i, (k, v) in enumerate((("Наименование вида отхода", waste_name or "—"),
                                ("Код по ФККО", code_fmt or "—"))):
        t0.cell(i, 0).text, t0.cell(i, 1).text = k, v
    doc.add_paragraph()

    # ── метод ──
    p = doc.add_paragraph()
    p.add_run("1. Метод расчёта. ").bold = True
    p.add_run("Класс опасности определяется расчётным методом по показателю "
              "степени опасности отхода K, равному сумме показателей степени "
              "опасности компонентов (п. 4–5 Критериев): K = Σ Ki, Ki = Ci / Wi, "
              "где Ci — концентрация i-го компонента в отходе (мг/кг), Wi — "
              "коэффициент степени опасности i-го компонента для окружающей "
              "среды (мг/кг). Содержание компонентов в % переведено в мг/кг "
              "(1 % = 10 000 мг/кг).")
    p = doc.add_paragraph()
    p.add_run("2. Исходные данные. ").bold = True
    p.add_run(basis or "Компонентный состав отхода — по протоколу определения "
                       "состава (КХА / морфологический анализ); Wi — по п. 11 "
                       "и приложению № 4 к Критериям, по данным БДО "
                       "Росприроднадзора (источник указан у каждого "
                       "компонента).")
    if protocol and any(protocol.values()):
        line = " ".join(x for x in (
            "Протокол определения состава:",
            f"№ {protocol.get('number')}" if protocol.get("number") else "",
            f"от {protocol.get('date')}" if protocol.get("date") else "",
            f"— {protocol.get('lab')}" if protocol.get("lab") else "",
            f"(аттестат {protocol.get('lab_attestation')})"
            if protocol.get("lab_attestation") else "",
            f", МИ {protocol.get('method_doc')}" if protocol.get("method_doc") else "",
        ) if x)
        doc.add_paragraph(line)
    doc.add_paragraph()

    # ── таблица ──
    heads = ["№", "Компонент отхода", "Содержание C, %", "Ci, мг/кг",
             "Wi, мг/кг", "Источник Wi", "Ki = Ci/Wi"]
    table = doc.add_table(rows=1, cols=len(heads))
    table.style = "Table Grid"
    for i, text in enumerate(heads):
        cell = table.rows[0].cells[i]
        cell.text = text
        cell.paragraphs[0].alignment = AL.CENTER
    for i, c in enumerate(r.components, start=1):
        cells = table.add_row().cells
        cells[0].text = str(i)
        cells[1].text = c["name"]
        cells[2].text = f"{c['percent']:.2f}".replace(".", ",")
        cells[3].text = _fmt(c["ci"])
        cells[4].text = _fmt(c["wi"]) if c["wi"] > 0 else "—"
        cells[5].text = c.get("wi_source") or "—"
        cells[6].text = _fmt(c["ki"]) if c["wi"] > 0 else "—"
        for j in (0, 2, 3, 4, 6):
            cells[j].paragraphs[0].alignment = AL.CENTER
    cells = table.add_row().cells
    cells[1].text = "Итого"
    total_pct = sum(c["percent"] for c in r.components)
    cells[2].text = f"{total_pct:.2f}".replace(".", ",")
    cells[3].text = _fmt(sum(c["ci"] for c in r.components))
    cells[6].text = f"K = {r.k_total:.4g}".replace(".", ",")
    for j in (2, 3, 6):
        cells[j].paragraphs[0].alignment = AL.CENTER
    for row in table.rows:
        for cell in row.cells:
            for par in cell.paragraphs:
                for rn in par.runs:
                    rn.font.size = Pt(10)
    doc.add_paragraph()

    # ── результат ──
    p = doc.add_paragraph()
    p.add_run("3. Показатель степени опасности отхода. ").bold = True
    p.add_run(f"K = Σ(Ci / Wi) = {r.k_total:.4g}".replace(".", ","))
    p = doc.add_paragraph()
    p.add_run("4. Отнесение к классу опасности ").bold = True
    p.add_run(f"(приложение № 1 к Критериям): {SCALE}.")
    concl = doc.add_paragraph()
    concl.add_run(f"ВЫВОД: показатель K = {r.k_total:.4g}".replace(".", ",")
                  + f" — отход относится к {_fkko.roman(r.hazard_class)} "
                    f"({r.hazard_class}) классу опасности по степени негативного "
                    f"воздействия на окружающую среду.").bold = True
    if declared_class not in (None, "", 0):
        try:
            dc = int(declared_class)
        except (TypeError, ValueError):
            dc = 0
        if dc and dc != r.hazard_class:
            doc.add_paragraph(
                f"⚠ Класс опасности по ФККО/паспорту — {_fkko.roman(dc)}: "
                f"расчёт даёт {_fkko.roman(r.hazard_class)}. Проверьте состав "
                f"(Ci) и значения Wi; при расхождении с ФККО действует класс "
                f"по ФККО.")
    if r.hazard_class == 5:
        doc.add_paragraph(
            "Примечание: отнесение отхода к V классу опасности подлежит "
            "подтверждению биотестированием водной вытяжки из отхода "
            "(раздел III Критериев — кратность разведения, при которой "
            "вредное воздействие на гидробионты отсутствует; для V класса "
            "используется сама водная вытяжка без разведения, приложение № 5).")
    for m in missing_wi or []:
        doc.add_paragraph(f"⚠ {m}: коэффициент Wi в справочнике отсутствует — "
                          f"компонент в K не учтён; значение Wi взять из БДО "
                          f"Росприроднадзора или рассчитать по первичным "
                          f"показателям (приложения № 2–3 к Критериям).")
    for w in r.warnings:
        doc.add_paragraph(f"⚠ {w}")

    doc.add_paragraph()
    doc.add_paragraph("Расчёт выполнил: ____________________ "
                      "/______________________/    «____» ____________ 20____ г.")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def report(components: list[Component]) -> str:
    r = calculate(components)
    lines = [f"── Расчёт класса опасности отхода ({NPA}) ──"]
    for c in r.components:
        lines.append(f"  {c['name']}: Ci={c['ci']} мг/кг, Wi={c['wi']} → "
                     f"Ki={c['ki']}")
    lines.append(f"K = Σ(Ci/Wi) = {r.k_total:.4g}")
    lines.append(f"КЛАСС ОПАСНОСТИ: {r.hazard_class}")
    if r.hazard_class == 5:
        lines.append("⚠ V класс требует подтверждения биотестированием.")
    for w in r.warnings:
        lines.append(f"  ⚠ {w}")
    return "\n".join(lines)
