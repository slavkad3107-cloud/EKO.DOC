"""Раздел ООС — «Перечень мероприятий по охране окружающей среды».

Состав раздела задан постановлением Правительства РФ от 16.02.2008 № 87
(п. 25 — для объектов производственного и непроизводственного назначения).
Это подраздел проектной документации, и ЭкоДок делает то, что можно сделать
машиной:

  * титул, содержание, сведения о заказчике и объекте — из карточки объекта;
  * таблицы выбросов, отходов и сбросов — из уже собранных данных;
  * перечень мероприятий — типовые формулировки по каждому пункту п. 25,
    включаемые только для тех сред, по которым воздействие есть;
  * расчёт затрат и платы — из расчёта платы за НВОС.

Чего машина не делает и чего не выдумывает: расчёт рассеивания (УПРЗА),
акустика, изыскания. Там, где нужны их результаты, в документе остаётся
явная пометка «[требуется: …]», и та же строка попадает в gaps() — чтобы
пользователь видел список до генерации, а не искал пометки в тексте.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import Medium, ReportContext

TITLE = ("Перечень мероприятий по охране окружающей среды "
         "(раздел 8 проектной документации, ПП РФ № 87, п. 25)")

# Пункты п. 25 ПП 87: ключ → (заголовок, для какой среды обязателен)
# medium = "" — пункт включается всегда.
SECTIONS: list[tuple[str, str, str]] = [
    ("assessment", "Результаты оценки воздействия объекта капитального "
                   "строительства на окружающую среду", ""),
    ("air", "Мероприятия по охране атмосферного воздуха", "air"),
    ("water", "Мероприятия по охране поверхностных и подземных вод, "
              "решения по очистке сточных вод", "water"),
    ("soil", "Мероприятия по охране и рациональному использованию земельных "
             "ресурсов и почвенного покрова, рекультивация", ""),
    ("waste", "Мероприятия по обращению с отходами производства и потребления",
     "waste"),
    ("subsoil", "Мероприятия по охране недр", ""),
    ("bio", "Мероприятия по охране объектов растительного и животного мира "
            "и среды их обитания", ""),
    ("accidents", "Мероприятия по минимизации возникновения аварийных ситуаций "
                  "и последствий их воздействия на экосистему", ""),
    ("pek", "Программа производственного экологического контроля (мониторинга)",
     ""),
    ("costs", "Перечень и расчёт затрат на реализацию природоохранных "
              "мероприятий и компенсационных выплат", ""),
]

# типовые мероприятия по каждому пункту — то, что пишется в любом разделе ООС
MEASURES: dict[str, list[str]] = {
    "air": [
        "оснащение источников выбросов пылегазоочистным оборудованием с "
        "проектной эффективностью очистки и контроль его работы",
        "соблюдение технологического регламента работы оборудования, "
        "исключающее залповые и аварийные выбросы",
        "разработка и выполнение мероприятий по уменьшению выбросов в периоды "
        "неблагоприятных метеорологических условий (приказ Минприроды № 811)",
        "контроль содержания загрязняющих веществ в выбросах в рамках "
        "программы ПЭК",
    ],
    "water": [
        "отведение хозяйственно-бытовых сточных вод в централизованную систему "
        "водоотведения по договору с водоканалом",
        "оборудование площадок с твёрдым покрытием и организованным сбором "
        "поверхностного стока, очистка стока перед сбросом",
        "исключение сброса неочищенных сточных вод на рельеф и в водные "
        "объекты, обвалование мест хранения нефтепродуктов",
        "контроль качества сточных вод в контрольных точках в рамках ПЭК",
    ],
    "soil": [
        "выполнение работ в границах отведённого земельного участка, "
        "недопущение захламления прилегающих территорий",
        "снятие, складирование и сохранение плодородного слоя почвы с "
        "последующим использованием при рекультивации",
        "техническая и биологическая рекультивация нарушенных земель по "
        "завершении работ (ГОСТ Р 59070-2020, ПП РФ № 800)",
        "проведение химического анализа грунтов при их вывозе и использовании, "
        "определение класса опасности и категории загрязнения",
    ],
    "waste": [
        "раздельный сбор отходов по видам и классам опасности, оборудование "
        "мест накопления в соответствии с СанПиН 2.1.3684-21",
        "передача отходов I–IV класса опасности только организациям, имеющим "
        "лицензию на соответствующий вид деятельности",
        "соблюдение предельных сроков накопления отходов (11 месяцев) и "
        "ведение учёта в журнале по приказу Минприроды № 1028",
        "оформление паспортов отходов I–IV класса опасности "
        "(приказ Минприроды № 1026)",
    ],
    "subsoil": [
        "исключение проливов нефтепродуктов и химических веществ на грунт, "
        "содержание техники в исправном состоянии",
        "недопущение несанкционированного размещения отходов в подземных "
        "горных выработках и на территории объекта",
    ],
    "bio": [
        "проведение работ вне периода массового размножения объектов животного "
        "мира, недопущение уничтожения растительности вне границ работ",
        "компенсационное озеленение в объёме, согласованном с уполномоченным "
        "органом, при вынужденном сносе зелёных насаждений",
    ],
    "accidents": [
        "оснащение объекта первичными средствами пожаротушения и сорбентами "
        "для локализации проливов нефтепродуктов",
        "разработка порядка действий персонала при аварийных ситуациях и "
        "уведомления надзорных органов",
        "периодический осмотр оборудования и ёмкостей, ведение журнала "
        "технического обслуживания",
    ],
}

# что должно прийти из смежного ПО или изысканий — машиной не считается
EXTERNAL = {
    "air": "результаты расчёта рассеивания (УПРЗА «Эколог») — максимальные "
           "приземные концентрации в долях ПДК на границе жилой зоны",
    "water": "балансовая схема водопотребления и водоотведения",
    "assessment": "инженерно-экологические изыскания по участку "
                  "(СП 502.1325800.2021)",
}


def _num(value) -> str:
    if value in (None, ""):
        return "—"
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return str(value)
    return f"{d.normalize():f}" if d else "0"


def media(ctx: ReportContext) -> set[str]:
    """По каким средам у объекта есть воздействие — те пункты и раскрываем."""
    out: set[str] = set()
    for p in ctx.pollutants:
        if p.medium == Medium.AIR:
            out.add("air")
        elif p.medium == Medium.WATER:
            out.add("water")
    if ctx.wastes or ctx.waste_acts:
        out.add("waste")
    return out


def rows_air(ctx: ReportContext) -> list[dict]:
    return [{"name": p.name, "code": p.code,
             "mass": p.mass_norm + p.mass_limit + p.mass_over}
            for p in ctx.pollutants if p.medium == Medium.AIR]


def rows_water(ctx: ReportContext) -> list[dict]:
    return [{"name": p.name, "code": p.code,
             "mass": p.mass_norm + p.mass_limit + p.mass_over}
            for p in ctx.pollutants if p.medium == Medium.WATER]


def rows_waste(ctx: ReportContext) -> list[dict]:
    from ecodoc.development.waste_inventory import collect
    return collect(ctx)


def costs(ctx: ReportContext) -> dict:
    """Плата за НВОС как основа пункта «г» — расчёт затрат."""
    try:
        from ecodoc.reports.declaration_nvos.calc import calculate
        r = calculate(ctx)
    except Exception:
        return {}
    if not r.total:
        return {}
    return {"air": r.total_air, "water": r.total_water,
            "waste": r.total_waste, "total": r.total}


def gaps(ctx: ReportContext) -> list[str]:
    """Чего не хватает для раздела — тот же список, что и пометки в тексте."""
    out: list[str] = []
    org = ctx.organization
    if not (org.name or org.short_name):
        out.append("не заполнено наименование организации-заказчика")
    if not ctx.objects:
        out.append("не заведён объект: нет кода НВОС, адреса и категории")
    else:
        for o in ctx.objects:
            if not o.address:
                out.append(f"объект {o.code or o.name}: не указан адрес")
            if not o.category:
                out.append(f"объект {o.code or o.name}: не указана категория НВОС")
    have = media(ctx)
    if not have:
        out.append("нет ни выбросов, ни сбросов, ни отходов — раздел ООС "
                   "нечем наполнять: загрузите исходные данные")
    for key, text in EXTERNAL.items():
        if key == "assessment" or key in have:
            out.append(f"требуется: {text}")
    if "waste" in have:
        from ecodoc.development.waste_inventory import gaps as waste_gaps
        out += waste_gaps(ctx)
    return out


def generate(ctx: ReportContext, out_path: str | Path,
             stage: str = "эксплуатация") -> Path:
    """Раздел ООС (.docx): текстовая часть с таблицами и мероприятиями."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.shared import Cm, Pt

    org = ctx.organization
    obj = ctx.objects[0] if ctx.objects else None
    have = media(ctx)
    year = ctx.period.year or date.today().year

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    for s in doc.sections:
        s.left_margin, s.right_margin = Cm(3), Cm(1.5)
        s.top_margin, s.bottom_margin = Cm(2), Cm(2)

    # ── титул ────────────────────────────────────────────────────────────
    t = doc.add_paragraph()
    t.alignment = AL.CENTER
    t.add_run(org.name or org.short_name or "Заказчик не указан").bold = True
    doc.add_paragraph()
    h = doc.add_paragraph()
    h.alignment = AL.CENTER
    run = h.add_run(TITLE)
    run.bold = True
    run.font.size = Pt(14)
    sub = doc.add_paragraph()
    sub.alignment = AL.CENTER
    sub.add_run(f"Объект: {obj.name or obj.code if obj else '[требуется: объект]'}\n"
                f"Адрес: {obj.address if obj and obj.address else '[требуется: адрес]'}\n"
                f"Стадия: {stage}. {year} г.")
    doc.add_page_break()

    # ── содержание ───────────────────────────────────────────────────────
    doc.add_paragraph().add_run("СОДЕРЖАНИЕ").bold = True
    for i, (key, title, medium) in enumerate(SECTIONS, start=1):
        skip = medium and medium not in have
        doc.add_paragraph(f"{i}. {title}" + (" — не требуется" if skip else ""))
    doc.add_page_break()

    # ── общие сведения ───────────────────────────────────────────────────
    doc.add_paragraph().add_run("Общие сведения").bold = True
    doc.add_paragraph(
        f"Заказчик: {org.name or org.short_name or '[требуется]'}, "
        f"ИНН {org.inn or '[требуется]'}, ОГРН {org.ogrn or '—'}, "
        f"адрес: {org.address or '[требуется]'}.")
    if obj:
        doc.add_paragraph(
            f"Объект НВОС: {obj.code or '[требуется: код НВОС]'}, "
            f"категория {obj.category or '[требуется]'}, "
            f"адрес: {obj.address or '[требуется]'}.")
    doc.add_paragraph(
        "Раздел разработан в соответствии с постановлением Правительства РФ "
        "от 16.02.2008 № 87 (п. 25), Федеральным законом от 10.01.2002 № 7-ФЗ "
        "«Об охране окружающей среды» и действующими санитарными правилами.")

    n = 0
    for key, title, medium in SECTIONS:
        n += 1
        if medium and medium not in have:
            continue
        doc.add_paragraph()
        head = doc.add_paragraph()
        head.add_run(f"{n}. {title}").bold = True

        if key == "assessment":
            doc.add_paragraph(
                f"Воздействие объекта на окружающую среду оценивается по "
                f"следующим компонентам: "
                + (", ".join(sorted({"air": "атмосферный воздух",
                                     "water": "поверхностные и подземные воды",
                                     "waste": "обращение с отходами"}[m]
                                    for m in have)) if have
                   else "[требуется: исходные данные по воздействию]") + ".")
            doc.add_paragraph(f"[требуется: {EXTERNAL['assessment']}]")

        elif key == "air":
            rows = rows_air(ctx)
            doc.add_paragraph(
                f"Источники выбросов и валовые выбросы загрязняющих веществ "
                f"приняты по результатам инвентаризации ({len(rows)} "
                f"загрязняющих веществ):")
            _table(doc, ["№", "Загрязняющее вещество", "Код", "Выброс, т/год"],
                   [[str(i), r["name"] or "—", r["code"] or "—", _num(r["mass"])]
                    for i, r in enumerate(rows, start=1)])
            doc.add_paragraph(f"[требуется: {EXTERNAL['air']}]")
            _measures(doc, MEASURES["air"])

        elif key == "water":
            rows = rows_water(ctx)
            doc.add_paragraph("Сброс загрязняющих веществ со сточными водами:")
            _table(doc, ["№", "Загрязняющее вещество", "Код", "Сброс, т/год"],
                   [[str(i), r["name"] or "—", r["code"] or "—", _num(r["mass"])]
                    for i, r in enumerate(rows, start=1)])
            doc.add_paragraph(f"[требуется: {EXTERNAL['water']}]")
            _measures(doc, MEASURES["water"])

        elif key == "waste":
            rows = rows_waste(ctx)
            total = sum(Decimal(str(r.get("generated") or 0)) for r in rows)
            doc.add_paragraph(
                f"Перечень отходов, образующихся на объекте — {len(rows)} "
                f"вид(ов), суммарно {_num(total)} т/год:")
            _table(doc, ["№", "Наименование отхода", "Код ФККО", "Класс",
                         "Количество, т/год"],
                   [[str(i), r["name"] or "—", r["fkko"] or "—",
                     str(r["hazard"] or "—"), _num(r["generated"])]
                    for i, r in enumerate(rows, start=1)])
            _measures(doc, MEASURES["waste"])

        elif key == "pek":
            doc.add_paragraph(
                "Производственный экологический контроль осуществляется по "
                "программе ПЭК, разработанной в соответствии с приказом "
                "Минприроды России от 18.02.2022 № 109. Контролируемые "
                "показатели и периодичность приведены в программе ПЭК, "
                "выпускаемой отдельным документом.")
            if "air" in have:
                doc.add_paragraph(
                    "— контроль выбросов на источниках и на границе санитарно-"
                    "защитной зоны;")
            if "water" in have:
                doc.add_paragraph("— контроль качества сточных вод в контрольных точках;")
            if "waste" in have:
                doc.add_paragraph("— контроль мест накопления отходов и учёт их движения.")

        elif key == "costs":
            pay = costs(ctx)
            doc.add_paragraph(
                "Затраты на природоохранные мероприятия складываются из "
                "капитальных вложений в природоохранное оборудование, текущих "
                "затрат на его эксплуатацию и платы за негативное воздействие.")
            if pay:
                _table(doc, ["Показатель", "Значение, руб."],
                       [["Плата за выбросы", _num(pay.get("air"))],
                        ["Плата за сбросы", _num(pay.get("water"))],
                        ["Плата за размещение отходов", _num(pay.get("waste"))],
                        ["Итого плата за НВОС за год", _num(pay.get("total"))]])
            else:
                doc.add_paragraph(
                    "[требуется: расчёт платы за НВОС — заполните данные по "
                    "выбросам, сбросам и размещению отходов]")
            doc.add_paragraph(
                "[требуется: сметная стоимость природоохранных мероприятий по "
                "проекту]")

        else:
            _measures(doc, MEASURES.get(key, []))

    doc.add_paragraph()
    sign = doc.add_paragraph()
    sign.add_run(f"{org.director_position or 'Руководитель'}\t\t"
                 f"_____________\t{org.director_name or ''}")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def _measures(doc, items: list[str]) -> None:
    if not items:
        return
    doc.add_paragraph("Предусматриваются мероприятия:")
    for m in items:
        doc.add_paragraph(f"— {m};")


def _table(doc, header: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for i, text in enumerate(header):
        table.rows[0].cells[i].text = text
    for r in rows:
        cells = table.add_row().cells
        for i, text in enumerate(r):
            cells[i].text = text
    if not rows:
        cells = table.add_row().cells
        cells[0].text = "[требуется: данные не заведены]"
