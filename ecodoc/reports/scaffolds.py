"""Каркасы форм отчётности, ещё не реализованных полностью.

Зарегистрированы, чтобы карта модулей и календарь подачи были полными.
"""
from __future__ import annotations

from ecodoc.core.models import Issue
from ecodoc.core.registry import register
from ecodoc.reports.base import NotImplementedReport


# 2-ТП (водхоз) реализована в ecodoc/reports/tp2_water/report.py


# ── Контур «Разработка»: полная карта документов ─────────────────────────
# Зарегистрированы каркасами, чтобы весь ландшафт был виден в `ecodoc list`
# и учитывался контролем полноты. Реализуются по мере надобности.

class _Dev(NotImplementedReport):
    domain = "development"
    has_xml = False
    devdoc = False   # True => реальный генератор .docx через `ecodoc devdoc <code>`

    def validate(self) -> list[Issue]:
        if getattr(self, "devdoc", False):
            return [Issue("warning", "форма",
                          f"«{self.title}» генерируется как .docx отдельной командой "
                          f"`ecodoc devdoc {self.code}` (или кнопкой «Сгенерировать (.docx)» "
                          f"в GUI), не через обычный generate.")]
        return super().validate()


@register
class PNOOLR(_Dev):
    code = "pnoolr"
    title = "ПНООЛР — проект нормативов образования отходов и лимитов"
    devdoc = True        # расчётная часть: ecodoc/development/pnoolr.py


@register
class HazardClassCalc(_Dev):
    code = "hazard-class"
    title = ("Расчёт класса опасности отхода (пр. МПР № 158) — калькулятор во "
             "вкладке «Сервис», там же кнопка «Оформить расчёт (.docx)»")
    implemented = False   # интерактивный калькулятор в GUI (Сервис), не форма-генератор


@register
class NMUPlan(_Dev):
    code = "nmu"
    title = ("План мероприятий по снижению выбросов в периоды НМУ "
             "(пр. МПР № 662 и № 651 от 11.2025, № 811 утратил силу) — .docx")
    devdoc = True   # генерируется как .docx через api_devdoc / ecodoc devdoc nmu


@register
class PLARN(_Dev):
    code = "plarn"
    devdoc = True        # генератор: ecodoc/development/plarn.py (ПП РФ № 2451)
    title = ("ПЛАРН — план предупреждения и ликвидации разливов нефти и "
             "нефтепродуктов (ПП РФ № 2451)")


@register
class DVOS(_Dev):
    code = "dvos"
    devdoc = True        # генератор: ecodoc/development/dvos.py (пр. № 117)
    title = ("ДВОС — декларация о воздействии на окружающую среду, II категория "
             "(форма — приказ Минприроды № 117 от 19.03.2025)")


@register
class AirInventory(_Dev):
    code = "air-inventory"
    title = "Инвентаризация источников выбросов (пр. МПР № 871)"
    devdoc = True        # генерируется: ecodoc/development/air_inventory.py


@register
class WasteInventory(_Dev):
    code = "waste-inventory"
    title = "Инвентаризация отходов (перечень по объекту)"
    devdoc = True        # генерируется: ecodoc/development/waste_inventory.py


@register
class WastePassportDoc(_Dev):
    code = "waste-passport"
    title = "Паспорта отходов I–IV класса (пр. МПР № 1026)"
    devdoc = True        # генерируется: ecodoc/development/waste_passport.py


@register
class PEKProgram(_Dev):
    code = "pek-program"
    title = "Программа ПЭК (разработка, пр. МПР № 109) — .docx"
    devdoc = True   # генерируется как .docx через api_devdoc / ecodoc devdoc pek-program


@register
class TUWaste(_Dev):
    code = "tu-waste"
    devdoc = True        # письмо-запрос: ecodoc/development/tu_waste.py
    title = "ТУ / письма о технических условиях (грунты, отходы строительства)"


@register
class OOSVolume(_Dev):
    code = "oos"
    devdoc = True        # текстовая часть раздела: ecodoc/development/oos.py
    title = ("Раздел ООС — перечень мероприятий по охране окружающей среды "
             "(ПП РФ № 87, п. 25)")


@register
class NDVVolume(_Dev):
    code = "ndv"
    title = ("Том НДВ — сборка во вкладке «УПРЗА»: выгрузка источников → "
             "расчёт в «Экологе» → загрузка результатов → том .docx")
    implemented = False   # собирается кнопкой «Собрать том» во вкладке УПРЗА


@register
class NDSVolume(_Dev):
    code = "nds"
    title = "Том НДС — сборка во вкладке «УПРЗА» (кнопка «Собрать том»)"
    implemented = False


