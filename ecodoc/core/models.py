"""Доменные модели ЭкоДок — общие для всех форм отчётности.

Это «единый источник правды»: парсеры заполняют эти объекты из приложенных
документов, генераторы превращают их в XML и печатные формы. Одни и те же
сущности (организация, объект НВОС, отход, выброс) переиспользуются всеми
четырьмя формами, поэтому модель живёт в core, а не внутри отчётов.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class Medium(str, Enum):
    AIR = "air"        # выбросы в атмосферный воздух
    WATER = "water"    # сбросы в водные объекты
    WASTE = "waste"    # размещение отходов


class NormBand(str, Enum):
    """Норматив, в пределах которого учтена масса (определяет коэффициент платы)."""
    NORM = "norm"      # в пределах НДВ/НДС/лимита размещения
    LIMIT = "limit"    # в пределах ВСВ/ВСС (временно разрешённые)
    OVER = "over"      # сверх нормативов/лимитов


@dataclass
class Organization:
    """Природопользователь (юр. лицо или ИП)."""
    name: str = ""
    short_name: str = ""
    inn: str = ""
    kpp: str = ""
    ogrn: str = ""
    okpo: str = ""
    okved: str = ""
    address: str = ""           # юридический адрес
    oktmo: str = ""             # ОКТМО места внесения платы
    director_name: str = ""     # ФИО руководителя
    director_position: str = "Генеральный директор"
    phone: str = ""
    email: str = ""

    @property
    def is_individual(self) -> bool:
        """ИП/физлицо определяется по длине ИНН (12 знаков), у ЮЛ — 10."""
        return len((self.inn or "").strip()) == 12

    @property
    def official_title(self) -> str:
        """Должность подписанта: у ИП — «Индивидуальный предприниматель»."""
        return "Индивидуальный предприниматель" if self.is_individual else self.director_position


@dataclass
class NVOSObject:
    """Объект, оказывающий негативное воздействие (ОНВ)."""
    code: str = ""              # код объекта НВОС, напр. «40-0178-001234-П»
    name: str = ""
    category: str = ""          # I / II / III / IV
    address: str = ""
    oktmo: str = ""
    region_code: str = ""       # код субъекта РФ (78 — СПб, 47 — ЛО)


@dataclass
class Pollutant:
    """Загрязняющее вещество (выброс или сброс) за отчётный период.

    Массы разнесены по нормативным «корзинам» — от этого зависит коэффициент
    при расчёте платы. Единицы — тонны.
    """
    name: str = ""
    code: str = ""              # код вещества по перечню (напр. 0301 — азота диоксид)
    medium: Medium = Medium.AIR
    mass_norm: Decimal = Decimal("0")    # в пределах норматива (НДВ/НДС)
    mass_limit: Decimal = Decimal("0")   # в пределах лимита (ВСВ/ВСС)
    mass_over: Decimal = Decimal("0")    # сверх лимита
    # необязательные коэффициенты к ставке (если не заданы — берутся по умолчанию)
    k_ot: Optional[Decimal] = None       # коэффициент за территорию (ООПТ и пр.)
    is_flare: bool = False      # выбросы при сжигании/рассеивании ПНГ на факелах
                                # (Разделы 2/3 декларации), для обычных выбросов False
    source: str = ""            # откуда взяты массы: «НДВ» / «ООС» / «инвентаризация»
                                # (по воздуху данные берутся из проекта НДВ или раздела ООС)


@dataclass
class WasteFlow:
    """Движение отхода за период (для учёта по №1028 и расчёта платы за размещение).

    Все значения — тонны. Поля движения нужны форме «Учёт отходов»; поля
    размещения (placed_*) — Декларации НВОС.
    """
    fkko_code: str = ""         # код по ФККО (11 знаков)
    name: str = ""
    hazard_class: int = 5       # класс опасности 1..5

    accumulated_start: Decimal = Decimal("0")   # на начало периода (хранение)
    accumulated_start_nakopl: Decimal = Decimal("0")  # на начало периода (накопление)
    generated: Decimal = Decimal("0")           # образовано
    received: Decimal = Decimal("0")            # принято от others
    processed: Decimal = Decimal("0")           # обработано (сортировка и пр.)
    used: Decimal = Decimal("0")                # утилизировано
    neutralized: Decimal = Decimal("0")         # обезврежено
    transferred: Decimal = Decimal("0")         # передано others (всего)
    transferred_util: Decimal = Decimal("0")     # из переданного — на утилизацию
    transferred_neutral: Decimal = Decimal("0")  # из переданного — на обезвреживание
    transferred_storage: Decimal = Decimal("0")  # из переданного — на хранение
    transferred_burial: Decimal = Decimal("0")   # из переданного — на захоронение
    placed_norm: Decimal = Decimal("0")         # размещено в пределах лимита
    placed_over: Decimal = Decimal("0")         # размещено сверх лимита
    accumulated_end: Decimal = Decimal("0")     # на конец периода

    is_mining: bool = False     # отход добывающей промышленности (для ставки V кл.)
    # тип отхода для раздела декларации: "prod" (производства — Р5), "tko" (Р6),
    # "byproduct" (побочные продукты производства — Р7), "overburden" (вскрышные/
    # вмещающие породы — Р8), "livestock" (побочные продукты животноводства — Р9).
    # Пусто => авто: ТКО по группе ФККО «7 3…», иначе — отходы производства.
    waste_kind: str = ""

    # --- описательные поля (Приложение 1 журнала №1028, кадастр) ---
    origin: str = ""            # происхождение / условия образования вида отхода
    aggregate_state: str = ""   # агрегатное состояние и физическая форма
    composition: str = ""       # химический и (или) компонентный состав, %


@dataclass
class WasteAct:
    """Справка-акт на отход — ПЕРВИЧНЫЙ ввод по отходам.

    Все отходные формы (журнал №1028, 2-ТП отходы, кадастр, раздел отходов
    декларации) СЧИТАЮТСЯ из списка актов агрегацией по ФККО (см.
    ecodoc/core/waste_agg.py). Один акт = одна передача/обращение с отходом.
    """
    name: str = ""              # наименование отхода
    fkko_code: str = ""         # код по ФККО
    hazard_class: int = 5       # класс опасности 1..5
    mass: Decimal = Decimal("0")        # масса, тонн
    volume_m3: Decimal = Decimal("0")   # объём, м³ (если задан)
    density: Decimal = Decimal("0")     # плотность, т/м³ (для пересчёта)
    # вид обращения: утилизация | обезвреживание | размещение | хранение | ""
    operation: str = ""
    carrier: str = ""           # перевозчик
    receiver: str = ""          # приёмщик / полигон / получатель
    receiver_inn: str = ""
    license: str = ""           # реквизиты лицензии получателя
    date: str = ""              # дата акта (ДД.ММ.ГГГГ)


@dataclass
class ReportPeriod:
    year: int = 0
    # для квартальных/полугодовых форм; для годовых quarter=None
    quarter: Optional[int] = None


@dataclass
class ReportContext:
    """Полный набор входных данных для генерации любой формы.

    Парсеры наполняют этот объект из приложенных файлов; затем пользователь
    правит его вручную; затем форма рендерится.
    """
    organization: Organization = field(default_factory=Organization)
    objects: list[NVOSObject] = field(default_factory=list)
    period: ReportPeriod = field(default_factory=ReportPeriod)
    pollutants: list[Pollutant] = field(default_factory=list)
    # первичный ввод по отходам — справки-акты; wastes (движение) считается из них
    waste_acts: list[WasteAct] = field(default_factory=list)
    wastes: list[WasteFlow] = field(default_factory=list)
    # произвольные доп.поля, специфичные для конкретной формы (ПЭК, кадастр)
    extra: dict = field(default_factory=dict)
    # «провенанс» — откуда какое значение взято (файл/страница), для проверки человеком
    provenance: dict = field(default_factory=dict)


@dataclass
class Issue:
    """Результат валидации: предупреждение или ошибка перед выгрузкой."""
    level: str          # "error" | "warning"
    field: str
    message: str

    def __str__(self) -> str:
        mark = "✖" if self.level == "error" else "⚠"
        return f"{mark} [{self.field}] {self.message}"
