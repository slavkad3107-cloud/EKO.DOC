"""Сведения в региональный кадастр отходов Санкт-Петербурга.

Печатная форма повторяет официальный бланк Комитета по природопользованию
СПб: Форма 1 (сведения о ЮЛ/ИП и объекте НВОС) + Форма 2 (места накопления) +
Форма 3 (движение отходов, 22 графы) + Форма 4 (объекты обработки/утилизации/
обезвреживания) + Форма 5 (уведомление о представлении сведений).

Основание — Распоряжение Комитета по природопользованию, охране окружающей
среды и обеспечению экологической безопасности СПб от 26.04.2023 № 87-р
(в ред. Распоряжения от 14.02.2025 № 28-р). Срок — не позднее 31 марта года,
следующего за отчётным, по каждому обособленному подразделению отдельно.
Каналы подачи: подсистема «Ведение регионального кадастра отходов» ГИС СПб
(с УКЭП); e-mail kadastr@kpoos.gov.spb.ru (документ с УКЭП, тема — ИНН и
наименование, Excel во вложении); либо бумажный прошитый экземпляр
(191123, СПб, ул. Чайковского, д. 20, лит. В). XML-выгрузки нет.
Места накопления — из ctx.extra['accumulation_sites']; объекты обработки —
из ctx.extra['treatment_objects'] (обычно отсутствуют, тогда строка «-»).
"""
from __future__ import annotations

from pathlib import Path

from openpyxl.utils import get_column_letter

from ecodoc.core.models import Issue
from ecodoc.core.money import D
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.reports.base import Report

_REGIONS = {"78", "47", "40", "41", "46"}  # СПб (78/40) и ЛО (47/41/46)


def _num(v) -> float:
    return float(D(v))


@register
class CadastreSPB(Report):
    code = "cadastre-spb"
    title = "Кадастр отходов (СПб)"
    has_xml = False  # сдаётся подписанным Excel, XML-выгрузки нет

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.wastes:
            issues.append(Issue("error", "отходы", "нет позиций отходов"))
        regions = {str(ob.region_code) for ob in self.ctx.objects if ob.region_code}
        if regions and not (regions & _REGIONS):
            issues.append(Issue("warning", "регион",
                                "объекты вне СПб/ЛО — проверьте, требуется ли региональный "
                                f"кадастр (коды: {', '.join(sorted(regions))})"))
        year_next = (self.ctx.period.year + 1) if self.ctx.period.year else "след."
        issues.append(Issue("warning", "срок",
                            f"срок подачи — не позднее 31 марта {year_next} по каждому "
                            "обособленному подразделению (Распоряжение Комитета по "
                            "природопользованию СПб № 87-р в ред. № 28-р); для ЛО/иных "
                            "регионов — сверьте свой НПА"))
        return issues

    def render_xml(self, out_path: Path) -> Path:  # pragma: no cover
        raise NotImplementedError("Кадастр СПб сдаётся подписанным Excel, XML нет")

    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        self._form1(wb)
        self._form2(wb)
        self._form3(wb)
        self._form4(wb)
        self._form5(wb)
        return xlsx.save(wb, out_path)

    # Форма 1 — сведения о ЮЛ/ИП и объекте НВОС ------------------------
    def _form1(self, wb):
        ws = wb.create_sheet("Форма 1")
        o = self.ctx.organization
        ob = self.ctx.objects[0] if self.ctx.objects else None
        xlsx.widths(ws, {"A": 2, "B": 6, "C": 48, "D": 55})
        xlsx.cell(ws, "D1", "Форма 1", border=False, bold=True, align="right")
        xlsx.cell(ws, "C3", "Сведения об индивидуальном предпринимателе/юридическом лице",
                  border=False, bold=True, align="left")
        xlsx.cell(ws, "B5", "1", bold=True)
        xlsx.merge(ws, "C5:D5",
                   "Общие сведения об индивидуальном предпринимателе, юридическом лице",
                   bold=True, fill=True, align="left")
        director = (f"{o.director_position}\n{o.director_name}".strip()
                    if o.director_name else o.director_position)
        rows1 = [
            ("1.1", "ИНН", o.inn),
            ("1.2", "ОГРН/ОГРНИП", o.ogrn),
            ("1.3", "Полное наименование", o.name),
            ("1.4", "Краткое (сокращенное) наименование", o.short_name or o.name),
            ("1.5", "Код ОКПО", o.okpo),
            ("1.6", "Адрес регистрации индивидуального предпринимателя, юридического лица",
             o.address),
            ("1.7", "Почтовый адрес", o.address),
            ("1.8", "Телефон", o.phone),
            ("1.9", "Факс", "-"),
            ("1.10", "Электронная почта", o.email),
            ("1.11", "Адрес интернет-сайта", "-"),
            ("1.12", "ФИО руководителя с указанием должности", director),
            ("1.13", "Коды ОКВЭД (основной и вспомогательные)", o.okved),
            ("1.14", "Должность, ФИО, номер телефона, адрес электронной почты "
                     "ответственного за представление сведений в кадастр",
             self._responsible()),
        ]
        r = 6
        for num, label, value in rows1:
            xlsx.cell(ws, f"B{r}", num)
            xlsx.cell(ws, f"C{r}", label, align="left")
            xlsx.cell(ws, f"D{r}", value or "", align="left")
            r += 1
        xlsx.cell(ws, f"B{r}", "2", bold=True)
        xlsx.merge(ws, f"C{r}:D{r}",
                   "Сведения об объекте, оказывающем негативное воздействие на окружающую среду",
                   bold=True, fill=True, align="left")
        r += 1
        rows2 = [
            ("2.1", "Код объекта, оказывающего негативное воздействие на окружающую среду",
             ob.code if ob else ""),
            ("2.2", "Адрес местонахождения объекта, оказывающего негативное воздействие "
                    "на окружающую среду", ob.address if ob else ""),
            ("2.3", "Код ОКТМО объекта, оказывающего негативное воздействие на окружающую среду",
             (ob.oktmo if ob else "") or o.oktmo),
        ]
        for num, label, value in rows2:
            xlsx.cell(ws, f"B{r}", num)
            xlsx.cell(ws, f"C{r}", label, align="left")
            xlsx.cell(ws, f"D{r}", value or "", align="left")
            r += 1

    # Форма 2 — места накопления --------------------------------------
    def _form2(self, wb):
        ws = wb.create_sheet("Форма 2")
        xlsx.widths(ws, {"A": 2, "B": 6, "C": 34, "D": 9, "E": 9, "F": 34, "G": 15,
                         "H": 9, "I": 20})
        xlsx.cell(ws, "I1", "Форма 2", border=False, bold=True, align="right")
        xlsx.cell(ws, "B3", "Сведения о местах накопления отходов",
                  border=False, bold=True, align="left")
        xlsx.merge(ws, "B5:B6", "№ п/п", bold=True, fill=True)
        xlsx.merge(ws, "C5:C6", "Краткое описание места накопления отходов", bold=True, fill=True)
        xlsx.merge(ws, "D5:E5", "Вместимость места накопления отходов", bold=True, fill=True)
        xlsx.cell(ws, "D6", "тонн", bold=True, fill=True, size=9)
        xlsx.cell(ws, "E6", "м3", bold=True, fill=True, size=9)
        xlsx.merge(ws, "F5:H5", "Перечень накапливаемых отходов", bold=True, fill=True)
        xlsx.cell(ws, "F6", "Наименование отхода по федеральному классификационному "
                            "каталогу отходов", bold=True, fill=True, size=9)
        xlsx.cell(ws, "G6", "Код отхода по федеральному классификационному каталогу отходов",
                  bold=True, fill=True, size=9)
        xlsx.cell(ws, "H6", "Класс опасности отхода", bold=True, fill=True, size=9)
        xlsx.merge(ws, "I5:I6", "Способ накопления (отдельно от других отходов/"
                                "в смеси с другими отходами)", bold=True, fill=True, size=9)
        for i, col in enumerate("BCDEFGHI"):
            xlsx.cell(ws, f"{col}7", i + 1, italic=True, size=9)
        sites = self._extra_list("accumulation_sites")
        r = 8
        if sites:
            for n, s in enumerate(sites, 1):
                xlsx.cell(ws, f"B{r}", n)
                xlsx.cell(ws, f"C{r}", s.get("description", ""), align="left")
                xlsx.cell(ws, f"D{r}", s.get("capacity_t", ""))
                xlsx.cell(ws, f"E{r}", s.get("capacity_m3", ""))
                xlsx.cell(ws, f"F{r}", s.get("waste_name", ""), align="left")
                xlsx.cell(ws, f"G{r}", s.get("fkko", ""))
                xlsx.cell(ws, f"H{r}", s.get("hazard_class", ""))
                xlsx.cell(ws, f"I{r}", s.get("method", "отдельно от других отходов"),
                          align="left")
                r += 1
        else:
            for i, col in enumerate("BCDEFGHI"):
                xlsx.cell(ws, f"{col}8", "…" if col == "C" else "")
        xlsx.heights(ws, {5: 30, 6: 40})

    # Форма 3 — движение отходов (22 графы) ---------------------------
    def _form3(self, wb):
        ws = wb.create_sheet("Форма 3")
        xlsx.cell(ws, "V5", "Форма 3", border=False, bold=True, align="right")
        xlsx.cell(ws, "A7", "Сведения о движении отходов", border=False, bold=True, align="left")
        # верхний ярус (row 9), спаны групп; single-колонки объединены до row 11
        xlsx.merge(ws, "A9:A11", "№ п/п", bold=True, fill=True)
        xlsx.merge(ws, "B9:B11", "Наименование отхода по федеральному классификационному "
                                 "каталогу отходов", bold=True, fill=True, size=9)
        xlsx.merge(ws, "C9:C11", "Код отхода по федеральному классификационному "
                                 "каталогу отходов", bold=True, fill=True, size=9)
        xlsx.merge(ws, "D9:D11", "Класс опасности отхода", bold=True, fill=True, size=9)
        xlsx.merge(ws, "E9:E11", "Наличие отходов на начало отчетного года, тонн",
                   bold=True, fill=True, size=9)
        xlsx.merge(ws, "F9:F11", "Образовано отходов за отчетный год, тонн",
                   bold=True, fill=True, size=9)
        xlsx.merge(ws, "G9:J9", "Поступило отходов от других хозяйствующих субъектов, тонн",
                   bold=True, fill=True, size=9)
        xlsx.merge(ws, "K9:L9", "Обработано отходов, тонн", bold=True, fill=True, size=9)
        xlsx.merge(ws, "M9:N9", "Утилизировано отходов, тонн", bold=True, fill=True, size=9)
        xlsx.merge(ws, "O9:P9", "Обезврежено отходов, тонн", bold=True, fill=True, size=9)
        xlsx.merge(ws, "Q9:Q11", "Передано региональному оператору по обращению с ТКО, тонн",
                   bold=True, fill=True, size=9)
        xlsx.merge(ws, "R9:U9", "Передано отходов другим хозяйствующим субъектам "
                                "(за исключением регионального оператора по обращению с ТКО), тонн",
                   bold=True, fill=True, size=9)
        xlsx.merge(ws, "V9:V11", "Наличие отходов на конец отчетного года, тонн",
                   bold=True, fill=True, size=9)
        # второй ярус (row 10, объединено до row 11 для подписей)
        sub = {
            "G": "всего", "H": "из них из других субъектов РФ",
            "I": "наименование субъекта РФ", "J": "цель поступления отходов",
            "K": "всего", "L": "из них поступивших из других субъектов РФ",
            "M": "всего", "N": "из них поступивших из других субъектов РФ",
            "O": "всего", "P": "из них поступивших из других субъектов РФ",
            "R": "всего", "S": "из них в другие субъекты РФ",
            "T": "наименование субъекта РФ", "U": "цель передачи отходов",
        }
        for col, label in sub.items():
            xlsx.merge(ws, f"{col}10:{col}11", label, bold=True, fill=True, size=8)
        for i in range(22):
            xlsx.cell(ws, f"{get_column_letter(i+1)}12", i + 1, italic=True, size=9)
        r = 13
        for n, w in enumerate(self.ctx.wastes, 1):
            recv = _num(D(w.transferred) - D(_tko(w)))
            vals = {
                "A": n, "B": w.name, "C": w.fkko_code, "D": w.hazard_class,
                "E": _num(w.accumulated_start), "F": _num(w.generated),
                "G": _num(w.received), "H": 0.0, "I": "", "J": "",
                "K": _num(w.processed), "L": 0.0, "M": _num(w.used), "N": 0.0,
                "O": _num(w.neutralized), "P": 0.0, "Q": _tko(w),
                "R": recv, "S": 0.0, "T": "", "U": "",
                "V": _num(w.accumulated_end),
            }
            for col, v in vals.items():
                xlsx.cell(ws, f"{col}{r}", v, align="left" if col in "BIJTU" else "center")
            r += 1
        xlsx.widths(ws, {"A": 5, "B": 30, "C": 15, "D": 8,
                         **{get_column_letter(i): 10 for i in range(5, 23)}})
        xlsx.heights(ws, {9: 40, 10: 40})

    # Форма 4 — объекты обработки/утилизации/обезвреживания ------------
    def _form4(self, wb):
        ws = wb.create_sheet("Форма 4")
        last = get_column_letter(27)
        xlsx.cell(ws, f"{last}1", "Форма 4", border=False, bold=True, align="right")
        xlsx.cell(ws, "A3", "Сведения об объекте обработки, утилизации, обезвреживания отходов",
                  border=False, bold=True, align="left")
        labels = [
            "№, п/п",
            "Код объекта в государственном реестре объектов, оказывающих негативное "
            "воздействие на окружающую среду",
            "Адрес места нахождения объекта обработки, утилизации, обезвреживания отходов "
            "(с указанием района Санкт-Петербурга)",
            "Кадастровый номер земельного участка",
            "Категория земель (вид разрешенного использования земельного участка)",
            "ИНН, наименование (ФИО), адрес, телефон, факс, интернет-сайт юридического лица/"
            "индивидуального предпринимателя, эксплуатирующего объект",
            "Дата выдачи, номер лицензии на деятельность по сбору, использованию, "
            "обезвреживанию, транспортированию, размещению отходов I-IV классов опасности",
            "Применение технологии (промышленное, опытно-промышленное, опытное, иное)",
            "Наименование технологии",
            "Наименование и реквизиты технической документации на технику/технологию",
            "Основной вывод заключения государственной экологической экспертизы по проекту "
            "технической документации",
            "Назначение технологии (обработка, утилизация, обезвреживание отходов)",
            "Краткая характеристика технологического процесса обработки, утилизации "
            "и (или) обезвреживания отходов",
            "Используемые установки: Наименование",
            "Используемые установки: Реквизиты технической документации (технические условия)",
            "Используемые установки: Наличие положительного заключения государственной "
            "экологической экспертизы",
            "Получение вторичной продукции (энергии): Наименование и код по ОКПД",
            "Получение вторичной продукции (энергии): Производительность (количество в год)",
            "ИНН, наименование (ФИО), адрес … разработчика (собственника) технологии",
            "Наименование обрабатываемых, утилизируемых и (или) обезвреживаемых отходов",
            "Код по ФККО обрабатываемых, утилизируемых и (или) обезвреживаемых отходов",
            "Класс опасности",
            "Количество отходов, обработанных, утилизированных и (или) обезвреженных "
            "за отчетный год, тонн",
            "Образование вторичных отходов: Наименование",
            "Образование вторичных отходов: Код по ФККО",
            "Образование вторичных отходов: Класс опасности",
            "Образование вторичных отходов: Образовано вторичных отходов за отчетный год, тонн",
        ]
        for i, label in enumerate(labels):
            col = get_column_letter(i + 1)
            xlsx.cell(ws, f"{col}5", label, bold=True, fill=True, size=8)
            xlsx.cell(ws, f"{col}6", i + 1, italic=True, size=9)
            ws.column_dimensions[col].width = 6 if i == 0 else 16
        objs = self._extra_list("treatment_objects")
        r = 7
        if objs:
            for n, obj in enumerate(objs, 1):
                xlsx.cell(ws, f"A{r}", n)
                for i in range(1, 27):
                    col = get_column_letter(i + 1)
                    xlsx.cell(ws, f"{col}{r}", obj.get(f"c{i+1}", ""), align="left", size=9)
                r += 1
        else:
            for i in range(27):
                xlsx.cell(ws, f"{get_column_letter(i+1)}7", "-")
        xlsx.heights(ws, {5: 90})

    # Форма 5 — уведомление -------------------------------------------
    def _form5(self, wb):
        ws = wb.create_sheet("Форма 5")
        o = self.ctx.organization
        year = self.ctx.period.year or ""
        xlsx.widths(ws, {"A": 10, "B": 12, "C": 12, "D": 8, "E": 10, "F": 12, "G": 10,
                         "H": 12, "I": 10})
        xlsx.cell(ws, "I1", "Форма 5", border=False, bold=True, align="right")
        for i, line in enumerate(["Председателю Комитета", "по природопользованию, охране",
                                  "окружающей среды и обеспечению",
                                  "экологической безопасности"]):
            xlsx.cell(ws, f"F{2+i}", line, border=False, align="left")
        xlsx.merge(ws, "A13:I13",
                   "Уведомление о представлении сведений в региональный кадастр отходов "
                   "производства и потребления в Санкт-Петербурге", border=False, bold=True)
        xlsx.merge(ws, "A15:I15",
                   f"     Направляю в Ваш адрес сведения в региональный кадастр отходов "
                   f"в Санкт-Петербурге за отчетный {year} год.", border=False, align="left")
        xlsx.cell(ws, "A16", "     Уникальный идентификационный номер: ",
                  border=False, align="left")
        xlsx.merge(ws, "A18:I18", "УИН, либо штрих код", border=False, italic=True,
                   size=9, align="left")
        xlsx.cell(ws, "A21", "     Достоверность представленных сведений подтверждаю.",
                  border=False, align="left")
        xlsx.merge(ws, "A23:I23",
                   "     Приложение: Сведения в региональный кадастр отходов "
                   "в Санкт-Петербурге на ______ л. в 1 экз.", border=False, align="left")
        xlsx.merge(ws, "A27:B27", "Руководитель", border=False, align="left")
        xlsx.merge(ws, "C27:E27", o.name or o.short_name, border=False, align="center")
        xlsx.cell(ws, "H27", o.director_name or "", border=False, align="center")
        xlsx.cell(ws, "C28", "(наименование организации)", border=False, italic=True, size=8)
        xlsx.cell(ws, "F28", "(подпись)", border=False, italic=True, size=8)
        xlsx.cell(ws, "H28", "(Ф.И.О.)", border=False, italic=True, size=8)
        xlsx.cell(ws, "B30", "М.П.", border=False)
        xlsx.cell(ws, "F30", "(дата)", border=False, italic=True, size=8)
        xlsx.cell(ws, "B31", "(при наличии).", border=False, italic=True, size=8)

    # --- вспомогательное ---
    def _responsible(self) -> str:
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        if e.get("responsible"):
            return str(e["responsible"])
        o = self.ctx.organization
        parts = [p for p in ["Эколог", o.director_name, o.phone, o.email] if p]
        return ", ".join(parts)

    def _extra_list(self, key: str) -> list[dict]:
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        v = e.get(key, [])
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _tko(w) -> float:
    """Масса, переданная региональному оператору ТКО (ФККО 7 33 100 01 72 4 и пр. ТКО)."""
    code = str(getattr(w, "fkko_code", "")).replace(" ", "")
    is_tko = code.startswith("733") or code.startswith("735")  # ТКО-группы ФККО
    return float(D(w.transferred)) if is_tko else 0.0
