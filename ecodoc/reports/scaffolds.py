"""Каркасы форм отчётности, ещё не реализованных полностью.

Зарегистрированы, чтобы карта модулей и календарь подачи были полными.
"""
from __future__ import annotations

from ecodoc.core.registry import register
from ecodoc.reports.base import NotImplementedReport


@register
class TP2Water(NotImplementedReport):
    code = "2tp-water"
    title = "2-ТП (водхоз)"
    # Нужен блок водопотребления/водоотведения в ctx.extra['water']
    # (журналы водоучёта) — модель появится вместе с реализацией.


# ── Контур «Разработка»: полная карта документов ─────────────────────────
# Зарегистрированы каркасами, чтобы весь ландшафт был виден в `ecodoc list`
# и учитывался контролем полноты. Реализуются по мере надобности.

class _Dev(NotImplementedReport):
    domain = "development"
    has_xml = False


@register
class PNOOLR(_Dev):
    code = "pnoolr"
    title = "ПНООЛР — проект нормативов образования отходов и лимитов"


@register
class HazardClassCalc(_Dev):
    code = "hazard-class"
    title = "Расчёт класса опасности отхода (пр. МПР № 536) — калькулятор во вкладке «Сервис»"
    implemented = False   # интерактивный калькулятор в GUI (Сервис), не форма-генератор


@register
class NMUPlan(_Dev):
    code = "nmu"
    title = "План мероприятий при НМУ (пр. МПР № 811)"


@register
class PLARN(_Dev):
    code = "plarn"
    title = "ПЛАРН — план ликвидации аварийных разливов нефтепродуктов"


@register
class DVOS(_Dev):
    code = "dvos"
    title = "Декларация о воздействии на окружающую среду (II категория)"


@register
class AirInventory(_Dev):
    code = "air-inventory"
    title = "Инвентаризация источников выбросов (пр. МПР № 871)"


@register
class PEKProgram(_Dev):
    code = "pek-program"
    title = "Программа ПЭК (разработка, пр. МПР № 109)"


@register
class TUWaste(_Dev):
    code = "tu-waste"
    title = "ТУ / письма о технических условиях (грунты, отходы строительства)"
