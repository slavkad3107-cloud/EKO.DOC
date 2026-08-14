"""Заполнение бланка журнала учёта отходов (Приказ №1028) из папки «Формы».

Пользователь ведёт журнал в готовом файле Excel, где часть ячеек — формулы
(ссылки на титул, суммы). Поэтому: не рисуем лист заново, а вписываем данные
в бланк-образец, оставляя формулы на месте (их пересчитает Excel).

Колонки ищем по подписям граф, а не по фиксированным адресам: бланки у разных
организаций смещены на строку-другую.

Важно: бланк-образец — это, как правило, ЧУЖОЙ уже заполненный журнал
(другой организации), а не пустая форма. Поэтому строки данных образца
предварительно очищаются — иначе отходы и контрагенты чужой организации
уезжали в отчётный документ клиента. Запись ограничена областью таблицы
(до шапки блока-продолжения); не хватило строк — таблица раздвигается,
объединённые ячейки не трогаем (раньше запись в них роняла заполнение
с AttributeError, сбой молча глотался, и бланк не применялся никогда).
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from openpyxl.cell.cell import MergedCell

from ecodoc.render import template_xlsx as tx

CODE = "waste-movement"

# подпись графы (начало) → ключ данных (num — порядковый номер строки).
# Ключи t_*/partner/contract/… наполняются в зависимости от вида листа:
# «переданные» (Таблица 3) — из transferred_* и extra["waste_receivers"],
# «полученные» (Таблица 4) — из extra["waste_suppliers"]; подписи граф в
# обоих листах одинаковые, различить их можно только по заголовку листа.
_COLUMNS = [
    ("№ п/п", "num"),
    ("наименование отход", "name"),
    ("код фкко", "fkko_code"),
    ("класс опасности", "hazard_class"),
    ("происхождение", "origin"),
    ("агрегатное состояние", "aggregate_state"),
    ("химический", "composition"),
    ("образовано отходов", "generated"),
    ("получено отходов", "received"),
    ("количество полученных отходов", "received"),   # Таблица 4 («Всего»)
    ("количество переданных отходов", "transferred"),  # Таблица 3 («Всего»)
    ("утилизировано", "used"),
    ("обезврежено", "neutralized"),
    ("передано отходов", "transferred"),
    ("для обработки", "t_processing"),
    ("для утилизации", "t_util"),
    ("для обезвреживания", "t_neutral"),
    ("для хранения", "t_storage"),
    ("для захоронения", "t_burial"),
    ("сведения о лицах", "partner"),
    ("дата и номер договора", "contract"),
    ("срок действия договора", "contract_term"),
    ("реквизиты лицензии", "license"),
]

_TITLE_FIELDS = [
    ("наименование юридического лица", "org_name"),
    ("индивидуального предпринимателя", "org_name"),
    ("инн", "inn"),
    ("огрн", "ogrn"),
    ("отчетный год", "year"),
    ("отчётный год", "year"),
]

# служебные подписи титула: строка организации ВЫШЕ их, значения — правее
_TITLE_AUX = ("период", "подпись", "фио", "дата", "ответственный")


def _num(value) -> float | None:
    """Тоннаж бланка: Порядок №1028 требует «в тоннах с точностью до трех
    знаков после запятой» — двоичный хвост float (469.0220892119701) в
    журнал не идёт. Ноль не пишем: пустая графа читается как отсутствие."""
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value).replace(",", "."))
    except Exception:
        return None
    if not d:
        return None
    return float(d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def header_row(ws, max_row: int = 40) -> tuple[int, dict] | None:
    """Найти строку шапки таблицы и колонки граф по подписям."""
    pos = tx.find_anchor(ws, "код фкко", limit_rows=max_row)
    if not pos:
        return None
    row = pos[0]
    cols: dict[str, int] = {}
    for r in range(max(1, row - 2), row + 3):          # шапка бывает в 2–3 строки
        for cell in ws[r]:
            if not isinstance(cell.value, str):
                continue
            text = re.sub(r"\s+", " ", cell.value).strip().lower()
            for label, attr in _COLUMNS:
                if attr not in cols and text.startswith(label):
                    cols[attr] = cell.column
    return (row, cols) if "fkko_code" in cols else None


def _merged_rows(ws) -> set[int]:
    rows: set[int] = set()
    for rng in ws.merged_cells.ranges:
        rows.update(range(rng.min_row, rng.max_row + 1))
    return rows


def _is_numbering_row(ws, row: int) -> bool:
    """Строка нумерации граф: «А», 1, 2, 3… — подряд идущие номера."""
    nums: list[int] = []
    for c in ws[row]:
        v = c.value
        if v in (None, ""):
            continue
        if isinstance(v, str):
            v = v.strip()
            if len(v) <= 2 and not v.isdigit():
                continue                    # буквенные графы «А», «Б»
            if not v.isdigit():
                return False
            v = int(v)
        if isinstance(v, float):
            if not v.is_integer():
                return False
            v = int(v)
        if isinstance(v, bool) or not isinstance(v, int):
            return False
        nums.append(v)
    return len(nums) >= 3 and nums == list(range(nums[0], nums[0] + len(nums)))


def _is_next_block(ws, row: int) -> bool:
    """Начало следующего блока таблицы («продолжение», «№ строки»)."""
    for c in ws[row]:
        v = c.value
        if isinstance(v, str) and v.strip().lower().startswith(
                ("продолжение", "№ строки", "n строки")):
            return True
    return False


def data_region(ws, header: int) -> tuple[int, int]:
    """Границы области данных под шапкой (включительно).

    Начало — после строк шапки (они задеты объединениями) и строки нумерации
    граф; конец — перед первой строкой следующего блока: она либо входит в
    объединённый диапазон (шапка «продолжения» бланка), либо подписана
    «продолжение»/«№ строки». Раньше данные писались с первой ПУСТОЙ строки —
    т.е. ПОСЛЕ чужих строк образца и прямо по шапке блока-продолжения."""
    merged = _merged_rows(ws)
    row = header + 1
    while row < header + 20 and (row in merged or _is_numbering_row(ws, row)):
        row += 1
    start = row
    end = start
    while (end - start < 500 and (end + 1) not in merged
           and not _is_next_block(ws, end + 1)):
        end += 1
    return start, end


def _clear_rows(ws, start: int, end: int) -> None:
    """Очистить строки данных образца: бланк из «Формы» — чужой ЗАПОЛНЕННЫЙ
    журнал, и без очистки его отходы/контрагенты попадали в документ клиента.
    Формулы оставляем — расчётные графы пересчитает Excel."""
    for r in range(start, end + 1):
        for cell in ws[r]:
            if isinstance(cell, MergedCell):
                continue
            v = cell.value
            if v is None or (isinstance(v, str) and v.startswith("=")):
                continue
            cell.value = None


def _insert_row(ws, idx: int) -> None:
    """insert_rows + ручной сдвиг объединённых диапазонов: openpyxl «не
    управляет зависимостями» при вставке строк — merge-диапазоны остаются на
    старых координатах и наехали бы на новые строки данных."""
    ws.insert_rows(idx)
    for rng in ws.merged_cells.ranges:
        if rng.min_row >= idx:
            rng.shift(0, 1)


def _sheet_kind(ws) -> str:
    """Вид листа по его заголовку: "transferred" (Таблица 3 — переданные),
    "received" (Таблица 4 — полученные), "" — общие данные (Прил. 1/2)."""
    text = " ".join(
        re.sub(r"\s+", " ", c.value).strip().lower()
        for row in ws.iter_rows(min_row=1, max_row=4)
        for c in row if isinstance(c.value, str))
    if "переданных другим лицам" in text:
        return "transferred"
    if "полученных от других лиц" in text:
        return "received"
    return ""


def _by_fkko(ctx, key: str) -> dict[str, dict]:
    """Контрагенты по коду ФККО из ctx.extra (waste_receivers/waste_suppliers):
    в модели WasteFlow сведений о лицах и договорах нет."""
    e = ctx.extra if isinstance(ctx.extra, dict) else {}
    out: dict[str, dict] = {}
    for r in e.get(key, []):
        if isinstance(r, dict) and r.get("fkko"):
            out[str(r["fkko"])] = r
    return out


def _org_line(ctx) -> str:
    org = ctx.organization
    line = org.name or org.short_name or ""
    e = ctx.extra if isinstance(ctx.extra, dict) else {}
    site = e.get("site_line") or ""
    if not site and getattr(ctx, "objects", None):
        ob = ctx.objects[0]
        site = f"Площадка: {ob.name or ''} {ob.address or ''}".strip()
    return f"{line}\n{site}" if line and site else (line or site)


def _replace_below_heading(ws, org_line: str) -> None:
    """Бланки без подписей полей (реальный журнал): строка организации — первая
    текстовая ячейка под заголовком формы; в образце там чужая организация."""
    if not org_line:
        return
    pos = tx.find_anchor(ws, "данные учета в области обращения с отходами")
    if not pos:
        return
    for r in range(pos[0] + 1, pos[0] + 12):
        for cell in ws[r]:
            if isinstance(cell, MergedCell):
                continue
            v = cell.value
            if not isinstance(v, str) or not v.strip() or v.startswith("="):
                continue
            if v.strip().lower().startswith(_TITLE_AUX):
                return          # начались служебные подписи — строки орг. нет
            cell.value = org_line
            return


def _replace_right(ws, label: str, value) -> None:
    """Заменить значение ПРАВЕЕ подписи (не обязательно в соседней ячейке):
    в бланке пользователя между «Ответственный исполнитель» и ФИО — 4 пустых
    колонки, и там остаются данные чужой организации."""
    pos = tx.find_anchor(ws, label)
    if not pos:
        return
    row, col = pos
    for cell in ws[row]:
        if cell.column <= col or isinstance(cell, MergedCell):
            continue
        v = cell.value
        if v in (None, "") or (isinstance(v, str) and v.startswith("=")):
            continue
        if str(v).strip().lower().startswith(_TITLE_AUX):
            return              # дальше идёт следующая подпись — значения нет
        cell.value = value
        return


def _fill_title(ws, ctx, values: dict) -> None:
    """Титул: сначала подписи-поля; в бланках без подписей — замена строки
    чужой организации, периода, исполнителя и даты (образец — чужой отчёт)."""
    pairs = {}
    for label, key in _TITLE_FIELDS:
        if values.get(key) not in (None, ""):
            pairs[label] = values[key]
    missing = tx.fill_by_labels(ws, pairs)
    org_labels = {l for l, k in _TITLE_FIELDS if k == "org_name" and l in pairs}
    if not org_labels or org_labels <= set(missing):
        _replace_below_heading(ws, _org_line(ctx))
    if values.get("year"):
        tx.fill_by_labels(ws, {"период": f"за {values['year']} год"})
    e = ctx.extra if isinstance(ctx.extra, dict) else {}
    _replace_right(ws, "ответственный исполнитель",
                   ctx.organization.director_name or "")
    _replace_right(ws, "дата", str(e.get("report_date", "")))


def fill(ctx, out_path: str | Path, sample: Path | None = None) -> Path | None:
    """Заполнить бланк журнала. None — если образца нет (рисуем кодом)."""
    from ecodoc.core import forms_registry
    sample = sample or forms_registry.sample_for(CODE)
    if sample is None or sample.suffix.lower() not in (".xlsx", ".xlsm"):
        return None

    wb = tx.open_template(sample)
    org = ctx.organization
    values = {"org_name": org.name or org.short_name, "inn": org.inn,
              "ogrn": org.ogrn, "year": ctx.period.year or ""}

    if wb.sheetnames:
        _fill_title(wb[wb.sheetnames[0]], ctx, values)

    receivers = _by_fkko(ctx, "waste_receivers")
    suppliers = _by_fkko(ctx, "waste_suppliers")
    filled_sheets = 0
    for name in wb.sheetnames:
        ws = wb[name]
        head = header_row(ws)
        if not head:
            continue
        header, cols = head
        start, end = data_region(ws, header)
        _clear_rows(ws, start, min(end, ws.max_row))
        # Прил. 3 — только переданные, Прил. 4 — только полученные отходы:
        # состав строк в таблицах разный (как и в форме, рисуемой кодом)
        kind = _sheet_kind(ws)
        keep = {"transferred": lambda w: _num(w.transferred) is not None,
                "received": lambda w: _num(w.received) is not None,
                }.get(kind, lambda w: True)
        row, num = start, 0
        for w in ctx.wastes:
            if not (w.fkko_code or w.name) or not keep(w):
                continue
            num += 1
            if row > end:               # таблица кончилась — раздвигаем её,
                _insert_row(ws, row)    # не наезжая на блок-продолжение
                end += 1
            data = {
                "num": num,
                "name": w.name,
                "fkko_code": w.fkko_code,
                "hazard_class": w.hazard_class or None,
                "origin": getattr(w, "origin", ""),
                "aggregate_state": getattr(w, "aggregate_state", ""),
                "composition": getattr(w, "composition", ""),
                "generated": _num(w.generated),
                "received": _num(w.received),
                "used": _num(w.used),
                "neutralized": _num(w.neutralized),
                "transferred": _num(w.transferred),
            }
            info: dict = {}
            if kind == "transferred":
                info = receivers.get(str(w.fkko_code), {})
                data.update({
                    "t_processing": _num(w.transferred_processing),
                    "t_util": _num(w.transferred_util),
                    "t_neutral": _num(w.transferred_neutral),
                    "t_storage": _num(w.transferred_storage),
                    "t_burial": _num(w.transferred_burial),
                    "partner": info.get("receiver", ""),
                    "license": info.get("license", ""),
                })
            elif kind == "received":
                info = suppliers.get(str(w.fkko_code), {})
                data["partner"] = info.get("supplier", "")
            if kind:
                data["contract"] = info.get("contract", "")
                data["contract_term"] = info.get("contract_term", "")
            for attr, col in cols.items():
                value = data.get(attr)
                if value in (None, ""):
                    continue
                cell = ws.cell(row=row, column=col)
                if isinstance(cell, MergedCell):
                    continue            # объединение — не пишем (и не падаем)
                if tx.is_formula(ws, row, col):
                    continue            # расчётную графу не трогаем
                cell.value = value
            row += 1
        filled_sheets += 1
    if not filled_sheets:
        return None
    return tx.save_as(wb, out_path)
