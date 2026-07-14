"""Хелперы генерации и (опциональной) валидации XML через lxml."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from lxml import etree


def el(parent, tag: str, text=None, **attrs):
    """Создать дочерний элемент с текстом и атрибутами."""
    e = etree.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    for k, v in attrs.items():
        if v is not None:
            e.set(k, str(v))
    return e


def _guid(*parts: str) -> str:
    """Детерминированный 32-символьный идентификатор (формат ID_ORG/ID_EO)."""
    return hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


_NVOS_RE = re.compile(r"^\s*\d{2}-\d{4}-\d{5,7}-[ПТОЛ]\s*$")


def _is_nvos_code(code: str) -> bool:
    """Похоже ли на рег.код объекта НВОС (NN-NNNN-NNNNNN-П/Т/О/Л)."""
    return bool(_NVOS_RE.match(str(code or "")))


def data_packet_ni(ctx, doc_type: int, body_fn, *, exp_date: str,
                   program: str = "AdiPNV 4.9.1", version: str = "1.8",
                   rpt_period: int = 0):
    """Собрать XML-конверт «Модуля природопользователя» РПН (DATA_PACKET_NI).

    Формат, который импортирует Модуль природопользователя: общий конверт
    ORG_INFO (реквизиты + ОКВЭД + объекты НВОС) + тело конкретной формы
    (RPT_2TP_WASTE и т.п.), которое дописывает `body_fn(org_info, object_el)`,
    + CHECKSUM.

    doc_type — тип документа (3 = 2-ТП отходы). exp_date — строка ISO-8601
    (передаётся снаружи ради детерминизма тестов).

    ВНИМАНИЕ: CHECKSUM (MD5) вычисляется нашим инструментом как хэш тела
    ORG_INFO. Точный алгоритм контрольной суммы Модуля закрыт — проверьте
    импорт файла в самом Модуле; при отказе Модуль обычно пересчитывает
    сумму при повторном сохранении. ОКАТО подставляется из ОКТМО (близкий,
    но иной классификатор — при необходимости поправьте).
    """
    o = ctx.organization
    e = ctx.extra if isinstance(ctx.extra, dict) else {}
    year = ctx.period.year or ""
    okato = o.oktmo or ""
    # ИП определяется по длине ИНН (12 знаков = ИП/физлицо, 10 = ЮЛ);
    # у ИП нет КПП, ОГРН — это ОГРНИП.
    is_ip = o.is_individual

    # код территориального органа РПН — из данных площадки (extra.rpn_to);
    # жёсткая «1» была неверна для организаций других регионов
    rpn_to = str(e.get("rpn_to", "") or "1")
    root = etree.Element("DATA_PACKET_NI", Version=version, Program=program,
                         ExpDate=exp_date, DocType=str(doc_type), RPN_TO=rpn_to,
                         YEAR=str(year), RPT_PERIOD=str(rpt_period),
                         CALC_TYPE="0", NUMB_COR_RPT="",
                         INN=o.inn or "", KPP="" if is_ip else (o.kpp or ""),
                         OGRN=o.ogrn or "")
    org = etree.SubElement(root, "ORG_INFO")
    el(org, "ID_ORG", _guid(o.inn, "org"))
    el(org, "FNAME", o.name)
    el(org, "SNAME", o.short_name or o.name)
    el(org, "FINDIVID", "true" if is_ip else "false")
    el(org, "INN", o.inn)
    el(org, "OGRN", o.ogrn)
    el(org, "REG_DATE", e.get("reg_date", ""))
    el(org, "KPP", "" if is_ip else o.kpp)
    el(org, "ADDJ_OKATO", okato)
    el(org, "ADDJ_INDEX", e.get("index", ""))
    el(org, "ADDR_JUR", o.address)
    el(org, "ADDJ_STREET", "")
    el(org, "ADDF_OKATO", okato)
    el(org, "ADDF_INDEX", e.get("index", ""))
    el(org, "ADDR_FACT", o.address)
    el(org, "ADDF_STREET", "")
    el(org, "PHONE", o.phone)
    el(org, "ORG_SCALE", "0")
    el(org, "CHIEF", o.director_name)
    el(org, "SEP_DIV", "false")
    el(org, "OKPO", o.okpo)
    el(org, "MANUFACTURER", "false")
    el(org, "IMPORTER", "false")
    el(org, "ENTRY_DATE", e.get("reg_date", ""))
    codes = [c.strip() for c in (o.okved or "").replace(";", ",").split(",") if c.strip()]
    for i, code in enumerate(codes):
        okv = el(org, "OKVED")
        el(okv, "OKVED_CODE", code)
        if i == 0:
            el(okv, "IS_MAIN", "true")
    # объект(ы) НВОС
    obj_el = None
    for ob in (ctx.objects or [None]):
        eo = etree.SubElement(org, "EMISS_OBJECT")
        eo_id = _guid(o.inn, ob.code if ob else "eo")
        el(eo, "ID_EO", eo_id)
        el(eo, "NAME_EO", (ob.name or ob.address) if ob else o.address)
        el(eo, "OKATO", (ob.oktmo if ob else "") or okato)
        el(eo, "ADDR_EO", (ob.address if ob else "") or o.address)
        el(eo, "OBJ_EXPLOITATION", "1")
        el(eo, "URBAN_AIR", "true")
        el(eo, "AREA_INFO", "0")
        el(eo, "POPUL_LOC", "true")
        el(eo, "DRINK_WTS", "false")
        el(eo, "OBJ_AREA_TYPE", "5")
        el(eo, "IS_BOAT", "false")
        # объект на учёте НВОС, если задан его рег.код (напр. «41-0247-000123-П»)
        reg = _is_nvos_code(ob.code if ob else "")
        if reg:
            el(eo, "REG_NUMBER", ob.code)
        el(eo, "NOT_REG_OBJ", "false" if reg else "true")
        if obj_el is None:
            obj_el = (ob, eo_id)
    body_fn(org, obj_el, exp_date)
    checksum = hashlib.md5(etree.tostring(org)).hexdigest().upper()
    el(root, "CHECKSUM", checksum)
    return root


def write_tree(root, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree = etree.ElementTree(root)
    tree.write(
        str(out_path),
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )
    return out_path


def validate_against_xsd(xml_path: Path, xsd_path: Path) -> list[str]:
    """Проверить XML по официальной XSD. Вернуть список ошибок (пусто = ОК).

    XSD-схемы РПН не входят в комплект — положите .xsd рядом и укажите путь.
    """
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    doc = etree.parse(str(xml_path))
    if schema.validate(doc):
        return []
    return [str(e) for e in schema.error_log]
