"""Отчёт об инвентаризации стационарных источников и выбросов ЗВ.

НПА: приказ Минприроды России от 19.11.2021 № 871 «Об утверждении Порядка
проведения инвентаризации стационарных источников и выбросов загрязняющих
веществ в атмосферный воздух, корректировки ее данных, документирования и
хранения данных, полученных в результате проведения таких инвентаризации и
корректировки» (зарег. Минюстом 30.11.2021 № 66125, действует с 01.03.2022
по 01.03.2028, изменений не вносилось — проверено 22.08.2026 по
consultant.ru / normativ.kontur.ru).

Почему модуль переписан: прежняя версия выдавала «листик» — три листа xlsx
с перечнем источников и веществ. Настоящий отчёт (образец —
ООО «ПРОТЕЛЮКС», 609 стр., разработчик ООО «Альянс Консалтинг») собран по
рекомендуемому образцу содержания (приложение 4 к Порядку) и таблицам
приложений 1–3. Теперь генерируются:

  * .docx — полнотекстовый отчёт: титул, сведения о разработчике, содержание,
    введение с таблицей 1 «Полный перечень ЗВ», разделы 1–7 по приложению 4,
    перечень приложений;
  * .xlsx — те же таблицы в машиночитаемом виде (листы «Источники» и
    «Вещества» сохранены: их читают GUI/тесты) плюс листы с таблицами
    3.1, 3.2, 3.6, 3.7, 1.1–1.3, 2.1 по приказу № 871.

Откуда данные (ReportContext):
  * ctx.extra['emission_sources'] — источники (number, name, kind, pollutants
    [{code, name, g_s, t_year, conc}]) + необязательные параметры ИЗАВ
    (height, diameter, length, width, x1, y1, x2, y2, speed, volume,
    temperature, density, area_width, mode, count, workshop, site, ...);
  * ctx.pollutants (Medium.AIR) — валовые выбросы по веществам;
  * ctx.extra['air_inventory'] — «паспорт» отчёта: разработчик, исполнители,
    дата, описание производства, ГОУ, замеры (таблица 2.1), методики.

Чего нет в контексте — в документе стоит «[требуется: …]», а gaps() даёт
перечень замечаний для вкладки программы.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ecodoc.core.models import Medium, ReportContext
from ecodoc.render import xlsx

TITLE = "Отчёт по инвентаризации стационарных источников и выбросов загрязняющих веществ в атмосферный воздух"
SHORT_TITLE = "Инвентаризация стационарных источников выбросов"
NPA = ("приказ Минприроды России от 19.11.2021 № 871 «Об утверждении Порядка "
       "проведения инвентаризации стационарных источников и выбросов "
       "загрязняющих веществ в атмосферный воздух, корректировки ее данных, "
       "документирования и хранения данных, полученных в результате проведения "
       "таких инвентаризации и корректировки»")
NPA_SHORT = "приказ Минприроды России от 19.11.2021 № 871"

# ── Рекомендуемый образец содержания отчёта (приложение 4 к Порядку № 871).
# Формулировки — как в приложении 4 и в реальном отчёте (ПРОТЕЛЮКС, стр. 3).
SECTIONS = [
    ("1", "Сведения о хозяйствующем субъекте, объекте ОНВ, его отдельных "
          "территориях и производственной деятельности, включая сведения о "
          "количестве, характеристиках и эффективности ГОУ"),
    ("2", "Описание проведенных работ по инвентаризации выбросов с указанием "
          "нормативно-методических документов, перечня использованных методик "
          "выполнения измерений ЗВ и расчетного определения выбросов ЗВ"),
    ("3", "Карта-схема территории объекта ОНВ"),
    ("4", "Характеристики ИЗАВ, показатели работы ГОУ, суммарные выбросы по "
          "объекту ОНВ"),
    ("5", "Результаты определения выбросов ЗВ расчетными (балансовыми) "
          "методами, включающие, при необходимости, данные о расходах и "
          "составах сырья и топлива"),
    ("6", "Результаты инструментального определения показателей выбросов с "
          "приложением соответствующих расчетов, актов отборов проб и "
          "протоколов анализов, в том числе сведений об отборе проб и о "
          "количественном определении массовой концентрации ЗВ и параметров "
          "газовоздушной смеси, расчетов показателей выбросов на основе "
          "значений, полученных в результате измерений"),
    ("7", "Документирование характеристик нестационарности выбросов"),
]
SUBSECTIONS = {
    "1": [("1.1", "Реквизиты объекта ОНВ"),
          ("1.2", "Краткое описание видов деятельности на объекте ОНВ"),
          ("1.2.1", "Краткая характеристика технологии производства и "
                    "технологического оборудования объекта ОНВ"),
          ("1.2.2", "Сведения о сырье, материалах, топливе и выпускаемой продукции"),
          ("1.2.3", "Сведения о количестве, характеристиках и эффективности ГОУ"),
          ("1.2.4", "Мероприятия по охране атмосферного воздуха"),
          ("1.3", "Сведения о результатах предыдущей инвентаризации"),
          ("1.4", "Краткая характеристика прилегающей к объекту ОНВ местности"),
          ("1.5", "Размеры и границы санитарно-защитной зоны объекта ОНВ")],
    "4": [("4.1", "Источники выделения загрязняющих веществ"),
          ("4.2", "Источники выбросов загрязняющих веществ"),
          ("4.3", "Результаты обследования ГОУ и условий их эксплуатации"),
          ("4.4", "Суммарные выбросы по объекту ОНВ")],
}

# Перечень приложений к отчёту — по приложению 4 к Порядку (пп. 11–12) и
# реальному отчёту (стр. 4).
APPENDICES = [
    "Приложение 1. Исходные данные по предприятию",
    "Приложение 2. Справка по климатическим характеристикам и фоновым концентрациям",
    "Приложение 3. Расчет выбросов ЗВ",
    "Приложение 4. Расчет рассеивания ЗВ",
    "Приложение 5. Паспорта на оборудование (ГОУ)",
    "Приложение 6. Паспорт качества газа и режимные карты",
    "Приложение 7. Сан-эпид заключение на проект СЗЗ и письмо об установлении СЗЗ",
    "Приложение 8. Выписка из ЕГРН на здания, земельный участок",
    "Приложение 9. Протоколы замеров (акты отбора проб, протоколы анализов)",
    "Приложение 10. Копия аттестата аккредитации аналитической лаборатории",
    "Приложение 11. Карта-схема территории объекта ОНВ с нанесёнными ИЗАВ",
]

# ── Шапки таблиц — дословно по приложениям 1–3 к Порядку № 871 ───────────
# (сверено с consultant.ru, таблицы 3.1/3.2/3.6/3.7/2.1, и с реальным отчётом,
# где таблицы 4.2.1/4.3.1/4.4.1/7.1–7.3 выгружены из «Эколога» по № 871).

# Таблица 1 введения (реальный отчёт, стр. 7): полный перечень ЗВ.
T1_HEADER = ["Код", "Наименование загрязняющего вещества", "Вид ПДК",
             "Значение ПДК (ОБУВ), мг/м3", "Класс опасности",
             "Суммарный выброс загрязняющих веществ, г/с",
             "Суммарный выброс загрязняющих веществ, т/г"]

# Таблица 3.1 «Источники выделения загрязняющих веществ».
T31_TITLE = "Таблица 3.1. Источники выделения загрязняющих веществ"
T31_HEADER = [
    "№ цеха", "Наименование цеха", "№ участка", "Наименование участка",
    "Номер источника выделения (ИВ)", "Наименование источника выделения (ИВ)",
    "Характеристика нестационарности работы ИВ (№ режима нестационарности)",
    "Время работы ИВ с учетом нестационарности, час/сутки",
    "Время работы ИВ с учетом нестационарности, часов в год",
    "Количество ИВ под одним номером",
    "Загрязняющее вещество: код", "Загрязняющее вещество: наименование",
    "Количество ЗВ, отходящих от ИВ при учете нестационарности, г/с",
    "Количество ЗВ, отходящих от ИВ всего, т/год",
    "Инвентарный № газоочистного оборудования", "Номер ИЗАВ", "Примечание"]

# Таблица 3.2 «Стационарные источники выбросов загрязняющих веществ» —
# 26 граф (реальный отчёт использует 24: без вертикальной составляющей
# скорости и плотности ГВС — их «Эколог» не выгружает).
T32_TITLE = "Таблица 3.2. Стационарные источники выбросов загрязняющих веществ"
T32_HEADER = [
    "№ ИЗАВ", "Тип ИЗАВ", "Наименование ИЗАВ",
    "Число ИЗАВ, объединенных под одним номером", "Высота источника, м",
    "Размеры устья источника: круглое устье — диаметр, м",
    "Размеры устья источника: прямоугольное устье — длина, м",
    "Размеры устья источника: прямоугольное устье — ширина, м",
    "Координаты источника на карте-схеме: X1", "Координаты источника на карте-схеме: Y1",
    "Координаты источника на карте-схеме: X2", "Координаты источника на карте-схеме: Y2",
    "Ширина площадного источника, м", "Номер режима (стадии) выброса",
    "Скорость выхода ГВС, м/с", "Вертикальная составляющая скорости, м/с",
    "Объем (расход) ГВС, м3/с", "Температура ГВС, град. С", "Плотность ГВС, кг/м3",
    "Выбрасываемые в атмосферу вещества: код",
    "Выбрасываемые в атмосферу вещества: наименование",
    "Выбрасываемые в атмосферу вещества: концентрация, мг/м3",
    "Выбрасываемые в атмосферу вещества: мощность выброса, г/с",
    "Выбрасываемые в атмосферу вещества: валовый выброс режима (стадии) ИЗА, т/год",
    "Итого за год выброс вещества источником, т/год", "Примечание"]

# Таблица 3.6 «Результаты обследования установок очистки газа и условий их
# эксплуатации» — 11 граф.
T36_TITLE = ("Таблица 3.6. Результаты обследования установок очистки газа и "
             "условий их эксплуатации")
T36_HEADER = [
    "№ цеха", "Наименование цеха", "№ участка",
    "Наименование источника выделения (выброса), его номер",
    "Наименование установки очистки газа, её тип и марка (номер в реестре)",
    "Номер ИЗАВ (после очистки)",
    "Эффективность установки очистки газа, %: проектная",
    "Эффективность установки очистки газа, %: фактическая",
    "Наименование и код загрязняющего вещества",
    "Коэффициент обеспеченности, %: нормативный",
    "Коэффициент обеспеченности, %: фактический"]

# Таблица 3.7 «Суммарные выбросы ЗВ…» — 10 граф; порядок граф — как в
# выгрузке «Эколога» в реальном отчёте (табл. 4.4.1, стр. 58).
T37_TITLE = ("Таблица 3.7. Суммарные выбросы ЗВ в атмосферный воздух, их очистка "
             "и утилизация (в целом по объекту ОНВ), т/год")
T37_HEADER = [
    "Загрязняющее вещество: код", "Загрязняющее вещество: наименование",
    "Количество загрязняющих веществ, отходящих от источников выделения",
    "Выбрасывается без очистки: всего",
    "Выбрасывается без очистки: в т.ч. от организованных источников загрязнения",
    "Поступает на очистку",
    "Из поступивших на очистку: уловлено и обезврежено — фактически",
    "Из поступивших на очистку: уловлено и обезврежено — из них утилизировано",
    "Из поступивших на очистку: выброшено в атмосферный воздух",
    "Всего выброшено в атмосферный воздух"]

# Таблица 3.8 «Выбросы от передвижных ИЗАВ» (п. 40 Порядка).
T38_TITLE = "Таблица 3.8. Выбросы от передвижных ИЗАВ"
T38_HEADER = ["№ п/п", "Вид передвижного ИЗАВ", "Количество, ед.",
              "Скорость движения по территории объекта, км/ч", "Вид топлива",
              "Время работы за сезон, ч", "Время работы за год, ч",
              "Наименование и код ЗВ", "Выброс ЗВ максимальный, г/с",
              "Выброс ЗВ, т/год", "Ссылка на расчетную методику"]

# Приложение 1 — нестационарность (шапки дословно из реального отчёта,
# табл. 7.1–7.3 = табл. 1.1–1.3 Порядка).
T11_TITLE = ("Таблица 1.1. Режимы работы ИЗАВ и их временные характеристики при "
             "нестационарности выбросов")
T11_HEADER = ["№ ИЗАВ", "Источник выделения (ИВ): номер ИВ",
              "Источник выделения (ИВ): наименование ИВ",
              "Источник выделения (ИВ): описание режима работы ИВ",
              "Источник выделения (ИВ): время работы ИВ на конкретном режиме за период времени",
              "№ (код) режима ИЗАВ (присваивается в зависимости от времени работы "
              "ИВ, одинаков для одновременно работающих ИЗАВ)"]
T12_TITLE = ("Таблица 1.2. Характеристика одновременности работы оборудования "
             "при нестационарных выбросах")
T12_HEADER = ["Наименование цеха", "Источники выделения (выброса): №",
              "Источники выделения (выброса): наименование",
              "Количество: всего", "Количество: в том числе одновременно работающих",
              "Коэффициент одновременности загрузки оборудования К0 (графа 5 / графа 4)",
              "Номер ИЗАВ"]
T13_TITLE = "Таблица 1.3. Учет нестационарности выбросов"
T13_HEADER = ["№ п/п", "№ ИЗАВ", "Источник выделения",
              "Характеристики технологических стадий: наименование характеристики",
              "Характеристики технологических стадий: значения характеристик "
              "технологических стадий"]

# Приложение 2 — инструментальные измерения (таблица 2.1 Порядка).
T21_TITLE = ("Таблица 2.1. Результаты инструментального определения показателей "
             "выбросов")
T21_HEADER = ["№ п/п", "Дата",
              "Наименование цеха, участка, наименование источника выделения, режим работы",
              "ИЗАВ, его номер",
              "Показатели отходящих газов в месте измерений: диаметр (размер сечения), м",
              "Показатели отходящих газов в месте измерений: скорость, м/с",
              "Показатели отходящих газов в месте измерений: объемный расход, м3/с",
              "Показатели отходящих газов в месте измерений: температура, °C",
              "Показатели отходящих газов в месте измерений: давление/разряжение, кПа",
              "Показатели отходящих газов в месте измерений: концентрация паров воды, г/м3",
              "Наименование и код загрязняющего вещества",
              "Методика выполнения измерений",
              "Массовая концентрация ЗВ, мг/м3",
              "Выброс ЗВ средний, г/с", "Выброс ЗВ максимальный, г/с"]

# Твёрдые вещества (агрегатное состояние) — для итогов «в т.ч. твердых» в
# табл. 3.7. Коды по перечню Расп. № 1316-р / справочнику «Эколога»: взвешенные,
# пыли, металлы и их соединения, сажа, бенз/а/пирен.
SOLID_CODES = {"0101", "0104", "0108", "0110", "0118", "0123", "0128", "0140",
               "0142", "0143", "0146", "0158", "0164", "0168", "0183", "0184",
               "0203", "0207", "0214", "0228", "0260", "0322", "0328", "0703",
               "1301", "1555", "2902", "2904", "2907", "2908", "2909", "2930",
               "2936", "2950", "3123", "3714", "3721"}


# ── числовые помощники ───────────────────────────────────────────────────

def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", ".").replace(" ", ""))
    except Exception:
        return None
    return float(d)


def fmt(value, digits: int = 6) -> str:
    """Число → строка как в «Экологе» (6 знаков, без экспоненты для мелких)."""
    v = _num(value)
    if v is None:
        return ""
    if v == 0:
        return "0"
    text = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else f"{v:.2e}"


def _first(d: dict, *keys, default=""):
    """Первый непустой ключ из списка синонимов (ИИ и парсеры именуют по-разному)."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


# ── данные из контекста ──────────────────────────────────────────────────

def cfg(ctx: ReportContext) -> dict:
    """«Паспорт» отчёта: extra['air_inventory'] (разработчик, исполнители, ГОУ…)."""
    c = (ctx.extra or {}).get("air_inventory")
    return c if isinstance(c, dict) else {}


def sources(ctx: ReportContext) -> list[dict]:
    """Источники выбросов из разобранных документов + параметры ИЗАВ.

    Ключи параметров читаются с синонимами: программа получает их и от ИИ
    (analyzer), и из выгрузок «Эколога», и из ручного ввода в GUI.
    """
    out = []
    for s in (ctx.extra or {}).get("emission_sources", []):
        if not isinstance(s, dict):
            continue
        subs = []
        for p in (s.get("pollutants") or []):
            if not isinstance(p, dict):
                continue
            subs.append({"code": str(_first(p, "code")), "name": str(_first(p, "name")),
                         "g_s": _first(p, "g_s", "gs", "max_g_s"),
                         "t_year": _first(p, "t_year", "t_god", "year"),
                         "conc": _first(p, "conc", "concentration", "mg_m3")})
        kind = str(s.get("kind") or "")
        num = str(s.get("number") or "")
        # неорганизованные источники в практике нумеруются с 6001
        if not kind and num.isdigit():
            kind = "неорганизованный" if int(num) >= 6000 else "организованный"
        out.append({
            "number": num, "name": str(s.get("name") or ""), "kind": kind,
            "type": str(_first(s, "type", "izav_type",
                               default=("площадной" if "неорг" in kind
                                        else "точечный" if kind else ""))),
            "count": _first(s, "count", "number_of", default="1"),
            "height": _first(s, "height", "h"),
            "diameter": _first(s, "diameter", "d"),
            "length": _first(s, "length"), "width": _first(s, "width"),
            "x1": _first(s, "x1", "x"), "y1": _first(s, "y1", "y"),
            "x2": _first(s, "x2"), "y2": _first(s, "y2"),
            "area_width": _first(s, "area_width"),
            "mode": _first(s, "mode", "regime", default="1"),
            "speed": _first(s, "speed", "velocity", "w0"),
            "speed_v": _first(s, "speed_v", "vertical_speed"),
            "volume": _first(s, "volume", "flow", "v1"),
            "temperature": _first(s, "temperature", "temp", "t"),
            "density": _first(s, "density"),
            "workshop": _first(s, "workshop", "ceh"), "site": _first(s, "site", "uchastok"),
            "emitters": [e for e in (s.get("emitters") or []) if isinstance(e, dict)],
            "gou": _first(s, "gou", "cleaning"),
            "hours_day": _first(s, "hours_day"), "hours_year": _first(s, "hours_year"),
            "method": _first(s, "method", "methodology"),
            "measured": bool(s.get("measured")),
            "note": str(_first(s, "note", "comment")),
            "src": str(s.get("_src") or ""),
            "pollutants": subs})
    return out


def air_pollutants(ctx: ReportContext) -> list[dict]:
    """Вещества-выбросы с массами (валовые за год) из ctx.pollutants."""
    out = []
    for p in ctx.pollutants:
        if p.medium != Medium.AIR:
            continue
        total = sum(x for x in (_num(p.mass_norm), _num(p.mass_limit),
                                _num(p.mass_over)) if x)
        out.append({"code": p.code or "", "name": p.name or "",
                    "norm": _num(p.mass_norm), "limit": _num(p.mass_limit),
                    "over": _num(p.mass_over), "total": total or None,
                    "source": p.source or ""})
    return out


def substance_totals(ctx: ReportContext) -> list[dict]:
    """Сводка по веществам: г/с и т/год суммой по источникам.

    Почему так: в отчёте «Полный перечень ЗВ» и табл. 3.7 строятся от
    источников (как в «Экологе»). Если по веществу нет разбивки по
    источникам, берём валовую массу из ctx.pollutants; при расхождении
    источников и перечня выигрывают источники, а расхождение попадает в gaps().
    """
    agg: dict[str, dict] = {}
    for s in sources(ctx):
        org = "неорг" not in s["kind"]
        for p in s["pollutants"]:
            key = p["code"] or p["name"]
            if not key:
                continue
            a = agg.setdefault(key, {"code": p["code"], "name": p["name"],
                                     "g_s": 0.0, "t_year": 0.0, "t_org": 0.0,
                                     "from_sources": True})
            a["name"] = a["name"] or p["name"]
            a["g_s"] += _num(p["g_s"]) or 0.0
            t = _num(p["t_year"]) or 0.0
            a["t_year"] += t
            if org:
                a["t_org"] += t
    for p in air_pollutants(ctx):
        key = p["code"] or p["name"]
        if not key:
            continue
        a = agg.get(key)
        if a is None:
            agg[key] = {"code": p["code"], "name": p["name"], "g_s": 0.0,
                        "t_year": p["total"] or 0.0, "t_org": 0.0,
                        "from_sources": False}
        elif not a["t_year"] and p["total"]:
            a["t_year"] = p["total"]
    rows = list(agg.values())
    for r in rows:
        r["solid"] = r["code"] in SOLID_CODES
    rows.sort(key=lambda r: (not r["solid"], r["code"] or "9999", r["name"]))
    return rows


def gou_list(ctx: ReportContext) -> list[dict]:
    """Установки очистки газа: extra['air_inventory']['gou'] + поле gou у источников."""
    out = []
    for g in cfg(ctx).get("gou") or []:
        if isinstance(g, dict):
            out.append(dict(g))
    for s in sources(ctx):
        g = s["gou"]
        if isinstance(g, dict) and not any(
                str(x.get("izav") or "") == s["number"] for x in out):
            out.append({"izav": s["number"], "emitter": s["name"], **g})
        elif isinstance(g, str) and g:
            out.append({"izav": s["number"], "emitter": s["name"], "name": g})
    return out


def measurements(ctx: ReportContext) -> list[dict]:
    """Строки инструментальных измерений (табл. 2.1) из extra['air_inventory']."""
    return [m for m in (cfg(ctx).get("measurements") or []) if isinstance(m, dict)]


def gaps(ctx: ReportContext) -> list[str]:
    """Чего не хватает для полного отчёта по № 871."""
    out = []
    srcs, subs, c = sources(ctx), air_pollutants(ctx), cfg(ctx)
    org = ctx.organization
    if not srcs:
        out.append("не найдены источники выбросов — загрузите раздел ООС, проект "
                   "НДВ или отчёт по инвентаризации (вкладка ЗАГРУЗКА, "
                   "категория «воздух»)")
    if not subs and not any(s["pollutants"] for s in srcs):
        out.append("не заданы вещества и массы выбросов — заполните вкладку ВЫБРОСЫ")
    if not org.ogrn:
        out.append("не указан ОГРН/ОГРНИП хозяйствующего субъекта (п. 35 «а» Порядка № 871)")
    if not ctx.objects or not ctx.objects[0].address:
        out.append("не указан адрес места нахождения объекта ОНВ (п. 35 Порядка № 871)")
    if not ctx.objects or not ctx.objects[0].code:
        out.append("не указан код объекта ОНВ (реквизиты объекта, разд. 1.1)")
    for s in srcs:
        if not s["number"]:
            out.append(f"источник «{s['name'] or '—'}»: не указан номер ИЗАВ")
        if not s["pollutants"]:
            out.append(f"источник №{s['number'] or '—'}: не указаны вещества и объёмы")
        missing = [lbl for key, lbl in (("height", "высота"), ("x1", "координаты X1/Y1"),
                                        ("speed", "скорость ГВС"), ("volume", "объём ГВС"),
                                        ("temperature", "температура ГВС"))
                   if not s[key]]
        if "неорг" not in s["kind"] and missing:
            out.append(f"источник №{s['number'] or '—'} «{s['name']}»: нет параметров "
                       f"ИЗАВ для табл. 3.2 — {', '.join(missing)}")
        if "неорг" in s["kind"] and not (s["x1"] and s["x2"]):
            out.append(f"источник №{s['number'] or '—'} «{s['name']}»: для площадного "
                       "ИЗАВ нужны координаты X1/Y1/X2/Y2 и ширина площадки")
        for p in s["pollutants"]:
            if not p["code"]:
                out.append(f"источник №{s['number']}: у вещества «{p['name']}» нет кода")
            if not p["g_s"]:
                out.append(f"источник №{s['number']}: у {p['code'] or p['name']} нет "
                           "мощности выброса, г/с (п. 38 Порядка № 871)")
            if not p["t_year"]:
                out.append(f"источник №{s['number']}: у {p['code'] or p['name']} нет "
                           "валового выброса, т/год")
    for p in subs:
        if not p["code"]:
            out.append(f"вещество «{p['name'] or '—'}»: не указан код")
        if not p["total"]:
            out.append(f"вещество {p['name'] or p['code']}: не указана масса, т/год")
    # сверка перечня веществ с источниками: расхождение > 5 % — замечание
    by_src = {r["code"]: r for r in substance_totals(ctx) if r["from_sources"]}
    for p in subs:
        r = by_src.get(p["code"])
        if r and p["total"] and r["t_year"] and \
                abs(r["t_year"] - p["total"]) > 0.05 * max(r["t_year"], p["total"]):
            out.append(f"вещество {p['code']}: сумма по источникам {fmt(r['t_year'])} т/год "
                       f"≠ валовой массе {fmt(p['total'])} т/год во вкладке ВЫБРОСЫ")
    if not c.get("developer"):
        out.append("не указан разработчик отчёта и исполнители (лист «Сведения о "
                   "разработчике») — extra.air_inventory.developer/executors")
    if not c.get("production"):
        out.append("нет описания технологии производства и оборудования "
                   "(разд. 1.2.1; п. 35 «б» Порядка № 871)")
    if not c.get("surroundings"):
        out.append("нет характеристики прилегающей местности (разд. 1.4; п. 35 «г»)")
    if not c.get("szz"):
        out.append("нет сведений о размерах и границах СЗЗ (разд. 1.5; п. 35 «д»)")
    if not c.get("responsible") and not org.director_name:
        out.append("не указано ответственное за инвентаризацию должностное лицо (п. 35 «е»)")
    if not c.get("map"):
        out.append("нет карты-схемы территории объекта ОНВ с ИЗАВ (разд. 3; п. 37 Порядка)")
    if not gou_list(ctx) and c.get("has_gou") is None:
        out.append("не указано, есть ли ГОУ (табл. 3.6): если нет — отметьте "
                   "air_inventory.has_gou=false")
    if any(s["measured"] for s in srcs) and not measurements(ctx):
        out.append("есть источники с инструментальным определением, но нет протоколов "
                   "измерений для табл. 2.1 (разд. 6; приложение 2 Порядка)")
    if not c.get("methods") and not any(s["method"] for s in srcs):
        out.append("не указаны методики расчёта выбросов по источникам (разд. 2 и 5; "
                   "перечень методик — распоряжение Минприроды от 14.12.2020 № 35-р)")
    if not c.get("date"):
        out.append("не указана дата проведения/утверждения инвентаризации (п. 34 Порядка)")
    return out


# ── строки таблиц (общие для xlsx и docx) ────────────────────────────────

def rows_t1(ctx: ReportContext) -> list[list[str]]:
    """Таблица 1 введения: полный перечень ЗВ с ПДК (ПДК — из справочника, если есть)."""
    # справочник substances.json (код, ПДК м/р и с/с) — классов опасности в нём
    # нет, поэтому класс всегда «[требуется]», пока юзер не задаст его в
    # extra.air_inventory.hazard_classes = {"0301": "3", ...}
    try:
        from ecodoc.core import refdata
        ref_by_code = {str(x.get("code")): x for x in refdata.substances()}
    except Exception:  # справочник необязателен
        ref_by_code = {}
    classes = cfg(ctx).get("hazard_classes") or {}
    rows = []
    for r in substance_totals(ctx):
        pdk_kind, pdk = "[требуется: вид ПДК]", "[требуется]"
        ref = ref_by_code.get(r["code"]) or {}
        if ref.get("pdk_mr"):
            pdk_kind, pdk = "ПДК м/р", str(ref["pdk_mr"])
        elif ref.get("pdk_ss"):
            pdk_kind, pdk = "ПДК с/с", str(ref["pdk_ss"])
        elif ref.get("obuv"):
            pdk_kind, pdk = "ОБУВ", str(ref["obuv"])
        cls = str(classes.get(r["code"]) or ref.get("hazard_class") or "[требуется]")
        rows.append([r["code"], r["name"], pdk_kind, pdk, cls,
                     fmt(r["g_s"], 7) if r["g_s"] else "[требуется]",
                     fmt(r["t_year"]) if r["t_year"] else "[требуется]"])
    return rows


def rows_t31(ctx: ReportContext) -> list[list[str]]:
    """Табл. 3.1: источники выделения. Если ИВ не заданы отдельно — ИВ = ИЗАВ."""
    rows = []
    for s in sources(ctx):
        emitters = s["emitters"] or [{"number": s["number"], "name": s["name"]}]
        for e in emitters:
            subs = [p for p in (e.get("pollutants") or []) if isinstance(p, dict)] \
                or s["pollutants"]
            for i, p in enumerate(subs or [{}]):
                rows.append([
                    str(s["workshop"] or "1") if i == 0 else "",
                    str(_first(e, "workshop_name", default=cfg(ctx).get("workshop_name", "Площадка"))) if i == 0 else "",
                    str(s["site"] or "") if i == 0 else "",
                    str(_first(e, "site_name")) if i == 0 else "",
                    str(_first(e, "number", default=s["number"])) if i == 0 else "",
                    str(_first(e, "name", default=s["name"])) if i == 0 else "",
                    str(_first(e, "mode", default=s["mode"])) if i == 0 else "",
                    str(_first(e, "hours_day", default=s["hours_day"] or "[требуется]")) if i == 0 else "",
                    str(_first(e, "hours_year", default=s["hours_year"] or "[требуется]")) if i == 0 else "",
                    str(_first(e, "count", default=s["count"])) if i == 0 else "",
                    str(_first(p, "code")), str(_first(p, "name")),
                    fmt(_first(p, "g_s", "gs"), 7), fmt(_first(p, "t_year")),
                    str(_first(e, "gou", default=(s["gou"].get("inv_no", "") if isinstance(s["gou"], dict) else ""))),
                    s["number"], s["note"] if i == 0 else ""])
    return rows


def rows_t32(ctx: ReportContext) -> list[list[str]]:
    """Табл. 3.2: стационарные ИЗАВ — строка на каждое вещество источника."""
    rows = []
    for s in sources(ctx):
        req = "[требуется]"
        circle = s["diameter"] or (req if not s["length"] and "неорг" not in s["kind"] else "")
        for i, p in enumerate(s["pollutants"] or [{}]):
            head = [s["number"] or req, s["type"] or req, s["name"] or req,
                    str(s["count"]), fmt(s["height"], 2) or req,
                    fmt(circle, 2) or circle, fmt(s["length"], 2), fmt(s["width"], 2),
                    fmt(s["x1"], 2) or req, fmt(s["y1"], 2) or req,
                    fmt(s["x2"], 2) or ("0" if "неорг" not in s["kind"] else req),
                    fmt(s["y2"], 2) or ("0" if "неорг" not in s["kind"] else req),
                    fmt(s["area_width"], 2) or ("0" if "неорг" not in s["kind"] else req),
                    str(s["mode"]),
                    fmt(s["speed"], 2) or req, fmt(s["speed_v"], 2),
                    fmt(s["volume"], 6) or req, fmt(s["temperature"], 1) or req,
                    fmt(s["density"], 3)]
            if i:
                head = [""] * len(head)
            rows.append(head + [
                str(p.get("code", "")), str(p.get("name", "")),
                fmt(p.get("conc"), 5), fmt(p.get("g_s"), 7), fmt(p.get("t_year")),
                fmt(p.get("t_year")), s["note"] if i == 0 else ""])
    return rows


def rows_t36(ctx: ReportContext) -> list[list[str]]:
    """Табл. 3.6: ГОУ."""
    rows = []
    for i, g in enumerate(gou_list(ctx), start=1):
        subs = g.get("pollutants") or g.get("substances") or [""]
        for j, sub in enumerate(subs if isinstance(subs, list) else [subs]):
            rows.append([
                str(_first(g, "workshop", default="1")) if j == 0 else "",
                str(_first(g, "workshop_name", default="Площадка")) if j == 0 else "",
                str(_first(g, "site", default=str(i))) if j == 0 else "",
                str(_first(g, "emitter", "source")) if j == 0 else "",
                str(_first(g, "name", "type", default="[требуется: тип, марка, № в реестре]")) if j == 0 else "",
                str(_first(g, "izav")) if j == 0 else "",
                str(_first(g, "eff_design", "kpd_design", default="[требуется]")),
                str(_first(g, "eff_actual", "kpd_actual", "kpd", default="[требуется]")),
                str(sub) if isinstance(sub, str) else f"{sub.get('name', '')} ({sub.get('code', '')})",
                str(_first(g, "coef_norm", default="[требуется]")),
                str(_first(g, "coef_actual", default="[требуется]"))])
    return rows


def rows_t37(ctx: ReportContext) -> tuple[list[list[str]], list[list[str]]]:
    """Табл. 3.7: суммарные выбросы; возвращает (строки, итоги).

    Очистка: по веществу считаем «поступает на очистку» только если ГОУ с
    этим веществом заведена; иначе всё — без очистки (как в отчёте без ГОУ).
    """
    gou_by_code: dict[str, dict] = {}
    for g in gou_list(ctx):
        for sub in g.get("pollutants") or []:
            if isinstance(sub, dict) and sub.get("code"):
                gou_by_code[str(sub["code"])] = g
    rows, tot = [], {"all": [0.0] * 8, "solid": [0.0] * 8, "gas": [0.0] * 8}
    for r in substance_totals(ctx):
        out_t = r["t_year"]
        g = gou_by_code.get(r["code"])
        if g:
            eff = (_num(_first(g, "eff_actual", "kpd_actual", "kpd")) or 0.0) / 100.0
            incoming = out_t / (1 - eff) if eff < 1 else out_t
            caught = incoming - out_t
            vals = [incoming, 0.0, 0.0, incoming, caught, 0.0, out_t, out_t]
        else:
            vals = [out_t, out_t, r["t_org"], 0.0, 0.0, 0.0, 0.0, out_t]
        rows.append([r["code"], r["name"]] + [fmt(v) for v in vals])
        for key in ("all", "solid" if r["solid"] else "gas"):
            tot[key] = [a + b for a, b in zip(tot[key], vals)]
    totals = [["Всего:", ""] + [fmt(v) for v in tot["all"]],
              ["в т. ч. твердых:", ""] + [fmt(v) for v in tot["solid"]],
              ["в т. ч. жидких и газообразных:", ""] + [fmt(v) for v in tot["gas"]]]
    return rows, totals


def rows_t21(ctx: ReportContext) -> list[list[str]]:
    rows = []
    for i, m in enumerate(measurements(ctx), start=1):
        rows.append([str(i), str(_first(m, "date")), str(_first(m, "place", "source_name")),
                     str(_first(m, "izav", "number")), fmt(_first(m, "diameter"), 2),
                     fmt(_first(m, "speed"), 2), fmt(_first(m, "volume"), 4),
                     fmt(_first(m, "temperature"), 1), fmt(_first(m, "pressure"), 2),
                     fmt(_first(m, "humidity"), 2),
                     f"{_first(m, 'name')} ({_first(m, 'code')})",
                     str(_first(m, "method", default="[требуется: методика измерений]")),
                     fmt(_first(m, "conc"), 5), fmt(_first(m, "g_s_avg", "g_s"), 7),
                     fmt(_first(m, "g_s_max", "g_s"), 7)])
    return rows


def nonstationary_rows(ctx: ReportContext) -> dict[str, list[list[str]]]:
    """Табл. 1.1–1.3: если режимов нет — по одной строке-констатации (как в отчёте)."""
    c = cfg(ctx)
    if c.get("nonstationary"):
        ns = c["nonstationary"]
        return {"11": [[str(x) for x in r] for r in ns.get("modes", [])],
                "12": [[str(x) for x in r] for r in ns.get("simultaneity", [])],
                "13": [[str(x) for x in r] for r in ns.get("stages", [])]}
    return {"11": [["Нестационарность режимов работы ИЗАВ и их временных характеристик "
                    "отсутствует. Выброс ЗВ от ИЗАВ осуществляется одновременно."] + [""] * 5],
            "12": [["Одновременность выбросов отсутствует"] + [""] * 6],
            "13": [["Нестационарность выбросов отсутствует"] + [""] * 4]}


# ── генерация ────────────────────────────────────────────────────────────

def _sheet(wb, name: str, title: str, header: list[str], rows: list[list[str]],
           totals: list[list[str]] | None = None, width: int = 18):
    ws = wb.create_sheet(name)
    xlsx.merge(ws, f"A1:{chr(64 + min(len(header), 26))}1", title, bold=True, align="left")
    xlsx.header_row(ws, 2, header)
    xlsx.data_row(ws, 3, [str(i) for i in range(1, len(header) + 1)])  # номера граф
    r = 4
    for row in rows or [["[требуется: данные не заведены]"] + [""] * (len(header) - 1)]:
        xlsx.data_row(ws, r, row)
        r += 1
    for t in totals or []:
        xlsx.data_row(ws, r, t)
        r += 1
    for i in range(len(header)):
        ws.column_dimensions[ws.cell(row=2, column=i + 1).column_letter].width = width
    return ws


def generate(ctx: ReportContext, out_path: str | Path) -> Path:
    """Собрать отчёт об инвентаризации: .xlsx (таблицы) + .docx (текст) рядом.

    Возвращает путь к .xlsx (как раньше — GUI и тесты ждут его); .docx лежит
    рядом с тем же именем. Если передан путь .docx — наоборот.
    """
    out_path = Path(out_path)
    xlsx_path = out_path.with_suffix(".xlsx")
    docx_path = out_path.with_suffix(".docx")
    org = ctx.organization
    srcs, subs = sources(ctx), air_pollutants(ctx)
    wb = xlsx.new_workbook()

    # ── Титул (как раньше + реквизиты по разд. 1.1) ─────────────────────
    ws = wb.create_sheet("Титул")
    xlsx.merge(ws, "A1:F1", TITLE.upper(), bold=True, align="center")
    xlsx.merge(ws, "A2:F2", f"({NPA_SHORT}) за {ctx.period.year or '____'} год",
               align="center")
    obj = ctx.objects[0] if ctx.objects else None
    info = [("Организация", org.name or org.short_name), ("ИНН", org.inn),
            ("ОГРН", org.ogrn), ("ОКВЭД", org.okved), ("ОКПО", org.okpo),
            ("ОКТМО", org.oktmo or (obj.oktmo if obj else "")),
            ("Руководитель", org.director_name),
            ("Объект НВОС", ", ".join(o.code for o in ctx.objects) or "—"),
            ("Адрес объекта", "; ".join(o.address for o in ctx.objects if o.address) or "—"),
            ("Категория объекта", obj.category if obj else ""),
            ("Источников выбросов", str(len(srcs))),
            ("в т.ч. организованных", str(sum(1 for s in srcs if "неорг" not in s["kind"]))),
            ("Веществ", str(len(substance_totals(ctx)))),
            ("Разработчик", str(cfg(ctx).get("developer") or "[требуется]")),
            ("Дата инвентаризации", str(cfg(ctx).get("date") or "[требуется]"))]
    for i, (label, value) in enumerate(info, start=4):
        xlsx.cell(ws, f"A{i}", label, bold=True)
        xlsx.merge(ws, f"B{i}:F{i}", value or "—", align="left")
    xlsx.widths(ws, {"A": 26, "B": 26, "C": 18, "D": 18, "E": 18, "F": 18})

    # ── Лист «Источники» (совместимость с GUI/тестами) ───────────────────
    ws2 = wb.create_sheet("Источники")
    xlsx.header_row(ws2, 1, ["№ источника", "Наименование", "Тип",
                             "Вещества (код, наименование, г/с, т/год)",
                             "Откуда взято"])
    xlsx.widths(ws2, {"A": 14, "B": 38, "C": 18, "D": 56, "E": 26})
    for i, s in enumerate(srcs, start=2):
        subs_text = "; ".join(
            f"{p['code']} {p['name']}"
            f"{' — ' + str(p['g_s']) + ' г/с' if p['g_s'] else ''}"
            f"{', ' + str(p['t_year']) + ' т/год' if p['t_year'] else ''}"
            for p in s["pollutants"]) or "нет данных"
        xlsx.data_row(ws2, i, [s["number"] or "—", s["name"] or "—",
                               s["kind"] or "—", subs_text, s["src"] or "—"])

    # ── Лист «Вещества» (совместимость) ──────────────────────────────────
    ws3 = wb.create_sheet("Вещества")
    xlsx.header_row(ws3, 1, ["Код", "Вещество", "В пределах норматива, т/год",
                             "В пределах лимита, т/год", "Сверх лимита, т/год",
                             "Всего, т/год", "Источник данных"])
    xlsx.widths(ws3, {"A": 10, "B": 40, "C": 16, "D": 16, "E": 16, "F": 14, "G": 20})
    for i, p in enumerate(subs, start=2):
        xlsx.data_row(ws3, i, [p["code"] or "—", p["name"] or "—", p["norm"],
                               p["limit"], p["over"], p["total"], p["source"] or "—"])

    # ── Таблицы по приказу № 871 ─────────────────────────────────────────
    _sheet(wb, "Перечень ЗВ (табл.1)", "Таблица 1. Полный перечень загрязняющих "
           "веществ, выбрасываемых в атмосферу", T1_HEADER, rows_t1(ctx), width=22)
    _sheet(wb, "Табл.3.1 ИВ", T31_TITLE, T31_HEADER, rows_t31(ctx))
    _sheet(wb, "Табл.3.2 ИЗАВ", T32_TITLE, T32_HEADER, rows_t32(ctx), width=14)
    _sheet(wb, "Табл.3.6 ГОУ", T36_TITLE, T36_HEADER, rows_t36(ctx), width=20)
    t37, tot = rows_t37(ctx)
    _sheet(wb, "Табл.3.7 Суммарные", T37_TITLE, T37_HEADER, t37, tot, width=20)
    _sheet(wb, "Табл.2.1 Измерения", T21_TITLE, T21_HEADER, rows_t21(ctx), width=16)
    ns = nonstationary_rows(ctx)
    _sheet(wb, "Табл.1.1-1.3 Нестац", T11_TITLE, T11_HEADER, ns["11"], width=22)
    ws_ns = wb["Табл.1.1-1.3 Нестац"]
    r = ws_ns.max_row + 2
    xlsx.merge(ws_ns, f"A{r}:G{r}", T12_TITLE, bold=True, align="left")
    xlsx.header_row(ws_ns, r + 1, T12_HEADER)
    for i, row in enumerate(ns["12"], start=r + 2):
        xlsx.data_row(ws_ns, i, row)
    r = ws_ns.max_row + 2
    xlsx.merge(ws_ns, f"A{r}:E{r}", T13_TITLE, bold=True, align="left")
    xlsx.header_row(ws_ns, r + 1, T13_HEADER)
    for i, row in enumerate(ns["13"], start=r + 2):
        xlsx.data_row(ws_ns, i, row)

    ws4 = wb.create_sheet("Чего не хватает")
    xlsx.header_row(ws4, 1, ["Замечание"])
    xlsx.widths(ws4, {"A": 110})
    problems = gaps(ctx) or ["замечаний нет"]
    for i, text in enumerate(problems, start=2):
        xlsx.data_row(ws4, i, [text])

    xlsx.save(wb, xlsx_path)

    # ── текстовый отчёт .docx рядом ──────────────────────────────────────
    from ecodoc.development import air_inventory_docx
    air_inventory_docx.build(ctx, docx_path)
    return docx_path if out_path.suffix.lower() == ".docx" else xlsx_path
