"""ТУ — письмо-запрос технических условий на приём грунтов и отходов строительства.

Когда застройщик вывозит грунт и строительные отходы на карьер (рекультивация),
полигон или площадку переработки, оператор объекта выдаёт технические условия
(ТУ) на приём: какие отходы, в каком объёме, с какими документами и по какому
графику он готов принять. Запрос ТУ — обычное деловое письмо (ГОСТ Р
7.0.97-2016: бланк с реквизитами, дата/№, адресат, заголовок к тексту, текст,
отметка о приложениях, подпись, исполнитель); образцы и требования операторов —
Формы/Разработка/ТУ/ИСТОЧНИК.txt.

Содержательная часть: перечень отходов/грунтов с кодом ФККО, классом, объёмом
(м³) и массой (т). Перечень берётся из нормативов стадии строительства раздела
ООС (extra.oos_wastes, stage=строительство: там есть и т, и м³, и плотность),
иначе — из перечня отходов объекта (waste_inventory.collect: масса по актам/
движению, объём — по плотности актов). Адресат — из тела запроса (receiver),
иначе — фактический приёмщик этих отходов по актам. Плейсхолдеров в письме
нет: чего не хватает — в gaps().
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import ReportContext

TITLE = "Запрос технических условий на приём грунтов и отходов строительства"
NA = "—"

# группы ФККО, которые считаем «грунтами и отходами строительства» при отборе
# из общего перечня объекта (когда нормативов ООС нет)
_CONSTRUCTION_PREFIXES = ("81", "82", "83", "89", "343", "34", "4041", "4051", "46")


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return None
    return d if d else None


def _f(v) -> str:
    from ecodoc.development.waste_inventory import fmt_num
    return fmt_num(v)


def wastes_for_tu(ctx: ReportContext, stage: str = "строительство") -> list[dict]:
    """Перечень для письма: [{fkko, name, hazard, t, m3, density, handling, source}].

    source: «ООС» — из нормативов раздела ООС (stage), «объект» — из перечня
    отходов объекта (waste_inventory.collect)."""
    from ecodoc.core.waste_agg import norm_fkko
    from ecodoc.development.waste_inventory import collect

    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    oos = [x for x in (extra.get("oos_wastes") or []) if isinstance(x, dict)
           and norm_fkko(x.get("fkko"))]
    picked = [x for x in oos if x.get("stage") == stage] or oos
    out: list[dict] = []
    if picked:
        seen = set()
        for x in picked:
            code = norm_fkko(x.get("fkko"))
            if code in seen:
                continue
            seen.add(code)
            t, m3, dens = _dec(x.get("mass_t")), _dec(x.get("volume_m3")), _dec(x.get("density"))
            if m3 is None and t is not None and dens:
                m3 = (t / dens).quantize(Decimal("0.001"))
            if t is None and m3 is not None and dens:
                t = (m3 * dens).quantize(Decimal("0.001"))
            hz = x.get("hazard_class")
            out.append({"fkko": code, "name": str(x.get("name") or "").strip(),
                        "hazard": int(hz) if hz in (1, 2, 3, 4, 5) else
                        (int(code[-1]) if code[-1] in "12345" else 0),
                        "t": float(t) if t is not None else None,
                        "m3": float(m3) if m3 is not None else None,
                        "density": float(dens) if dens else None,
                        "handling": str(x.get("handling") or "").strip(),
                        "source": "ООС"})
        return out
    rows = collect(ctx)
    cons = [r for r in rows if r["fkko"].startswith(_CONSTRUCTION_PREFIXES)] or rows
    for r in cons:
        t = r["fact_year"] or r["generated"] or r["transferred"] or None
        # объём — только через плотность (сумма м³ из актов за все годы к
        # массе за отчётный год не относится; collect() уже отбросил
        # неправдоподобные пары т/м³)
        m3 = round(t / r["density"], 3) if (t and r["density"]) else None
        out.append({"fkko": r["fkko"], "name": r["name"], "hazard": r["hazard"],
                    "t": t, "m3": m3, "density": r["density"],
                    "handling": ", ".join(r["operations"]), "source": "объект",
                    "receivers": list(r["receivers"]), "licenses": list(r["licenses"]),
                    "passport": r["passport"], "has_biotest": r["has_biotest"]})
    return out


def default_receiver(ctx: ReportContext, items: list[dict]) -> tuple[str, str]:
    """(получатель, лицензия) — самый частый приёмщик этих отходов по актам."""
    from collections import Counter
    from ecodoc.core.waste_agg import norm_fkko
    codes = {i["fkko"] for i in items}
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    cnt: Counter = Counter()
    lic: dict[str, str] = {}
    for a in ctx.waste_acts:
        if norm_fkko(a.fkko_code) in codes and a.receiver:
            cnt[a.receiver.strip()] += 1
            if _looks_like_license(a.license):
                lic.setdefault(a.receiver.strip(), a.license)
    for x in extra.get("waste_receivers") or []:
        if isinstance(x, dict) and norm_fkko(x.get("fkko")) in codes and x.get("receiver"):
            cnt[str(x["receiver"]).strip()] += 1
            if _looks_like_license(x.get("license")):
                lic.setdefault(str(x["receiver"]).strip(), str(x["license"]))
    if not cnt:
        return "", ""
    name = cnt.most_common(1)[0][0]
    return name, lic.get(name, "")


def _looks_like_license(text) -> bool:
    """«Л020-00113-47/00095706 от 25.07.2023», «(78)-4579-СТОУР» — да; «51.0» — нет."""
    s = str(text or "").strip()
    return len(s) >= 8 and any(ch.isdigit() for ch in s) and \
        (any(ch.isalpha() for ch in s) or "№" in s or "-" in s or "/" in s)


def _receiver_license(ctx: ReportContext, receiver: str) -> str:
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    key = (receiver or "").strip().lower()[:25]
    if not key:
        return ""
    for a in ctx.waste_acts:
        if _looks_like_license(a.license) and (a.receiver or "").strip().lower()[:25] == key:
            return a.license
    for x in extra.get("waste_receivers") or []:
        if isinstance(x, dict) and _looks_like_license(x.get("license")) and \
                str(x.get("receiver") or "").strip().lower()[:25] == key:
            return str(x["license"])
    return ""


def gaps(ctx: ReportContext, receiver: str = "", stage: str = "строительство") -> list[str]:
    """Чего не хватает для полноценного письма-запроса ТУ."""
    from ecodoc.development.waste_inventory import main_object, site_address
    org = ctx.organization
    out: list[str] = []
    items = wastes_for_tu(ctx, stage)
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    has_oos = any(isinstance(x, dict) and x.get("fkko") for x in (extra.get("oos_wastes") or []))
    if not items:
        out.append("перечень отходов пуст — загрузите раздел ООС (таблица отходов "
                   "стадии строительства) или справки-акты по грунтам/отходам "
                   "строительства")
    elif not has_oos:
        out.append("нет нормативов стадии строительства из раздела ООС — перечень и "
                   "объёмы взяты по актам/движению объекта; загрузите ООС, чтобы в "
                   "письме были проектные объёмы (м³ и т)")
    elif not any(x.get("stage") == stage for x in extra.get("oos_wastes") or []
                 if isinstance(x, dict)):
        out.append(f"в ООС нет таблицы отходов стадии «{stage}» — взяты отходы "
                   f"другой стадии")
    rec = receiver or default_receiver(ctx, items)[0]
    if not receiver:
        if rec:
            out.append(f"адресат не задан — подставлен фактический приёмщик по актам "
                       f"«{rec}»; укажите получателя ТУ (поле «Адресат»), если письмо "
                       f"другому оператору")
        else:
            out.append("не указан адресат письма (оператор объекта приёма грунтов/"
                       "отходов: полигон, карьер рекультивации, площадка переработки) "
                       "— передайте receiver в запросе или укажите приёмщика в актах")
    if rec and not _receiver_license(ctx, rec):
        out.append(f"нет реквизитов лицензии получателя «{rec}» — укажите в акте/"
                   f"получателях (вкладка ОТХОДЫ), иначе в письме просим сообщить их")
    for it in items:
        label = it["name"] or it["fkko"]
        if not it.get("m3") and not it.get("t"):
            out.append(f"{label}: нет ни объёма (м³), ни массы (т) — укажите в ООС/актах")
        elif not it.get("m3"):
            out.append(f"{label}: нет объёма в м³ (нет плотности) — операторы принимают "
                       f"грунт по объёму")
        elif not it.get("t"):
            out.append(f"{label}: нет массы в т (нет плотности)")
        if it["hazard"] in (1, 2, 3, 4) and it.get("passport") is False:
            out.append(f"{label}: нет паспорта отхода (I–IV класс) — приложение к письму")
        if it["hazard"] == 5 and it.get("has_biotest") is False:
            out.append(f"{label}: V класс не подтверждён протоколом биотестирования — "
                       f"операторы требуют его для приёма грунта")
    if not (org.name or org.short_name):
        out.append("не указано наименование организации-отправителя")
    if not org.inn:
        out.append("не указан ИНН организации (бланк письма)")
    if not org.address:
        out.append("не указан адрес организации (бланк письма)")
    if not (org.phone or org.email):
        out.append("не указаны телефон/e-mail организации (бланк письма)")
    if not org.director_name:
        out.append("не указан руководитель (подписант письма)")
    if not main_object(ctx):
        out.append("не задан объект НВОС (код формата NN-NNNN-NNNNNN-Б)")
    if not site_address(ctx):
        out.append("не указан адрес объекта (площадки), откуда вывозятся отходы")
    if not ctx.period.year:
        out.append("не указан год — планируемый период передачи отходов")
    return out


def _hr(paragraph) -> None:
    """Нижняя линия под шапкой бланка."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "8"), ("w:space", "1"), ("w:color", "000000")):
        bottom.set(qn(k), v)
    borders.append(bottom)
    p_pr.append(borders)


def generate(ctx: ReportContext, out_path: str | Path,
             receiver: str = "", purpose: str = "",
             stage: str = "строительство") -> Path:
    """Письмо-запрос ТУ (.docx) на бланке организации."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH as AL
    from docx.shared import Cm, Pt

    from ecodoc.development.waste_inventory import (_fmt_code, _roman, docx_new,
                                                     docx_para, docx_table,
                                                     main_object, site_address)

    org = ctx.organization
    items = wastes_for_tu(ctx, stage)
    o = main_object(ctx)
    year = ctx.period.year or date.today().year
    rec = receiver.strip() if receiver else default_receiver(ctx, items)[0]
    rec_license = _receiver_license(ctx, rec) if rec else ""

    doc = docx_new()
    for s in doc.sections:
        s.left_margin, s.right_margin = Cm(3), Cm(1.5)

    # ── бланк письма: наименование, реквизиты, линия ─────────────────────
    docx_para(doc, org.name or org.short_name or "", bold=True, align="center", size=14)
    if org.short_name and org.name and org.short_name != org.name:
        docx_para(doc, f"({org.short_name})", align="center", size=11)
    req = []
    if org.address:
        req.append(org.address)
    ids = ", ".join(x for x in (f"ИНН {org.inn}" if org.inn else "",
                                f"КПП {org.kpp}" if org.kpp else "",
                                f"ОГРН{'ИП' if org.is_individual else ''} {org.ogrn}"
                                if org.ogrn else "") if x)
    if ids:
        req.append(ids)
    contacts = ", ".join(x for x in (f"тел. {org.phone}" if org.phone else "",
                                     f"e-mail: {org.email}" if org.email else "") if x)
    if contacts:
        req.append(contacts)
    last = None
    for line in req:
        last = docx_para(doc, line, align="center", size=10)
    if last is None:
        last = doc.add_paragraph()
    _hr(last)

    # ── дата/№ слева, адресат справа (таблица без границ) ────────────────
    head = doc.add_table(rows=1, cols=2)
    head.autofit = False
    left, right = head.rows[0].cells
    left.width, right.width = Cm(8), Cm(8.5)
    left.text = ""
    p = left.paragraphs[0]
    p.add_run(f"«___» __________ {year} г.  № ______").font.size = Pt(11)
    p2 = left.add_paragraph()
    p2.add_run("На № ________ от __________").font.size = Pt(11)
    right.text = ""
    rp = right.paragraphs[0]
    rp.alignment = AL.LEFT
    if rec:
        rp.add_run("Руководителю\n").font.size = Pt(11)
        r2 = rp.add_run(rec)
        r2.bold = True
        r2.font.size = Pt(11)
    else:
        rp.add_run("Руководителю организации — оператора объекта приёма "
                   "грунтов и отходов строительства").font.size = Pt(11)
    doc.add_paragraph()

    # ── заголовок к тексту ───────────────────────────────────────────────
    docx_para(doc, "О выдаче технических условий на приём грунтов и отходов "
                   "строительства", bold=True)

    # ── текст ────────────────────────────────────────────────────────────
    obj_name = (o.name if o else "") or (ctx.extra or {}).get("site_name") or "объект"
    addr = site_address(ctx)
    what = ("работы по строительству (реконструкции) объекта" if stage == "строительство"
            else "хозяйственную деятельность на объекте")
    docx_para(doc, (
        f"{org.short_name or org.name}"
        f"{(' (ИНН ' + org.inn + ')') if org.inn else ''} выполняет {what} "
        f"«{obj_name}»"
        + (f", расположенного по адресу: {addr}" if addr else "")
        + (f" (код объекта НВОС {o.code})" if o else "")
        + f". В ходе {'строительных работ' if stage == 'строительство' else 'деятельности'} "
        f"образуются следующие грунты и отходы строительства, подлежащие вывозу "
        f"в {year} году:"), align="justify")

    table_rows = []
    for i, it in enumerate(items, start=1):
        table_rows.append([str(i), it["name"] or NA, _fmt_code(it["fkko"]),
                           _roman(it["hazard"]) or "не определён",
                           _f(it["m3"]) if it.get("m3") else NA,
                           _f(it["t"]) if it.get("t") else NA,
                           it.get("handling") or "передача на объект приёма"])
    docx_table(doc, ["№", "Наименование отхода по ФККО", "Код ФККО", "Класс опасности",
                     "Объём, м³", "Масса, т", "Планируемое обращение"],
               table_rows, widths_cm=[0.8, 6, 2.6, 1.6, 1.7, 1.7, 3.6], font_size=9,
               empty_text="перечень отходов формируется по разделу ООС (стадия "
                          "строительства) — данные не загружены")
    tot_m3 = sum(it["m3"] or 0 for it in items)
    tot_t = sum(it["t"] or 0 for it in items)
    if items:
        docx_para(doc, f"Итого: {_f(tot_m3) if tot_m3 else NA} м³ / "
                       f"{_f(tot_t) if tot_t else NA} т"
                       + (" (по расчёту раздела ООС проектной документации)."
                          if items[0]["source"] == "ООС" else
                          " (по данным учёта отходов объекта)."))

    docx_para(doc, (
        "В соответствии со ст. 11, 14 и 19 Федерального закона от 24.06.1998 "
        "№ 89-ФЗ «Об отходах производства и потребления» просим выдать "
        "технические условия на приём указанных грунтов и отходов на "
        "эксплуатируемый Вами объект"
        + (f" для {purpose.strip()}" if purpose and purpose.strip() else "")
        + " с указанием:"), align="justify")
    for line in [
        "возможности приёма и предельного объёма по каждому виду отхода (грунта);",
        "требований к качеству (класс опасности, подтверждение протоколами "
        "биотестирования и КХА, паспортами отходов I–IV классов, отсутствие "
        "включений);",
        "требований к транспортированию, режима и графика завоза, оформления "
        "сопроводительных документов (талоны, акты приёма-передачи);",
        "реквизитов лицензии на деятельность по обращению с отходами и объекта "
        "(№ в ГРОРО либо проект рекультивации / технические условия на "
        "использование грунта);",
        "стоимости приёма и порядка заключения договора.",
    ]:
        docx_para(doc, "– " + line, align="justify")
    if rec_license:
        docx_para(doc, f"По имеющимся у нас сведениям, деятельность осуществляется на "
                       f"основании лицензии {rec_license}; просим подтвердить "
                       f"актуальность её реквизитов.", align="justify")

    # ── приложения ───────────────────────────────────────────────────────
    passports = [it["name"] for it in items if it.get("passport")]
    protocols = [x for x in (ctx.extra or {}).get("lab_results", []) if isinstance(x, dict)]
    apps = []
    if passports:
        apps.append(f"Копии паспортов отходов I–IV классов опасности ({len(passports)} шт.): "
                    + "; ".join(passports) + ".")
    else:
        apps.append("Копии паспортов отходов I–IV классов опасности (при наличии "
                    "отходов I–IV классов в перечне).")
    apps.append("Копии протоколов биотестирования / КХА, подтверждающих класс "
                "опасности" + (f" ({len(protocols)} шт.)." if protocols else "."))
    apps.append("Копия свидетельства о постановке объекта на государственный учёт "
                "(код объекта НВОС)." if o else
                "Сведения об объекте, на котором образуются отходы.")
    if items and items[0]["source"] == "ООС":
        apps.append("Выписка из раздела «Перечень мероприятий по охране окружающей "
                    "среды» проектной документации (расчёт объёмов образования "
                    "отходов строительства).")
    docx_para(doc, "Приложения:", bold=True)
    for i, a in enumerate(apps, start=1):
        docx_para(doc, f"{i}. {a}", align="justify")

    # ── подпись, исполнитель ─────────────────────────────────────────────
    doc.add_paragraph()
    docx_para(doc, f"{org.official_title or 'Руководитель'}\t\t_____________\t"
                   f"{org.director_name or '________________'}")
    doc.add_paragraph()
    resp = (ctx.extra or {}).get("waste_responsible") or ""
    docx_para(doc, "Исп.: " + (resp or org.director_name or "")
              + (f", тел. {org.phone}" if org.phone else "")
              + (f", {org.email}" if org.email else ""), size=10)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out
