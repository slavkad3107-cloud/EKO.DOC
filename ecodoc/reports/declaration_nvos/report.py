"""Декларация о плате за НВОС (XML + Excel).

Форма — Приказ Минприроды России от 10.12.2020 № 1043 (в ред. Приказа № 241
от 29.04.2025, действует с 01.09.2025). Срок — до 10 марта года, следующего
за отчётным.

ВНИМАНИЕ: действующая редакция содержит 9 разделов расчёта (Р1 выбросы
стационарными; Р2/Р3 сжигание/рассеивание ПНГ на факелах в пределах/сверх
лимита; Р4 сбросы; Р5 отходы производства; Р6 ТКО; Р7 побочные продукты
производства; Р8 вскрышные/вмещающие горные породы; Р9 побочные продукты
животноводства). Печатная книга повторяет состав бланка, сверенный с реально
сданной декларацией (Формы/Отчетность/ДЕкларация/Декларация.pdf): титул с
полями 1–17, лист «Информация о суммах платы, подлежащих внесению в бюджет»,
расчёт «стр.2» со строками 010–195, лист «Информация об авансовых платежах»,
Раздел 1 (выбросы) в 18 граф по бланку. Нумерация строк 130–195 приведена по
бланку 2021 г. — в ред. № 241 возможен сдвиг, сверить по тексту Приложения 2.
"""
from __future__ import annotations

from pathlib import Path

from ecodoc.core.models import Issue, Medium, ReportContext
from ecodoc.core.money import fmt_money
from ecodoc.core.registry import register
from ecodoc.render import xlsx
from ecodoc.render.xmlutil import el, write_tree
from ecodoc.reports.base import Report
from ecodoc.reports.declaration_nvos.calc import SECTIONS, PaymentResult, calculate

from lxml import etree

_BAND_RU = {"norm": "в пределах норматива", "limit": "в пределах лимита",
            "over": "сверх лимита/норматива"}

# «Виды» платы для итоговой части стр.2 (строки 130–195), листа сумм и листа
# авансов: ключ → (подпись, № строки суммы, № строки вычета). Порядок — как в
# бланке: выбросы / ПНГ / сбросы / отходы производства / ТКО.
_KINDS = ("air", "png", "water", "waste", "tko")
_KIND_RU = {"air": "за выбросы", "png": "за выбросы ПНГ", "water": "за сбросы",
            "waste": "за размещение отходов производства",
            "tko": "за размещение ТКО"}
_KIND_REF = {"air": ("040", "131"), "png": ("060", "132"),
             "water": ("080", "133"), "waste": ("100", "134"),
             "tko": ("120", "135")}

# Три способа исчисления авансового платежа (п. 4 ст. 16.4 ФЗ-7) — лист
# «Информация об авансовых платежах»; нужное отмечается знаком X
_ADV_METHODS = (
    ("quarter", "1/4 суммы платы за НВОС, подлежащей уплате (уплаченной) "
                "за предыдущий год"),
    ("ndv", "1/4 суммы платы, определённой исходя из НДВ, ВРВ (НДС, ВРС, "
            "лимитов на размещение отходов)"),
    ("pek", "По данным производственного экологического контроля"),
)
# синонимы значений ctx.extra['declaration']['advance_method']
_ADV_SYNONYM = {"quarter": "quarter", "1/4": "quarter", "q": "quarter",
                "ndv": "ndv", "vrv": "ndv", "limit": "ndv", "ндв": "ndv",
                "pek": "pek", "пэк": "pek"}

# КБК платы за НВОС (администратор 048 — Росприроднадзор), проверены на 2025
_KBK_AIR = "048 1 12 01010 01 6000 120"    # выбросы стационарными объектами
_KBK_PNG = "048 1 12 01070 01 6000 120"    # выбросы при сжигании/рассеивании ПНГ
_KBK_WATER = "048 1 12 01030 01 6000 120"  # сбросы в водные объекты
_KBK_WASTE = "048 1 12 01041 01 6000 120"  # размещение отходов производства (кроме ТКО)
_KBK_TKO = "048 1 12 01042 01 6000 120"    # размещение ТКО

# КБК по разделу декларации. Р7–Р9 (побочные продукты, породы, животноводство)
# редки; КБК уточняйте по действующему перечню — для Р7/Р8 обычно КБК отходов.
_KBK_BY_SECTION = {
    "Р1": _KBK_AIR, "Р2": _KBK_PNG, "Р3": _KBK_PNG, "Р4": _KBK_WATER,
    "Р5": _KBK_WASTE, "Р6": _KBK_TKO, "Р7": _KBK_WASTE, "Р8": _KBK_WASTE, "Р9": "",
}


@register
class DeclarationNVOS(Report):
    code = "declaration-nvos"
    title = "Декларация о плате за НВОС"

    def __init__(self, context: ReportContext):
        super().__init__(context)
        self._calc: PaymentResult | None = None

    @property
    def calc(self) -> PaymentResult:
        if self._calc is None:
            self._calc = calculate(self.ctx)
        return self._calc

    # ------------------------------------------------------------------ #
    def validate(self) -> list[Issue]:
        from ecodoc.core.validators import inn_valid, ogrn_valid
        issues: list[Issue] = []
        o = self.ctx.organization
        if not o.inn:
            issues.append(Issue("error", "ИНН", "не указан ИНН плательщика"))
        elif not inn_valid(o.inn):
            issues.append(Issue("error", "ИНН",
                                f"ИНН {o.inn} не проходит проверку контрольной "
                                f"суммы — вероятна опечатка"))
        if o.ogrn and not ogrn_valid(o.ogrn):
            issues.append(Issue("warning", "ОГРН",
                                f"ОГРН {o.ogrn} не проходит проверку — сверьте"))
        if not o.name:
            issues.append(Issue("error", "наименование", "не указано наименование организации"))
        if not o.oktmo:
            issues.append(Issue("warning", "ОКТМО", "не указан ОКТМО — обязателен для распределения платы"))
        if not self.ctx.period.year:
            issues.append(Issue("error", "период", "не указан отчётный год"))
        if not self.ctx.objects:
            issues.append(Issue("warning", "объекты", "не указан ни один объект НВОС"))
        else:
            from ecodoc.calendar.engine import category_of
            cats = {category_of(o) for o in self.ctx.objects}
            cats.discard("")
            if cats and cats == {"IV"}:
                issues.append(Issue(
                    "error", "категория",
                    "все объекты — IV категории: такие объекты плату за НВОС "
                    "не вносят и декларацию не подают (п. 1 ст. 16.1 ФЗ-7). "
                    "Проверьте категорию во вкладке ОБЪЕКТ."))
        if not (self.ctx.pollutants or self.ctx.wastes):
            issues.append(Issue("error", "данные", "нет ни выбросов/сбросов, ни отходов — нечего декларировать"))
        for w in self.calc.warnings:
            issues.append(Issue("warning", "ставка", w))
        return issues

    # ------------------------------------------------------------------ #
    def render_xml(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        o = self.ctx.organization
        per = self.ctx.period
        c = self.calc

        root = etree.Element("ДекларацияНВОС", version="0.1", форма=self.code)
        # ── плательщик ──
        plat = el(root, "Плательщик")
        el(plat, "Наименование", o.name)
        el(plat, "ИНН", o.inn)
        el(plat, "КПП", o.kpp)
        el(plat, "ОГРН", o.ogrn)
        el(plat, "ОКТМО", o.oktmo)
        el(plat, "Адрес", o.address)
        el(plat, "Руководитель", o.director_name)
        el(root, "ОтчётныйГод", per.year)

        # ── объекты ──
        objs = el(root, "ОбъектыНВОС")
        for ob in self.ctx.objects:
            x = el(objs, "Объект")
            el(x, "Код", ob.code)
            el(x, "Наименование", ob.name)
            el(x, "Категория", ob.category)
            el(x, "ОКТМО", ob.oktmo or o.oktmo)

        # ── строки расчёта ──
        lines_el = el(root, "СтрокиРасчёта")
        for ln in c.lines:
            x = el(lines_el, "Строка", среда=ln.medium, норматив=ln.band,
                   раздел=ln.section)
            el(x, "Код", ln.code)
            el(x, "Наименование", ln.name)
            el(x, "Масса", ln.mass)
            el(x, "Ставка", ln.rate)
            el(x, "КоэффИндексации", ln.k_ind)
            el(x, "КоэффНорматива", ln.k_band)
            el(x, "КоэффДоп", ln.k_extra)
            el(x, "Плата", ln.amount)

        # ── итоги ──
        tot = el(root, "Итоги")
        for key in ("Р1", "Р2", "Р3", "Р4", "Р5", "Р6", "Р7", "Р8", "Р9"):
            el(tot, "Раздел", c.by_section.get(key, 0), код=key, наим=SECTIONS[key])
        el(tot, "ПлатаВыбросы", c.total_air)
        el(tot, "ПлатаСбросы", c.total_water)
        el(tot, "ПлатаОтходы", c.total_waste)
        el(tot, "ПлатаВсего", c.total)

        write_tree(root, out_path)
        return out_path

    # ------------------------------------------------------------------ #
    def render_print(self, out_path: Path) -> Path:
        out_path = self._ensure_dir(out_path)
        wb = xlsx.new_workbook()
        # порядок листов — как в печатной форме бланка: титул, «Информация о
        # суммах платы» (стр. 3–4 образца), расчёт (стр. 5–10), «Информация об
        # авансовых платежах» (стр. 11), затем разделы
        self._sheet_title(wb)          # стр.1 — титульный лист
        self._sheet_summary(wb)        # суммы платы по объектам НВОС
        self._sheet_calc(wb)           # стр.2 — расчёт суммы платы по разделам
        self._sheet_advances(wb)       # способ исчисления авансовых платежей
        self._sheet_section1(wb)       # Раздел 1 — выбросы, 18 граф по бланку
        if any(ln.section in ("Р2", "Р3") for ln in self.calc.lines):
            self._sheet_lines(wb, "Разделы 2-3 (ПНГ)", Medium.AIR.value,
                              sections=("Р2", "Р3"))
        self._sheet_lines(wb, "Раздел 4 (сбросы)", Medium.WATER.value)
        self._sheet_lines(wb, "Разделы 5-9 (отходы)", "waste")
        xlsx.save(wb, out_path)
        return out_path

    # стр.1 — титульный лист официального бланка -----------------------
    def _sheet_title(self, wb):
        o = self.ctx.organization
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        year = self.ctx.period.year or ""
        ws = wb.create_sheet("стр.1")
        xlsx.widths(ws, {"A": 4, "B": 40, "C": 52})
        xlsx.merge(ws, "B1:C1",
                   "ДЕКЛАРАЦИЯ О ПЛАТЕ ЗА НЕГАТИВНОЕ ВОЗДЕЙСТВИЕ НА ОКРУЖАЮЩУЮ СРЕДУ",
                   bold=True, border=False)
        xlsx.merge(ws, "B2:C2", f"за {year} год", border=False, bold=True)
        # ИП и юрлицо заполняют разные поля бланка: у ИП пусты поля ЮЛ (3, 8),
        # у юрлица — поле ФИО предпринимателя (4). Признак — 12-значный ИНН.
        is_ip = len(str(o.inn or "").strip()) == 12
        decl = e.get("declaration") or {}
        pages = decl.get("pages") or ""
        attach = decl.get("attachment_sheets") or ""
        # поле 9 бланка — два пропуска: страницы декларации и листы приложений
        val9 = (f"страниц: {pages or '—'}; листов приложений: {attach or '—'}"
                if (pages or attach) else "")
        rows = [
            ("1", "Вид документа (первичная «0» / уточнённая «1/…»)",
             e.get("doc_kind", "первичная — 0")),
            ("2", "Наименование территориального органа Росприроднадзора, "
                  "в который представляется декларация", e.get("rospr", "")),
            ("3", "Организационно-правовая форма и полное наименование "
                  "юридического лица", "" if is_ip else o.name),
            ("4", "Фамилия, имя, отчество (при наличии) индивидуального "
                  "предпринимателя", o.name if is_ip else ""),
            ("5", "Адрес юридического лица / место жительства ИП", o.address),
            ("6", "Код города и номер контактного телефона", o.phone),
            ("7", "ИНН", o.inn),
            ("8", "КПП", "" if is_ip else o.kpp),
            ("9", "Декларация составлена на ___ страницах с приложением "
                  "подтверждающих документов или их копий на ___ листах", val9),
            ("10", "Достоверность и полноту сведений подтверждаю: "
                   "руководитель ЮЛ / ИП / уполномоченный представитель",
             f"{'' if is_ip else o.director_position} "
             f"{o.director_name or (o.name if is_ip else '')}".strip()),
            # поля 11–17 бланка: подписи и служебные отметки. Данных для них в
            # модели нет — берём из ctx.extra['declaration'] по понятным
            # ключам, иначе печатаем пустую графу (как в принятых отчётах)
            ("11", "Руководитель обособленного подразделения, по доверенности "
                   "(при наличии): фамилия, имя, отчество, подпись, дата",
             str(decl.get("branch_head") or "")),
            ("12", "Исполнитель (при наличии): фамилия, имя, отчество, "
                   "подпись, телефон", str(decl.get("executor") or "")),
            ("13", "Главный бухгалтер (при наличии): фамилия, имя, отчество, "
                   "подпись", str(decl.get("accountant") or "")),
            ("14", "М.П. (при наличии). Далее заполняется должностным лицом "
                   "территориального органа Росприроднадзора", ""),
            ("15", "Декларация представлена (цифрами: день, месяц, год)", ""),
            ("16", "Уполномоченным представителем / по почте, "
                   "на ___ страницах; зарегистрирована за № ___", ""),
            ("17", "Фамилия, имя, отчество и должность должностного лица "
                   "территориального органа Росприроднадзора, подпись", ""),
        ]
        r = 4
        for num, label, value in rows:
            xlsx.cell(ws, f"A{r}", num)
            xlsx.cell(ws, f"B{r}", label, align="left")
            xlsx.cell(ws, f"C{r}", value or "", align="left")
            r += 1
        r += 1
        xlsx.cell(ws, f"B{r}", "Подпись: ______________   "
                  "Дата: «____» __________ 20___ г.",
                  border=False, align="left")

    # ---- общие вычисления итоговой части (стр.2 и лист сумм) ---------
    def _decl_extra(self) -> dict:
        """Пользовательские реквизиты декларации из ctx.extra['declaration']."""
        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        return e.get("declaration") or {}

    def _kind_base(self) -> dict:
        """Начисленная плата по «видам» итоговой части (строки 040/060/080/100/120)."""
        from ecodoc.core.money import D
        bs = self.calc.by_section
        return {
            "air": D(bs.get("Р1", 0)),
            "png": D(bs.get("Р2", 0)) + D(bs.get("Р3", 0)),
            "water": D(bs.get("Р4", 0)),
            "waste": D(bs.get("Р5", 0)),
            "tko": D(bs.get("Р6", 0)),
        }

    def _kind_after_deduction(self) -> dict:
        """Строки 141–145/151–155: плата по виду минус вычет затрат на
        мероприятия по снижению НВОС (отрицательной быть не может)."""
        from decimal import Decimal
        from ecodoc.core.money import D
        decl = self._decl_extra()
        ded = {k: D(v) for k, v in (decl.get("deduction") or {}).items()
               if k in _KINDS}
        base = self._kind_base()
        out = {}
        for k in _KINDS:
            v = base[k] - ded.get(k, Decimal("0"))
            out[k] = v if v > 0 else Decimal("0")
        return out

    # «Информация о суммах платы, подлежащих внесению в бюджет» ---------
    def _sheet_summary(self, wb):
        """Стр. 3–4 бланка: категория объекта НВОС → сумма платы к внесению.

        По бланку — одна строка данных на объект (категория может быть
        пустой), строка «ИТОГО» и блок подписи исполнителя. Плата в расчёте
        к объекту не привязана, поэтому при одном объекте вся сумма — его,
        при нескольких графа суммы остаётся пустой (источника разбивки нет),
        итог при этом верен.
        """
        from decimal import Decimal
        o = self.ctx.organization
        decl = self._decl_extra()
        total = sum(self._kind_after_deduction().values(), Decimal("0"))
        ws = wb.create_sheet("Информация о суммах платы")
        xlsx.widths(ws, {"A": 50, "B": 28})
        xlsx.merge(ws, "A1:B1", "Информация о суммах платы, подлежащих "
                   "внесению в бюджет", bold=True)
        xlsx.cell(ws, "A2", "Категория объекта, оказывающего негативное "
                  "воздействие на окружающую среду", bold=True, fill=True)
        xlsx.cell(ws, "B2", "Сумма платы, подлежащая внесению в бюджет",
                  bold=True, fill=True)
        r = 3
        objs = self.ctx.objects or [None]
        single = len(objs) == 1
        for ob in objs:
            xlsx.cell(ws, f"A{r}", (getattr(ob, "category", "") or "") if ob else "")
            xlsx.cell(ws, f"B{r}", fmt_money(total) if single else "")
            r += 1
        xlsx.cell(ws, f"A{r}", "ИТОГО", bold=True)
        xlsx.cell(ws, f"B{r}", fmt_money(total), bold=True)
        r += 2
        executor = str(decl.get("executor") or "") or o.director_name
        xlsx.cell(ws, f"A{r}", "Достоверность и полноту сведений, указанных "
                  "на данных страницах, подтверждаю:", border=False, align="left")
        xlsx.cell(ws, f"A{r+1}", f"Исполнитель ____________ {executor} "
                  "(подпись, Ф.И.О)", border=False, align="left")
        xlsx.cell(ws, f"A{r+2}", "Дата (цифрами: день, месяц, год): "
                  "«____» __________ 20___ г.", border=False, align="left")

    # «Информация об авансовых платежах, подлежащих внесению в бюджет» --
    def _sheet_advances(self, wb):
        """Стр. 11 бланка: способ исчисления авансового платежа по каждому
        виду платы (строки 010–060), нужное отмечается знаком X.

        Способ в модели не хранится — берётся из
        ctx.extra['declaration']['advance_method'] =
        {'air': 'quarter'|'ndv'|'pek', ...}; без него графы пустые.
        Субъекты МСП авансы не вносят — у них лист остаётся незаполненным.
        """
        o = self.ctx.organization
        decl = self._decl_extra()
        methods = {k: _ADV_SYNONYM.get(str(v).strip().lower(), "")
                   for k, v in (decl.get("advance_method") or {}).items()}
        ws = wb.create_sheet("Авансовые платежи")
        xlsx.widths(ws, {"A": 66, "B": 10, "C": 22})
        xlsx.merge(ws, "A1:C1", "Информация об авансовых платежах, "
                   "подлежащих внесению в бюджет", bold=True)
        xlsx.cell(ws, "A2", "Показатели", bold=True, fill=True)
        xlsx.cell(ws, "B2", "Строки", bold=True, fill=True)
        xlsx.cell(ws, "C2", "Значения показателей", bold=True, fill=True)
        oktmo = ((self.ctx.objects[0].oktmo if self.ctx.objects else "")
                 or o.oktmo or "")
        r = 3
        xlsx.cell(ws, f"A{r}", "Код по ОКТМО объекта, оказывающего негативное "
                  "воздействие на окружающую среду", align="left")
        xlsx.cell(ws, f"B{r}", "010")
        xlsx.cell(ws, f"C{r}", oktmo)
        r += 1
        xlsx.merge(ws, f"A{r}:C{r}", "Выбранный способ исчисления авансового "
                   "платежа (нужное отметить знаком X):", align="left")
        r += 1
        codes = {"air": "020", "png": "030", "water": "040",
                 "waste": "050", "tko": "060"}
        labels = {
            "air": "Авансовый платёж за выбросы загрязняющих веществ",
            "png": "Авансовый платёж за выбросы при сжигании и (или) "
                   "рассеивании ПНГ",
            "water": "Авансовый платёж за сбросы загрязняющих веществ",
            "waste": "Авансовый платёж за размещение отходов производства "
                     "и потребления (кроме ТКО)",
            "tko": "Авансовый платёж за размещение ТКО",
        }
        for k in _KINDS:
            xlsx.cell(ws, f"A{r}", labels[k], align="left", bold=True)
            xlsx.cell(ws, f"B{r}", codes[k], bold=True)
            xlsx.cell(ws, f"C{r}", "")
            r += 1
            for mk, mlabel in _ADV_METHODS:
                xlsx.cell(ws, f"A{r}", "  " + mlabel, align="left")
                xlsx.cell(ws, f"B{r}", "")
                xlsx.cell(ws, f"C{r}", "X" if methods.get(k) == mk else "")
                r += 1
        r += 1
        executor = str(decl.get("executor") or "") or o.director_name
        xlsx.cell(ws, f"A{r}", f"Исполнитель ____________ {executor} "
                  "(подпись, Ф.И.О)", border=False, align="left")

    # стр.2 — расчёт суммы платы, официальные коды строк 010–195 -------
    # (сверено с реальной сданной декларацией, Приложение 2 к Приказу № 1043)
    def _sheet_calc(self, wb):
        from decimal import Decimal
        from ecodoc.core.money import D
        o = self.ctx.organization
        c = self.calc
        bs = c.by_section
        # суммы по (раздел, корзина) для строк 041/042/043 и т.п.
        sb: dict = {}
        for ln in c.lines:
            sb[(ln.section, ln.band)] = sb.get((ln.section, ln.band), Decimal("0")) + D(ln.amount)

        def band(sect, b):
            return fmt_money(sb.get((sect, b), Decimal("0")))

        e = self.ctx.extra if isinstance(self.ctx.extra, dict) else {}
        decl = e.get("declaration") or {}

        def okt(kind: str) -> str:
            """ОКТМО для блока: свой у объекта размещения, иначе плательщика."""
            return str((decl.get("oktmo") or {}).get(kind) or o.oktmo or "")

        # вычеты (затраты на мероприятия по снижению НВОС), зачёт переплаты и
        # авансовые платежи в модели не считаются — их вносит пользователь в
        # ctx.extra['declaration']; при отсутствии в бланке остаются нули,
        # а не пустые строки
        ded = {k: D(v) for k, v in (decl.get("deduction") or {}).items()
               if k in _KINDS}
        ded_total = sum(ded.values(), Decimal("0"))
        adj = self._kind_after_deduction()      # строки 141–145 / 151–155
        adj_total = sum(adj.values(), Decimal("0"))
        off = {k: D(v) for k, v in (decl.get("offset") or {}).items()
               if k in _KINDS}                  # зачтённая переплата, 161–165
        off_total = sum(off.values(), Decimal("0"))
        # авансы: {'air': {'q1':…,'q2':…,'q3':…}} или {'air': сумма}; старый
        # плоский вид {'q1': …} тоже принимается — без привязки к виду платы
        # такие суммы попадают только в итог строки 170
        zero_q = {"q1": Decimal("0"), "q2": Decimal("0"), "q3": Decimal("0")}
        adv_q = {k: dict(zero_q) for k in _KINDS}
        adv_extra = {k: Decimal("0") for k in _KINDS}  # сумма без кварталов
        adv_flat = Decimal("0")
        for key, val in (decl.get("advance") or {}).items():
            if key in _KINDS:
                if isinstance(val, dict):
                    for q in zero_q:
                        adv_q[key][q] += D(val.get(q) or 0)
                else:
                    adv_extra[key] += D(val or 0)
            elif key in zero_q:
                adv_flat += D(val or 0)
        adv_kind = {k: sum(adv_q[k].values(), Decimal("0")) + adv_extra[k]
                    for k in _KINDS}
        adv_total = sum(adv_kind.values(), Decimal("0")) + adv_flat
        # итог к внесению (180) и к возврату/зачёту (190) по видам платы;
        # незакреплённые за видом авансы (adv_flat) учитываются только в итоге
        fin, ret = {}, {}
        for k in _KINDS:
            d = adj[k] - off.get(k, Decimal("0")) - adv_kind[k]
            fin[k] = d if d > 0 else Decimal("0")
            ret[k] = -d if d < 0 else Decimal("0")
        diff_total = adj_total - off_total - adv_total
        fin_total = diff_total if diff_total > 0 else Decimal("0")
        ret_total = -diff_total if diff_total < 0 else Decimal("0")

        ws = wb.create_sheet("стр.2")
        xlsx.widths(ws, {"A": 10, "B": 60, "C": 26, "D": 18})
        xlsx.merge(ws, "A1:D1", "Расчёт суммы платы, подлежащей внесению в бюджет "
                   "(Приложение 2 к Приказу Минприроды № 1043 в ред. № 241)",
                   bold=True, border=False)
        xlsx.cell(ws, "A3", "Код строки", bold=True, fill=True)
        xlsx.cell(ws, "B3", "Показатели", bold=True, fill=True, align="left")
        xlsx.cell(ws, "C3", "КБК / ОКТМО", bold=True, fill=True)
        xlsx.cell(ws, "D3", "Сумма, руб.", bold=True, fill=True)
        png = fmt_money(D(bs.get("Р2", 0)) + D(bs.get("Р3", 0)))
        # (код, показатель, значение-в-C (КБК/ОКТМО), значение-в-D (сумма))
        rows = [
            ("010", "Код по ОКТМО объекта, оказывающего негативное воздействие "
                    "на окружающую среду", o.oktmo or "", None),
            # далее — блоки «КБК → ОКТМО → сумма», как в бланке: после каждого
            # КБК идёт своя строка ОКТМО (у объектов размещения он может
            # отличаться от ОКТМО плательщика). Разделы 7–9 в формулу 020
            # бланка не входят — при наличии печатается сноска после таблицы.
            ("020", "Сумма платы, исчисленная без учёта корректировки её "
                    "размера, всего (020 = 021+022+023+024+025)",
             "", fmt_money(c.total)),
            ("021", "  плата за выбросы стационарными источниками (040)", "", fmt_money(bs.get("Р1", 0))),
            ("022", "  плата за выбросы ПНГ (060)", "", png),
            ("023", "  плата за сбросы (080)", "", fmt_money(bs.get("Р4", 0))),
            ("024", "  плата за размещение отходов производства (100)", "", fmt_money(bs.get("Р5", 0))),
            ("025", "  плата за размещение ТКО (120)", "", fmt_money(bs.get("Р6", 0))),
            ("030", "КБК: плата за выбросы", _KBK_AIR, None),
            ("031", "Код по ОКТМО", okt("air"), None),
            ("040", "Сумма платы за выбросы, всего (040 = 041+042+043)", "", fmt_money(bs.get("Р1", 0))),
            ("041", "  в пределах НДВ, ТН", "", band("Р1", "norm")),
            ("042", "  в пределах ВРВ", "", band("Р1", "limit")),
            ("043", "  сверх НДВ, ТН, ВРВ", "", band("Р1", "over")),
            ("050", "КБК: плата за выбросы ПНГ", _KBK_PNG, None),
            ("051", "Код по ОКТМО", okt("png"), None),
            ("060", "Сумма платы за выбросы ПНГ, всего (060 = 061+062+063)", "", png),
            ("061", "  плата за выбросы ПНГ в пределах НДВ, ТН", "", band("Р2", "norm")),
            ("062", "  плата за выбросы ПНГ в пределах ВРВ", "", band("Р2", "limit")),
            ("063", "  плата за выбросы ПНГ сверх НДВ, ТН, ВРВ", "", band("Р3", "over")),
            ("070", "КБК: плата за сбросы", _KBK_WATER, None),
            ("071", "Код по ОКТМО", okt("water"), None),
            ("080", "Сумма платы за сбросы, всего (080 = 081+082+083)", "", fmt_money(bs.get("Р4", 0))),
            ("081", "  в пределах НДС, ТН", "", band("Р4", "norm")),
            ("082", "  в пределах ВРС", "", band("Р4", "limit")),
            ("083", "  сверх НДС, ТН, ВРС", "", band("Р4", "over")),
            ("090", "КБК: плата за размещение отходов производства", _KBK_WASTE, None),
            ("091", "Код по ОКТМО объекта размещения отходов", okt("waste"), None),
            ("100", "Сумма платы за размещение отходов производства", "", fmt_money(bs.get("Р5", 0))),
            ("101", "  в пределах лимита", "", band("Р5", "norm")),
            ("102", "  сверх лимита", "", band("Р5", "over")),
            ("110", "КБК: плата за размещение ТКО", _KBK_TKO, None),
            ("111", "Код по ОКТМО объекта размещения ТКО", okt("tko"), None),
            ("120", "Сумма платы за размещение ТКО, всего (120 = 121+122+123)",
             "", fmt_money(bs.get("Р6", 0))),
            # 121 — плата регионального оператора за принятые ТКО: в расчёте
            # не участвует, источника в модели нет — значение только из
            # ctx.extra['declaration']['tko_accepted'], иначе 0,00
            ("121", "  плата за размещение принятых ТКО", "",
             fmt_money(D(decl.get("tko_accepted") or 0))),
            ("122", "  плата за размещение ТКО в пределах установленного "
                    "лимита на их размещение", "", band("Р6", "norm")),
            ("123", "  плата за размещение ТКО сверх установленного лимита "
                    "на их размещение", "", band("Р6", "over")),
            # ── итоговая часть бланка (нумерация по бланку 2021 г.;
            # в ред. № 241 возможен сдвиг — сверить по тексту Приложения 2) ──
            ("130", "Сумма средств на выполнение мероприятий по снижению "
                    "негативного воздействия на окружающую среду, всего "
                    "(130 = 131+132+133+134+135)",
             "", fmt_money(ded_total)),
            ("131", "  платы за выбросы", "", fmt_money(ded.get("air", 0))),
            ("132", "  платы за выбросы ПНГ", "", fmt_money(ded.get("png", 0))),
            ("133", "  платы за сбросы", "", fmt_money(ded.get("water", 0))),
            ("134", "  платы за размещение отходов производства", "", fmt_money(ded.get("waste", 0))),
            ("135", "  платы за размещение ТКО", "", fmt_money(ded.get("tko", 0))),
            ("140", "Сумма платы, исчисленная с учётом корректировки её "
                    "размера (140 = 141+142+143+144+145)", "", fmt_money(adj_total)),
        ]
        # в бланке подстроки 141–145 идут без формул (формулы — в 151–155)
        for i, k in enumerate(_KINDS, start=1):
            rows.append((f"14{i}", f"  плата {_KIND_RU[k]}",
                         "", fmt_money(adj[k])))
        rows.append(("150", "Сумма платы, подлежащей внесению в бюджет, всего "
                            "(150 = 151+152+153+154+155)", "", fmt_money(adj_total)))
        for i, k in enumerate(_KINDS, start=1):
            s, d_ = _KIND_REF[k]
            rows.append((f"15{i}", f"  плата {_KIND_RU[k]} (строка {s} − "
                         f"строка {d_})", "", fmt_money(adj[k])))
        rows.append(("160", "Сумма платы, зачтённая в предыдущем отчётном "
                            "периоде в счёт будущего отчётного периода, всего "
                            "(160 = 161+162+163+164+165)",
                     "", fmt_money(off_total)))
        for i, k in enumerate(_KINDS, start=1):
            rows.append((f"16{i}", f"  плата {_KIND_RU[k]}", "",
                         fmt_money(off.get(k, 0))))
        rows.append(("166", "Номер решения о зачёте сумм излишне уплаченной "
                            "(взысканной) платы за негативное воздействие на "
                            "окружающую среду в счёт будущего отчётного периода",
                     str(decl.get("offset_decision") or ""), None))
        rows.append(("170", "Сведения о суммах внесённых авансовых платежей, "
                            "всего (170 = 171+172+173+174+175)",
                     "", fmt_money(adv_total)))
        for i, k in enumerate(_KINDS, start=1):
            rows.append((f"17{i}", f"  {_KIND_RU[k]}", "", fmt_money(adv_kind[k])))
            # в бланке подстроки кварталов стоят в графе «Строки» (кодов у них
            # нет — вместо кода печатается «1 квартал» и т.д.)
            for q_label, q in (("1 квартал", "q1"), ("2 квартал", "q2"),
                               ("3 квартал", "q3")):
                rows.append((q_label, "", "", fmt_money(adv_q[k][q])))
        rows.append(("180", "Итоговая сумма платы для внесения за отчётный "
                            "период, всего (180 = 181+182+183+184+185)",
                     "", fmt_money(fin_total)))
        for i, k in enumerate(_KINDS, start=1):
            rows.append((f"18{i}", f"  плата {_KIND_RU[k]}", "", fmt_money(fin[k])))
        rows.append(("190", "Итоговая сумма платы для возврата и/или зачёта, "
                            "всего (190 = 191+192+193+194+195)", "", fmt_money(ret_total)))
        for i, k in enumerate(_KINDS, start=1):
            rows.append((f"19{i}", f"  плата {_KIND_RU[k]}", "", fmt_money(ret[k])))
        r = 4
        for code, label, c_val, d_val in rows:
            bold = code in ("010", "020", "150", "180")
            xlsx.cell(ws, f"A{r}", code, bold=bold)
            xlsx.cell(ws, f"B{r}", label, align="left", bold=bold)
            xlsx.cell(ws, f"C{r}", c_val)
            xlsx.cell(ws, f"D{r}", d_val if d_val is not None else "", bold=bold)
            r += 1
        extra = D(bs.get("Р7", 0)) + D(bs.get("Р8", 0)) + D(bs.get("Р9", 0))
        if extra > 0:
            xlsx.cell(ws, f"B{r}", "Плата за размещение побочных продуктов производства / "
                      "вскрышных пород / побочных продуктов животноводства (Разделы 7–9)",
                      border=False, align="left")
            xlsx.cell(ws, f"D{r}", fmt_money(extra))
            r += 1
        xlsx.cell(ws, f"A{r+1}", "Разделы 2–3 (ПНГ) — по флагу is_flare; строка 025/120 — ТКО "
                  "(ФККО «7 3…»). Сверено с реальной сданной декларацией.",
                  border=False, italic=True, size=9, align="left")

    # Раздел 1 — выбросы стационарными источниками, 18 граф по бланку ---
    def _sheet_section1(self, wb):
        """Раздел 1 в составе и порядке граф официального бланка.

        Одна строка = одно вещество (Pollutant), массы раскладываются по
        графам 6/7/8 (НДВ,ТН / ВРВ / сверх), суммы платы — по графам 15/16/17.
        Установленные выбросы (гр. 3–4) и стационарный источник в модели не
        хранятся — берутся из ctx.extra['declaration'] (ключи 'air_limits',
        'stationary_source'), иначе графы остаются пустыми, как в принятых
        отчётах.
        """
        from decimal import Decimal
        from ecodoc.core.money import D
        from ecodoc.core.refdata import coefficients
        band_k = coefficients()["band"]
        o = self.ctx.organization
        ob = self.ctx.objects[0] if self.ctx.objects else None
        decl = self._decl_extra()
        lines = [ln for ln in self.calc.lines if ln.section == "Р1"]

        ws = wb.create_sheet("Раздел 1 (выбросы)")
        xlsx.merge(ws, "A1:R1", "Раздел 1. Расчёт суммы платы за выбросы "
                   "загрязняющих веществ в атмосферный воздух стационарными "
                   "источниками", bold=True, border=False)
        # шапка объекта — как на листе бланка
        head = [
            ("Категория объекта, оказывающего негативное воздействие "
             "на окружающую среду", (ob.category if ob else "")),
            ("Наименование объекта", ob.name if ob else ""),
            ("Код объекта", ob.code if ob else ""),
            ("Адрес места нахождения объекта",
             (ob.address if ob else "") or o.address),
            ("Реквизиты документа, на основании которого осуществляются "
             "выбросы", str(decl.get("air_permit") or "")),
        ]
        r = 2
        for label, value in head:
            xlsx.merge(ws, f"A{r}:F{r}", label, align="left")
            xlsx.merge(ws, f"G{r}:R{r}", value, align="left")
            r += 1
        r += 1
        headers = [
            "N п/п", "Наименование загрязняющего вещества",
            "Установленные выбросы, т: НДВ, ТН",
            "Установленные выбросы, т: ВРВ",
            "Фактический выброс, всего, т",
            "в т.ч. в пределах НДВ, ТН", "в т.ч. в пределах ВРВ",
            "в т.ч. сверх НДВ, ТН, ВРВ", "Ставка платы, руб./т",
            "Кнд", "Квр", "Кср / Кпр", "Кот", "Кинд",
            "Сумма платы в пределах НДВ, ТН, руб. (гр.6×9×10×13×14)",
            "Сумма платы в пределах ВРВ, руб. (гр.7×9×11×13×14)",
            "Сумма платы сверх ВРВ, НДВ, ТН, руб. (гр.8×9×12×13×14)",
            "Сумма платы, всего, руб. (гр.15+16+17)"]
        # ширины через xlsx.widths: header_row(widths=…) читает ячейку строки
        # 1, а она здесь объединена под заголовок листа
        xlsx.widths(ws, dict(zip(
            "ABCDEFGHIJKLMNOPQR",
            [6, 26, 11, 11, 11, 11, 11, 11, 11, 7, 7, 8, 7, 7, 13, 13, 13, 14])))
        xlsx.header_row(ws, r, headers)
        r += 1
        xlsx.header_row(ws, r, [str(i) for i in range(1, 19)])  # номера граф
        r += 1
        # группировка строк расчёта (по полосам) обратно в «одно вещество»
        per: dict = {}
        order: list = []
        for ln in lines:
            key = (ln.code, ln.name)
            if key not in per:
                per[key] = {"mass": {}, "amt": {}, "k": {},
                            "rate": ln.rate, "k_ot": ln.k_extra,
                            "k_ind": ln.k_ind}
                order.append(key)
            per[key]["mass"][ln.band] = ln.mass
            per[key]["amt"][ln.band] = ln.amount
            per[key]["k"][ln.band] = ln.k_band
        # заголовок стационарного источника: в модели источника выброса нет
        # (Pollutant.source — это происхождение данных), реквизиты берутся из
        # ctx.extra; без них печатаем общий блок с пустыми реквизитами
        src = decl.get("stationary_source") or {}
        src_name = str(src.get("name") or "")
        src_num = str(src.get("number") or "")
        xlsx.merge(ws, f"A{r}:R{r}",
                   f"Стационарный источник {src_name} № {src_num or '____'}",
                   align="left", bold=True)
        r += 1
        xlsx.merge(ws, f"A{r}:R{r}", "ОКТМО стационарного источника "
                   + str(src.get("oktmo") or (ob.oktmo if ob else "")
                         or o.oktmo or ""), align="left")
        r += 1
        limits = decl.get("air_limits") or {}
        tot = {15: Decimal("0"), 16: Decimal("0"), 17: Decimal("0"),
               18: Decimal("0")}
        n = 0
        for key in order:
            n += 1
            d = per[key]
            lim = limits.get(key[0]) or {}
            m = {b: d["mass"].get(b, Decimal("0")) for b in ("norm", "limit", "over")}
            a = {b: d["amt"].get(b, Decimal("0")) for b in ("norm", "limit", "over")}
            total = a["norm"] + a["limit"] + a["over"]
            # коэффициенты полос: где полосы не было — справочное значение
            k10 = d["k"].get("norm", D(band_k["norm"]))
            k11 = d["k"].get("limit", D(band_k["limit"]))
            k12 = d["k"].get("over", D(band_k["over"]))
            xlsx.data_row(ws, r, [
                n, key[1], str(lim.get("ndv") or ""), str(lim.get("vrv") or ""),
                float(m["norm"] + m["limit"] + m["over"]),
                float(m["norm"]), float(m["limit"]), float(m["over"]),
                float(d["rate"]), float(k10), float(k11), float(k12),
                float(d["k_ot"]), float(d["k_ind"]),
                fmt_money(a["norm"]), fmt_money(a["limit"]),
                fmt_money(a["over"]), fmt_money(total)])
            r += 1
            tot[15] += a["norm"]
            tot[16] += a["limit"]
            tot[17] += a["over"]
            tot[18] += total
        for label in ("Итого:", "Итого по стационарным источникам:"):
            xlsx.merge(ws, f"A{r}:N{r}", label, align="left", bold=True)
            for col, key in (("O", 15), ("P", 16), ("Q", 17), ("R", 18)):
                xlsx.cell(ws, f"{col}{r}", fmt_money(tot[key]), bold=True)
            r += 1
        # корректировка размера платы программой не рассчитывается —
        # строки бланка печатаются пустыми
        xlsx.merge(ws, f"A{r}:N{r}", "Всего по всем стационарным источникам "
                   "по тем загрязняющим веществам, по которым осуществляется "
                   "корректировка размера платы", align="left")
        for col in ("O", "P", "Q", "R"):
            xlsx.cell(ws, f"{col}{r}", "")
        r += 1
        xlsx.merge(ws, f"A{r}:R{r}", "в том числе:", align="left")

    # ----- листы Excel -----
    def _sheet_lines(self, wb, title: str, medium: str,
                     sections: tuple = ()):
        c = self.calc
        rows = [ln for ln in c.lines if ln.medium == medium
                and (not sections or ln.section in sections)]
        ws = wb.create_sheet(title)
        headers = ["Раздел", "Код", "Наименование", "Норматив", "Масса, т",
                   "Ставка, руб.", "Кинд", "Кнорм", "Кдоп", "Плата, руб."]
        xlsx.header_row(ws, 1, headers,
                        widths=[8, 12, 32, 22, 12, 14, 8, 8, 8, 16])
        r = 2
        for ln in rows:
            xlsx.data_row(ws, r, [
                ln.section, ln.code, ln.name, _BAND_RU.get(ln.band, ln.band),
                float(ln.mass), float(ln.rate), float(ln.k_ind),
                float(ln.k_band), float(ln.k_extra), fmt_money(ln.amount)])
            r += 1
        # итог по листу
        total = sum((ln.amount for ln in rows), start=type(rows[0].amount)(0)) if rows else 0
        tcell = ws.cell(row=r, column=9, value="ИТОГО:")
        tcell.font = xlsx.BOLD
        v = ws.cell(row=r, column=10, value=fmt_money(total))
        v.font = xlsx.BOLD
