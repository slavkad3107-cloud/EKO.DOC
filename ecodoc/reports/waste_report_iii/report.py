"""Справка о движении отходов за год — данные для раздела 4 отчёта ПЭК.

ПРАВОВОЙ СТАТУС (почему это «справка», а не «форма отчётности»):
отдельной формы «отчётность об образовании, утилизации, обезвреживании,
размещении отходов для III категории / МСП» в законодательстве НЕТ.
Единственная когда-либо существовавшая отдельная форма — Приказ Минприроды
№ 30 от 16.02.2010 — отменена с 01.01.2021 (ПП РФ от 18.09.2020 № 1496),
а для МСП регионального надзора не применялась уже с 01.01.2016. С 01.01.2019
п. 7 ст. 18 ФЗ-89 «Об отходах производства и потребления» требует от ЮЛ и ИП
на объектах III категории представлять эти сведения В СОСТАВЕ отчёта об
организации и о результатах ПЭК (форма — Приказ Минприроды № 173 от
15.03.2024 в ред. № 262 от 12.05.2025; таблицы 4.2 и 4.3 раздела 4), срок —
до 25 марта. Адресат — РПН (федеральный надзор) или орган субъекта РФ
(региональный надзор) — в обоих случаях это тот же отчёт ПЭК. Критерий «МСП»
из закона исключён; «регионального уведомительного порядка МСП» с 2019 г. нет.

Поэтому ОТДЕЛЬНОЙ ПОДАЧИ У ЭТОГО ДОКУМЕНТА НЕТ: это рабочая справка, листы
которой повторяют шапки таблиц 4.2 (21 графа) и 4.3 (12 граф) отчёта ПЭК —
чтобы цифры переносились в раздел 4 отчёта ПЭК (форма с кодом «pek») один к
одному. XML — внутренний формат программы, ЛКПП его не принимает.

Шапки таблиц скопированы с принятого отчёта ПЭК (эталон пользователя
OneDrive/Формы/Отчетность/ОТчет ПЭК/Otcet-o-PEK_6303183.docx): в нём табл. 4.2
ещё на 23 графы (прежняя ред.), в действующей ред. № 173 граф «хранение/
захоронение на сторонних ОРО» нет — печатаем 21 графу действующей редакции.

Данные — из ctx.wastes; контрагенты — ctx.extra['waste_receivers']:
    [{"fkko": "40211001515", "receiver": "ООО ...", "inn": "...",
      "address": "...", "operation": "передача на захоронение",
      "mass": "1.5", "license": "№... от ..."}, ...]
«mass» относится к массе, переданной контрагенту по цели «operation»
(графы 8–12 табл. 4.3); «license» в табл. 4.3 не печатается — такой графы
в форме № 173 нет, реквизит остаётся только в XML.
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


def _dash(v) -> str:
    """Пустой реквизит печатаем как «—», а не как пустую строку/« / »:
    в справочном документе пустое поле выглядело заполненным (находка [6])."""
    s = "" if v is None else str(v).strip()
    return s or "—"


def _pair(a, b, sep: str = " / ") -> str:
    return f"{_dash(a)}{sep}{_dash(b)}"


# Графы 12–16 табл. 4.2 / 8–12 табл. 4.3: цель передачи → поле WasteFlow.
# Ключевые слова соответствуют формулировкам формы № 173 («обработка,
# утилизация, обезвреживание, хранение, захоронение»).
_PURPOSE_KEYS = (
    ("обработ", "transferred_processing"),
    ("утилиз", "transferred_util"),
    ("обезвре", "transferred_neutral"),
    ("хранен", "transferred_storage"),
    ("захорон", "transferred_burial"),
)


def _purpose_of(operation: str) -> str | None:
    """Определить цель передачи по свободному тексту «operation» получателя."""
    op = (operation or "").lower()
    for key, field in _PURPOSE_KEYS:
        if key in op:
            return field
    # «размещение» без уточнения: по ФЗ-89 размещение = хранение + захоронение;
    # без уточнения относим к захоронению (типичный случай передачи на полигон)
    if "размещ" in op:
        return "transferred_burial"
    return None


@register
class WasteReportIII(Report):
    code = "waste-report-iii"
    title = "Справка о движении отходов за год (данные для раздела 4 отчёта ПЭК)"

    def _receivers(self) -> list[dict]:
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        return e.get("waste_receivers", [])

    def validate(self) -> list[Issue]:
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.wastes:
            issues.append(Issue("error", "отходы", "нет позиций отходов"))
        if not (o.director_name or "").strip():
            issues.append(Issue("warning", "руководитель",
                                "не указан руководитель (ФИО) — в справке "
                                "печатается «—»"))
        transferred = {w.fkko_code for w in self.ctx.wastes if D(w.transferred) > 0}
        with_recv = {r.get("fkko") for r in self._receivers()}
        missing = transferred - with_recv
        if missing:
            issues.append(Issue("warning", "получатели",
                                "для переданных отходов не указаны получатели "
                                f"(extra.waste_receivers): {', '.join(sorted(missing))}"))
        if not self.ctx.objects:
            issues.append(Issue("warning", "объект",
                                "не указан объект НВОС — сведения раздела 4 отчёта "
                                "ПЭК привязываются к объекту (код, категория, ОКТМО)"))
        for w in self.ctx.wastes:
            # Приход по табл. 4.2 ПЭК = наличие на начало (гр.5 хранение +
            # гр.6 накопление) + образовано + получено — без accumulated_start_nakopl
            # баланс ложно «не сходился» на согласованных данных.
            bal = (D(w.accumulated_start) + D(w.accumulated_start_nakopl)
                   + D(w.generated) + D(w.received)
                   - D(w.used) - D(w.neutralized) - D(w.transferred)
                   - D(w.placed_norm) - D(w.placed_over))
            end = D(w.accumulated_end) + D(w.accumulated_end_nakopl)
            if abs(bal - end) > D("0.001"):
                issues.append(Issue("warning", f"баланс/{w.fkko_code}",
                                    f"наличие на конец {end} ≠ баланс {bal}"))
        return issues

    # ------------------------------------------------------------------ XML
    def render_xml(self, out_path: Path) -> Path:
        """Внутренний XML программы (не конверт ЛКПП — такой схемы для этих
        сведений не существует; в ЛКПП подаётся только отчёт ПЭК)."""
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        root = etree.Element("СправкаДвижениеОтходов", version="0.4",
                             назначение="раздел 4 отчёта ПЭК (Приказ № 173)")
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
            # наличие на начало/конец года раздельно, как графы 5/6 и 20/21
            # табл. 4.2: «хранение» и «накопление» — разные правовые режимы
            el(x, "НаличиеНачалоХранение", D(w.accumulated_start))
            el(x, "НаличиеНачалоНакопление", D(w.accumulated_start_nakopl))
            el(x, "Образовано", D(w.generated))
            el(x, "Поступило", D(w.received))
            el(x, "Утилизировано", D(w.used))
            el(x, "Обезврежено", D(w.neutralized))
            p = el(x, "Передано", всего=D(w.transferred))
            el(p, "Обработка", D(w.transferred_processing))
            el(p, "Утилизация", D(w.transferred_util))
            el(p, "Обезвреживание", D(w.transferred_neutral))
            el(p, "Хранение", D(w.transferred_storage))
            el(p, "Захоронение", D(w.transferred_burial))
            r = el(x, "Размещено", всего=D(w.placed_norm) + D(w.placed_over))
            el(r, "ХранениеСобственныеОРО", D(w.placed_storage))
            el(r, "ЗахоронениеСобственныеОРО", D(w.placed_burial))
            el(x, "НаличиеКонец", D(w.accumulated_end))
            el(x, "НаличиеКонецНакопление", D(w.accumulated_end_nakopl))
        recv = el(root, "Получатели")
        for rec in self._receivers():
            x = el(recv, "Получатель", фкко=rec.get("fkko", ""))
            el(x, "Наименование", rec.get("receiver", ""))
            el(x, "ИНН", rec.get("inn", ""))
            el(x, "Адрес", rec.get("address", ""))
            el(x, "Лицензия", rec.get("license", ""))
            el(x, "Операция", rec.get("operation", ""))
            el(x, "Масса", rec.get("mass", ""))
        write_tree(root, out_path)
        return out_path

    # ---------------------------------------------------------------- XLSX
    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        self._general(wb)
        self._movement(wb)
        self._receivers_sheet(wb)
        return xlsx.save(wb, out_path)

    def _general(self, wb):
        """Лист 1 — общие сведения о субъекте и объекте НВОС + правовой статус."""
        o = self.ctx.organization
        ws = wb.create_sheet("Общие сведения")
        ws.column_dimensions["A"].width = 40
        ws.column_dimensions["B"].width = 56
        ob = self.ctx.objects[0] if self.ctx.objects else None
        director = " ".join(s for s in (o.director_position, o.director_name)
                            if s and str(s).strip()).strip()
        rows = [
            ("СПРАВКА О ДВИЖЕНИИ ОТХОДОВ ЗА ГОД "
             "(данные для раздела 4 отчёта ПЭК)", ""),
            ("⚠ Отдельной подачи у этого документа НЕТ. Отдельной формы "
             "отчётности об отходах для III категории / МСП в законодательстве "
             "не существует: приказ Минприроды № 30 отменён с 01.01.2021.", ""),
            ("п. 7 ст. 18 ФЗ-89: объекты III категории представляют эти сведения "
             "В СОСТАВЕ отчёта ПЭК (приказ Минприроды от 15.03.2024 № 173 "
             "ред. 12.05.2025, таблицы 4.2 и 4.3), срок — до 25 марта.", ""),
            ("Региональный надзор — тот же отчёт ПЭК в орган субъекта РФ. "
             "Перенесите листы «Движение отходов» и «Получатели» в раздел 4 "
             "отчёта ПЭК (форма «pek»).", ""),
            ("", ""),
            ("Отчётный год", _dash(self.ctx.period.year)),
            ("Полное наименование", _dash(o.name)),
            ("Сокращённое наименование", _dash(o.short_name or o.name)),
            ("ИНН / ОГРН / ОКПО",
             f"{_dash(o.inn)} / {_dash(o.ogrn)} / {_dash(o.okpo)}"),
            ("ОКВЭД / ОКТМО", _pair(o.okved, o.oktmo)),
            ("Юридический адрес", _dash(o.address)),
            ("Телефон / e-mail", _pair(o.phone, o.email)),
            ("Объект НВОС (код / категория)",
             _pair(ob.code, ob.category) if ob else "— не указан"),
            ("Адрес объекта / ОКТМО", _pair(ob.address, ob.oktmo) if ob else "—"),
            # без ФИО печатать одну должность нельзя — поле выглядит
            # заполненным (находка [6]); либо целиком, либо «—»
            ("Руководитель",
             director if (o.director_name or "").strip() else "—"),
        ]
        for i, (k, v) in enumerate(rows, 1):
            a = ws.cell(row=i, column=1, value=k)
            ws.cell(row=i, column=2, value=v)
            if i == 1:
                a.font = xlsx.BOLD

    # Шапка таблицы 4.2 (21 графа действующей ред. № 173) — дословно по
    # эталону Otcet-o-PEK_6303183.docx. Ярус 1: (диапазон, текст); ярус 2 —
    # подграфы объединённых групп.
    _T42_TITLE = ("Таблица 4.2. Сведения об образовании, утилизации, "
                  "обезвреживании, размещении отходов производства и "
                  "потребления за отчетный год {year}")
    _T42_TOP = [
        ("A", "A", "N строки"),
        ("B", "B", "Наименование видов отходов"),
        ("C", "C", "Код по федеральному классификационному каталогу отходов, "
                   "далее - ФККО"),
        ("D", "D", "Класс опасности отходов"),
        ("E", "F", "Наличие отходов на начало года, тонн"),
        ("G", "G", "Образовано отходов, тонн"),
        ("H", "H", "Получено отходов от других индивидуальных предпринимателей "
                   "и юридических лиц, тонн"),
        ("I", "I", "Утилизировано отходов, тонн"),
        ("J", "J", "Обезврежено отходов, тонн"),
        ("K", "P", "Передано отходов другим индивидуальным предпринимателям "
                   "и юридическим лицам, тонн"),
        ("Q", "S", "Размещено отходов на эксплуатируемых объектах, тонн"),
        ("T", "U", "Наличие отходов на конец года, тонн"),
    ]
    _T42_SUB = {
        "E": "Хранение", "F": "Накопление",
        "K": "Всего", "L": "для обработки", "M": "для утилизации",
        "N": "для обезвреживания", "O": "для хранения", "P": "для захоронения",
        "Q": "Всего",
        "R": "Хранение на собственных объектах размещения отходов, далее - ОРО",
        "S": "Захоронение на собственных ОРО",
        "T": "Хранение", "U": "Накопление",
    }

    def _movement(self, wb):
        """Лист 2 — таблица 4.2 отчёта ПЭК (21 графа, двухъярусная шапка).

        Почему именно так: это единственная действующая форма для этих
        сведений; раньше лист печатал 12 сокращённых граф и терял разбивку
        передачи по целям (гр. 12–16), размещения по видам (гр. 18–19) и
        наличие на конец года хранение/накопление (гр. 20–21) — хотя данные
        в WasteFlow есть (находка [3]).
        """
        ws = wb.create_sheet("Движение отходов")
        cols = "ABCDEFGHIJKLMNOPQRSTU"
        xlsx.merge(ws, "A1:U1", self._T42_TITLE.format(year=self.ctx.period.year),
                   bold=True, align="left", border=False)
        for c1, c2, text in self._T42_TOP:
            if c1 == c2:
                # одиночная графа — объединяем по вертикали на оба яруса
                xlsx.merge(ws, f"{c1}2:{c1}3", text, bold=True, fill=True)
            else:
                xlsx.merge(ws, f"{c1}2:{c2}2", text, bold=True, fill=True)
        for col, text in self._T42_SUB.items():
            xlsx.cell(ws, f"{col}3", text, bold=True, fill=True)
        for i, col in enumerate(cols, 1):
            xlsx.cell(ws, f"{col}4", i, italic=True)  # строка нумерации граф
        xlsx.widths(ws, {"A": 6, "B": 34, "C": 16, "D": 8, "E": 10, "F": 10,
                         "G": 11, "H": 12, "I": 11, "J": 11, "K": 10, "L": 10,
                         "M": 10, "N": 11, "O": 10, "P": 10, "Q": 10, "R": 14,
                         "S": 13, "T": 10, "U": 10})
        xlsx.heights(ws, {2: 75, 3: 60})
        r = 5
        for n, w in enumerate(self.ctx.wastes, 1):
            xlsx.data_row(ws, r, [
                n, w.name, w.fkko_code, w.hazard_class,
                float(D(w.accumulated_start)),
                float(D(w.accumulated_start_nakopl)),
                float(D(w.generated)),
                float(D(w.received)), float(D(w.used)), float(D(w.neutralized)),
                float(D(w.transferred)),
                float(D(w.transferred_processing)),
                float(D(w.transferred_util)),
                float(D(w.transferred_neutral)),
                float(D(w.transferred_storage)),
                float(D(w.transferred_burial)),
                # гр. 17 «Всего» размещено = в пределах + сверх лимита
                float(D(w.placed_norm) + D(w.placed_over)),
                float(D(w.placed_storage)),
                float(D(w.placed_burial)),
                float(D(w.accumulated_end)),
                float(D(w.accumulated_end_nakopl))])
            r += 1

    # Шапка таблицы 4.3 (12 граф) — дословно по эталону.
    _T43_TITLE = ("Таблица 4.3. Сведения о юридических лицах и индивидуальных "
                  "предпринимателях, от которых получены и (или) которым "
                  "переданы отходы")
    _T43_PARTY = ("Наименование, ИНН, адрес в пределах места нахождения для "
                  "юридических лиц; фамилия, имя, отчество (при наличии), ИНН, "
                  "место жительства для физических лиц")

    def _receivers_sheet(self, wb):
        """Лист 3 — таблица 4.3 отчёта ПЭК (12 граф, трёхъярусная шапка).

        Масса по цели передачи (гр. 8–12) берётся из waste_receivers.mass и
        раскладывается по «operation»; графы 4–6 (полученные отходы) у
        типичного образователя пусты — получение отходов от других лиц
        в ctx.extra не ведётся, печатаем «—» (находка [4]).
        """
        ws = wb.create_sheet("Получатели")
        xlsx.merge(ws, "A1:L1", self._T43_TITLE, bold=True, align="left", border=False)
        top = [
            ("A", "A", "Номер строки"),
            ("B", "B", "Наименование видов отходов"),
            ("C", "C", "Код отхода по ФККО"),
            ("D", "D", self._T43_PARTY),
            ("E", "E", "Получено отходов, т"),
            ("F", "F", "Цель приема отходов (обработка, утилизация, "
                       "обезвреживание, хранение, захоронение)"),
            ("G", "G", self._T43_PARTY),
            ("H", "L", "Количество отходов, переданных индивидуальным "
                       "предпринимателям и юридическим лицам"),
        ]
        for c1, c2, text in top:
            if c1 == c2:
                xlsx.merge(ws, f"{c1}2:{c1}4", text, bold=True, fill=True)
            else:
                xlsx.merge(ws, f"{c1}2:{c2}2", text, bold=True, fill=True)
        # ярус 2–3 группы «Количество… переданных»
        xlsx.merge(ws, "H3:H4", "Для обработки", bold=True, fill=True)
        xlsx.merge(ws, "I3:I4", "Для утилизации", bold=True, fill=True)
        xlsx.merge(ws, "J3:J4", "Для обезвреживания", bold=True, fill=True)
        xlsx.merge(ws, "K3:L3", "Для размещения", bold=True, fill=True)
        xlsx.cell(ws, "K4", "хранение", bold=True, fill=True)
        xlsx.cell(ws, "L4", "захоронение", bold=True, fill=True)
        # Граф ровно 12 — как в эталоне и в действующей форме № 173
        # (итоговой графы «Всего» у табл. 4.3 нет, не выдумываем).
        for i, col in enumerate("ABCDEFGHIJKL", 1):
            xlsx.cell(ws, f"{col}5", i, italic=True)
        xlsx.widths(ws, {"A": 7, "B": 30, "C": 15, "D": 34, "E": 10, "F": 16,
                         "G": 34, "H": 10, "I": 10, "J": 11, "K": 10, "L": 11})
        xlsx.heights(ws, {2: 70, 3: 30, 4: 30})
        names = {w.fkko_code: w.name for w in self.ctx.wastes}
        r = 6
        for n, rec in enumerate(self._receivers(), 1):
            fkko = rec.get("fkko", "")
            party = ", ".join(s for s in (rec.get("receiver", ""), rec.get("inn", ""),
                                          rec.get("address", "")) if s)
            mass = D(rec.get("mass", 0) or 0)
            purpose = _purpose_of(rec.get("operation", ""))
            by = {f: (float(mass) if purpose == f else 0.0)
                  for _, f in _PURPOSE_KEYS}
            xlsx.data_row(ws, r, [
                n, names.get(fkko, rec.get("name", "")) or "—", fkko,
                "—", "—", "—",              # гр. 4–6: получение отходов не ведётся
                party or "—",
                by["transferred_processing"], by["transferred_util"],
                by["transferred_neutral"], by["transferred_storage"],
                by["transferred_burial"]])
            r += 1
