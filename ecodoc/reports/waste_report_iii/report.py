"""Отчётность об образовании, утилизации, обезвреживании и размещении отходов
(объекты III категории / субъекты МСП).

ВНИМАНИЕ по НПА: прежний федеральный Приказ Минприроды № 30 от 16.02.2010
УТРАТИЛ СИЛУ с 01.01.2021 (регуляторная гильотина). Отдельной действующей
ФЕДЕРАЛЬНОЙ формы больше нет: для объектов III категории (федеральный надзор)
эти сведения об отходах подаются В СОСТАВЕ отчёта ПЭК (Приказ № 109 от
18.02.2022, форма — Приказ № 173 от 15.03.2024), срок — до 25 марта. Для МСП
на объектах РЕГИОНАЛЬНОГО надзора действуют региональные уведомительные
порядки (СПб/ЛО и др.) со своими сроками. Приказ № 1028 — это Порядок УЧЁТА
(журнал), а не форма отчётности.

Текущий генератор строит самостоятельный упрощённый отчёт (баланс без остатков
на начало/конец и без разбивки передачи) — служит промежуточным/справочным
документом; для официальной подачи ориентируйтесь на раздел отходов отчёта ПЭК
либо на региональный формат.

Данные — из ctx.wastes; получатели отходов — ctx.extra['waste_receivers']:
    [{"fkko": "40211001515", "receiver": "ООО ...", "inn": "...",
      "license": "№... от ...", "operation": "передача на размещение"}, ...]
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


@register
class WasteReportIII(Report):
    code = "waste-report-iii"
    title = "Отчётность об образовании/утилизации отходов (III кат./МСП)"

    def _receivers(self) -> list[dict]:
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        return e.get("waste_receivers", [])

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        if not self.ctx.organization.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.wastes:
            issues.append(Issue("error", "отходы", "нет позиций отходов"))
        transferred = {w.fkko_code for w in self.ctx.wastes if D(w.transferred) > 0}
        with_recv = {r.get("fkko") for r in self._receivers()}
        missing = transferred - with_recv
        if missing:
            issues.append(Issue("warning", "получатели",
                                "для переданных отходов не указаны получатели "
                                f"(extra.waste_receivers): {', '.join(sorted(missing))}"))
        if not self.ctx.objects:
            issues.append(Issue("warning", "объект",
                                "не указан объект НВОС — отчётность привязывается к "
                                "объекту (код, категория, ОКТМО)"))
        for w in self.ctx.wastes:
            bal = (D(w.accumulated_start) + D(w.generated) + D(w.received)
                   - D(w.used) - D(w.neutralized) - D(w.transferred)
                   - D(w.placed_norm) - D(w.placed_over))
            if abs(bal - D(w.accumulated_end)) > D("0.001"):
                issues.append(Issue("warning", f"баланс/{w.fkko_code}",
                                    f"наличие на конец {D(w.accumulated_end)} ≠ баланс {bal}"))
        return issues

    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        root = etree.Element("ОтчётностьОтходыIII", version="0.2")
        org = el(root, "Организация")
        el(org, "Наименование", o.name)
        el(org, "ИНН", o.inn)
        el(org, "ОГРН", o.ogrn)
        el(org, "ОКПО", o.okpo)
        el(org, "ОКТМО", o.oktmo)
        for ob in self.ctx.objects:
            x = el(org, "ОбъектНВОС", код=ob.code)
            el(x, "Категория", ob.category)
            el(x, "Адрес", ob.address)
            el(x, "ОКТМО", ob.oktmo or o.oktmo)
        el(root, "ОтчётныйГод", self.ctx.period.year)
        items = el(root, "Отходы")
        for w in self.ctx.wastes:
            x = el(items, "Отход", фкко=w.fkko_code, класс=w.hazard_class)
            el(x, "Наименование", w.name)
            el(x, "НаличиеНачало", D(w.accumulated_start))
            el(x, "Образовано", D(w.generated))
            el(x, "Поступило", D(w.received))
            el(x, "Утилизировано", D(w.used))
            el(x, "Обезврежено", D(w.neutralized))
            el(x, "Передано", D(w.transferred))
            el(x, "Размещено", D(w.placed_norm) + D(w.placed_over))
            el(x, "НаличиеКонец", D(w.accumulated_end))
        recv = el(root, "Получатели")
        for r in self._receivers():
            x = el(recv, "Получатель", фкко=r.get("fkko", ""))
            el(x, "Наименование", r.get("receiver", ""))
            el(x, "ИНН", r.get("inn", ""))
            el(x, "Лицензия", r.get("license", ""))
            el(x, "Операция", r.get("operation", ""))
        write_tree(root, out_path)
        return out_path

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        self._general(wb)
        self._movement(wb)
        self._receivers_sheet(wb)
        return xlsx.save(wb, out_path)

    def _general(self, wb):
        """Раздел 1 — общие сведения о субъекте и объекте НВОС."""
        o = self.ctx.organization
        ws = wb.create_sheet("Общие сведения")
        ws.column_dimensions["A"].width = 40
        ws.column_dimensions["B"].width = 56
        ob = self.ctx.objects[0] if self.ctx.objects else None
        rows = [
            ("ОТЧЁТНОСТЬ ОБ ОБРАЗОВАНИИ, УТИЛИЗАЦИИ, ОБЕЗВРЕЖИВАНИИ, "
             "РАЗМЕЩЕНИИ ОТХОДОВ", ""),
            ("Отчётный год", self.ctx.period.year),
            ("Полное наименование", o.name),
            ("Сокращённое наименование", o.short_name or o.name),
            ("ИНН / ОГРН / ОКПО", f"{o.inn} / {o.ogrn} / {o.okpo}"),
            ("ОКВЭД / ОКТМО", f"{o.okved} / {o.oktmo}"),
            ("Юридический адрес", o.address),
            ("Телефон / e-mail", f"{o.phone} / {o.email}"),
            ("Объект НВОС (код / категория)",
             f"{ob.code} / {ob.category}" if ob else "— не указан"),
            ("Адрес объекта / ОКТМО", f"{ob.address} / {ob.oktmo}" if ob else "—"),
            ("Руководитель", f"{o.director_position} {o.director_name}".strip()),
        ]
        for i, (k, v) in enumerate(rows, 1):
            a = ws.cell(row=i, column=1, value=k)
            ws.cell(row=i, column=2, value=v)
            if i == 1:
                a.font = xlsx.BOLD

    def _movement(self, wb):
        """Раздел 2 — движение отходов (полный баланс масс)."""
        ws = wb.create_sheet("Движение отходов")
        xlsx.header_row(ws, 1, ["ФККО", "Наименование", "Кл.", "Нач. года, т",
                                "Образовано, т", "Поступило, т", "Утилизир., т",
                                "Обезвр., т", "Передано, т", "Размещено, т",
                                "Кон. года, т"],
                        widths=[14, 30, 5, 12, 12, 12, 11, 11, 11, 11, 12])
        r = 2
        for w in self.ctx.wastes:
            xlsx.data_row(ws, r, [
                w.fkko_code, w.name, w.hazard_class,
                float(D(w.accumulated_start)), float(D(w.generated)),
                float(D(w.received)), float(D(w.used)), float(D(w.neutralized)),
                float(D(w.transferred)),
                float(D(w.placed_norm) + D(w.placed_over)),
                float(D(w.accumulated_end))])
            r += 1

    def _receivers_sheet(self, wb):
        ws2 = wb.create_sheet("Получатели")
        xlsx.header_row(ws2, 1, ["ФККО", "Получатель", "ИНН", "Лицензия", "Операция"],
                        widths=[14, 34, 14, 26, 24])
        r = 2
        for rec in self._receivers():
            xlsx.data_row(ws2, r, [rec.get("fkko", ""), rec.get("receiver", ""),
                                   rec.get("inn", ""), rec.get("license", ""),
                                   rec.get("operation", "")])
            r += 1
