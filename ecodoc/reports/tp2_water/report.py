"""Форма 2-ТП (водхоз) — сведения об использовании воды. Годовая, с первого
рабочего дня по 22 января года, следующего за отчётным. Код ОКУД 0609060.

ДЕЙСТВУЮЩАЯ форма — Приказ Росстата от 02.10.2024 № 445 (заменил № 815 от
27.12.2019). Адресат — территориальное Бассейновое водное управление (БВУ)
Росводресурсов; подача только электронно через Модуль респондента ИАС
«2-ТП (водхоз)» / ГИС ЦП «Вода» (НЕ в Росстат).

ВНИМАНИЕ: действующая форма требует в водоотведении коды и массы сброшенных
ЗВ (Прил. 5 к № 445) и коды-классификаторы (Прил. 1–4); текущая модель хранит
по выпуску только приёмник/качество/объём — раздел «Водоотведение» неполон.

Данные — из ctx.extra['water']:
  {
    "intake":   [{"name": "скважина №1", "type": "подземный",
                  "volume": 12.5}],           # забор воды, тыс. м³/год
    "discharge":[{"receiver": "р. Нева", "quality": "нормативно-чистые",
                  "volume": 8.0}],            # водоотведение, тыс. м³/год
    "recycled": 40.0,                          # оборотное/повторное, тыс. м³/год
    "used_own": 10.0                           # использовано на собств. нужды
  }
Все объёмы — в тыс. м³/год.
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

from ecodoc.core.models import Issue
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report

_QUALITY = ("нормативно-чистые", "нормативно-очищенные",
            "недостаточно-очищенные", "загрязнённые без очистки")


@register
class TP2Water(Report):
    code = "2tp-water"
    title = "2-ТП (водхоз)"

    def _water(self) -> dict:
        return self.ctx.extra.get("water", {}) or {}

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not o.okpo:
            issues.append(Issue("warning", "ОКПО", "для 2-ТП обязателен код ОКПО"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        w = self._water()
        if not w.get("intake") and not w.get("discharge"):
            issues.append(Issue("error", "водоучёт",
                                "нет данных водозабора/водоотведения "
                                "(заполните extra.water: intake/discharge)"))
        for d in w.get("discharge", []):
            q = d.get("quality", "")
            if q and q not in _QUALITY:
                issues.append(Issue("warning", "качество",
                                    f"категория качества «{q}» не из перечня: "
                                    f"{', '.join(_QUALITY)}"))
        return issues

    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        w = self._water()
        root = etree.Element("Форма2ТПВодхоз", version="0.2", ОКУД="0609060",
                             НПА="Приказ Росстата № 445 от 02.10.2024")
        org = el(root, "Респондент")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "ОКПО", o.okpo)
        el(org, "ОКТМО", o.oktmo)
        el(org, "Адрес", o.address)
        el(org, "Адресат", "территориальное Бассейновое водное управление "
                           "(Модуль респондента ИАС «2-ТП (водхоз)» / ГИС ЦП «Вода»)")
        el(root, "ОтчётныйГод", self.ctx.period.year)

        intk = el(root, "ЗаборВоды")
        for s in w.get("intake", []):
            x = el(intk, "Источник")
            el(x, "Наименование", s.get("name", ""))
            el(x, "Тип", s.get("type", ""))
            el(x, "Объём", float(D(s.get("volume", 0))))
        disc = el(root, "Водоотведение")
        for d in w.get("discharge", []):
            x = el(disc, "Выпуск")
            el(x, "Приёмник", d.get("receiver", ""))
            el(x, "Качество", d.get("quality", ""))
            el(x, "Объём", float(D(d.get("volume", 0))))
            # сброшенные ЗВ по выпуску (коды по Прил. 5 к Приказу № 445)
            for zv in d.get("pollutants", []):
                z = el(x, "ЗВ", код=str(zv.get("code", "")))
                el(z, "Наименование", zv.get("name", ""))
                el(z, "Масса", float(D(zv.get("mass", 0))))
        el(root, "ОборотнаяВода", float(D(w.get("recycled", 0))))
        el(root, "ПовторноПоследовательная", float(D(w.get("reused", 0))))
        el(root, "ИспользованоНаСобственныеНужды", float(D(w.get("used_own", 0))))
        write_tree(root, out_path)
        return out_path

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        w = self._water()
        wb = xlsx.new_workbook()

        ws = wb.create_sheet("Забор воды")
        xlsx.header_row(ws, 1, ["Источник", "Тип", "Объём, тыс. м³/год"],
                        widths=[32, 20, 18])
        r = 2
        for s in w.get("intake", []):
            xlsx.data_row(ws, r, [s.get("name", ""), s.get("type", ""),
                                  float(D(s.get("volume", 0)))]); r += 1
        total_in = sum((D(s.get("volume", 0)) for s in w.get("intake", [])), D(0))
        xlsx.data_row(ws, r, ["ИТОГО забрано", "", float(total_in)])
        for c in range(1, 4):
            ws.cell(row=r, column=c).font = xlsx.BOLD

        ws2 = wb.create_sheet("Водоотведение")
        xlsx.header_row(ws2, 1, ["Приёмник", "Категория качества",
                                 "Объём, тыс. м³/год"], widths=[32, 26, 18])
        r = 2
        for d in w.get("discharge", []):
            xlsx.data_row(ws2, r, [d.get("receiver", ""), d.get("quality", ""),
                                   float(D(d.get("volume", 0)))]); r += 1
        total_out = sum((D(d.get("volume", 0)) for d in w.get("discharge", [])), D(0))
        xlsx.data_row(ws2, r, ["ИТОГО отведено", "", float(total_out)])
        for c in range(1, 4):
            ws2.cell(row=r, column=c).font = xlsx.BOLD
        # сброшенные ЗВ по выпускам (Приложение 5 к Приказу № 445)
        zvs = [(d, zv) for d in w.get("discharge", []) for zv in d.get("pollutants", [])]
        if zvs:
            r += 2
            xlsx.cell(ws2, f"A{r}", "Сброшенные загрязняющие вещества по выпускам:",
                      border=False, bold=True, align="left"); r += 1
            xlsx.header_row(ws2, r, ["Выпуск (приёмник)", "Код ЗВ / наименование",
                                     "Масса, т/год"]); r += 1
            for d, zv in zvs:
                xlsx.data_row(ws2, r, [d.get("receiver", ""),
                                       f"{zv.get('code','')} {zv.get('name','')}".strip(),
                                       float(D(zv.get("mass", 0)))]); r += 1

        ws3 = wb.create_sheet("Сводка")
        xlsx.header_row(ws3, 1, ["Показатель", "Значение, тыс. м³/год"],
                        widths=[40, 20])
        xlsx.data_row(ws3, 2, ["Забрано воды, всего", float(total_in)])
        xlsx.data_row(ws3, 3, ["Отведено (сброшено), всего", float(total_out)])
        xlsx.data_row(ws3, 4, ["Оборотное водоснабжение",
                               float(D(w.get("recycled", 0)))])
        xlsx.data_row(ws3, 5, ["Повторно-последовательное водоснабжение",
                               float(D(w.get("reused", 0)))])
        xlsx.data_row(ws3, 6, ["Использовано на собственные нужды",
                               float(D(w.get("used_own", 0)))])
        xlsx.data_row(ws3, 8, ["Форма / ОКУД", "2-ТП (водхоз) / 0609060"])
        xlsx.data_row(ws3, 9, ["Основание", "Приказ Росстата № 445 от 02.10.2024"])
        xlsx.data_row(ws3, 10, ["Адресат", "территориальное Бассейновое водное "
                                "управление (Модуль респондента / ГИС ЦП «Вода»)"])
        xlsx.data_row(ws3, 11, ["Срок (за 2025)", "с первого рабочего дня по 22.01.2026"])
        return xlsx.save(wb, out_path)
