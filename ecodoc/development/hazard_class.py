"""Расчёт класса опасности отхода по Приказу МПР № 536 от 04.12.2014.

Компонентный метод: по каждому компоненту отхода известен показатель
степени опасности Wi (мг/кг), рассчитывается K = Σ(Ci / Wi), где Ci —
концентрация компонента (мг/кг). По суммарному K определяется класс:
  K ≥ 10^6      → I класс (чрезвычайно опасные)
  10^4 ≤ K <10^6 → II класс (высокоопасные)
  10^3 ≤ K <10^4 → III класс (умеренно опасные)
  10^2 ≤ K <10^3 → IV класс (малоопасные)
  K < 10^2      → V класс (практически неопасные)

Wi компонентов берётся из аттестованных источников/протоколов; здесь —
машина расчёта K и класса по заданным (Ci, Wi). Биотестирование (для
подтверждения V класса) в расчёт не входит — это отдельная процедура.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Component:
    name: str
    ci: float          # концентрация компонента в отходе, мг/кг
    wi: float          # коэффициент степени опасности Wi, мг/кг


@dataclass
class HazardResult:
    k_total: float
    hazard_class: int
    components: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _class_by_k(k: float) -> int:
    if k >= 1e6:
        return 1
    if k >= 1e4:
        return 2
    if k >= 1e3:
        return 3
    if k >= 1e2:
        return 4
    return 5


def calculate(components: list[Component]) -> HazardResult:
    """K = Σ(Ci/Wi) и класс опасности по Приказу № 536."""
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
        res.components.append({"name": c.name, "ci": c.ci, "wi": c.wi,
                               "ki": round(ki, 4)})
    res.k_total = k
    res.hazard_class = _class_by_k(k)
    return res


def wi_from_logk(log_k: float) -> float:
    """Wi из унифицированного показателя lg(Wi) (Приказ № 536, прил.):
    Wi = 10^(lg Wi). Хелпер, если известен lg Wi компонента."""
    return math.pow(10, log_k)


def generate(components: list[Component], out_path,
             waste_name: str = "", fkko: str = "", org_name: str = "",
             basis: str = "") -> "Path":
    """Оформить расчёт документом (.docx): по Приказу № 536 такой расчёт
    прикладывается к паспорту отхода и к материалам отнесения к классу.

    Машина считает K и класс; откуда взяты Ci (протоколы КХА) и Wi
    (приложения к приказу / БДО) — пишет пользователь в поле basis."""
    from pathlib import Path

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.shared import Cm, Pt

    r = calculate(components)
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    for s in doc.sections:
        s.left_margin, s.right_margin = Cm(3), Cm(1.5)
        s.top_margin, s.bottom_margin = Cm(2), Cm(2)

    if org_name:
        head = doc.add_paragraph()
        head.alignment = AL.CENTER
        head.add_run(org_name).bold = True
    title = doc.add_paragraph()
    title.alignment = AL.CENTER
    run = title.add_run(
        "РАСЧЁТ класса опасности отхода\n"
        "(критерии — приказ Минприроды России от 04.12.2014 № 536)")
    run.bold = True
    run.font.size = Pt(14)

    doc.add_paragraph(f"Отход: {waste_name or '[наименование отхода]'}"
                      + (f", код ФККО {fkko}" if fkko else ""))
    doc.add_paragraph(
        "Метод: компонентный. Показатель степени опасности отхода "
        "K = Σ(Ci / Wi), где Ci — концентрация i-го компонента (мг/кг), "
        "Wi — коэффициент степени опасности компонента (мг/кг).")
    if basis:
        doc.add_paragraph(f"Исходные данные: {basis}")

    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for i, text in enumerate(["№", "Компонент", "Ci, мг/кг", "Wi, мг/кг",
                              "Ki = Ci/Wi"]):
        table.rows[0].cells[i].text = text
    for i, c in enumerate(r.components, start=1):
        cells = table.add_row().cells
        cells[0].text = str(i)
        cells[1].text = c["name"]
        cells[2].text = f"{c['ci']:g}"
        cells[3].text = f"{c['wi']:g}"
        cells[4].text = f"{c['ki']:g}"

    doc.add_paragraph()
    doc.add_paragraph(f"K = Σ(Ci/Wi) = {r.k_total:.4g}")
    bands = ("K ≥ 10⁶ — I класс; 10⁴ ≤ K < 10⁶ — II; 10³ ≤ K < 10⁴ — III; "
             "10² ≤ K < 10³ — IV; K < 10² — V")
    doc.add_paragraph(f"Границы классов: {bands}.")
    concl = doc.add_paragraph()
    concl.add_run(f"ВЫВОД: отход относится к {r.hazard_class} классу "
                  f"опасности.").bold = True
    if r.hazard_class == 5:
        doc.add_paragraph(
            "Примечание: отнесение к V классу подлежит подтверждению "
            "биотестированием водной вытяжки на двух тест-объектах из разных "
            "систематических групп (приказ № 536, п. 6).")
    for w in r.warnings:
        doc.add_paragraph(f"⚠ {w}")

    doc.add_paragraph()
    doc.add_paragraph("Расчёт выполнил: ____________________ "
                      "/______________________/")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def report(components: list[Component]) -> str:
    r = calculate(components)
    lines = ["── Расчёт класса опасности отхода (Приказ МПР № 536) ──"]
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
