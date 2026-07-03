"""Хелперы генерации и (опциональной) валидации XML через lxml."""
from __future__ import annotations

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
