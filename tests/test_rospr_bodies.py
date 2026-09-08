"""Территориальные органы Росприроднадзора (data/rospr_bodies.json) и
определение органа для титула декларации по любому признаку региона."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecodoc.core.models import Organization, ReportContext, NVOSObject
from ecodoc.reports.declaration_nvos import editions
from ecodoc.reports.declaration_nvos.editions import rosprirodnadzor_for
from ecodoc.reports.declaration_nvos.report import DeclarationNVOS


def test_directory_covers_all_subjects():
    data = json.loads((ROOT / "data" / "rospr_bodies.json").read_text(encoding="utf-8"))
    bodies = data["bodies"]
    assert len(bodies) >= 30 and data["source"].startswith("https://rpn.gov.ru")
    seen: dict[str, str] = {}
    for b in bodies:
        assert b["name"] and b["full"].count("Федеральной службы по надзору в сфере природопользования") == 1
        for s in b["subjects"]:
            assert s not in seen, f"субъект {s} у двух органов: {seen[s]} / {b['name']}"
            seen[s] = b["name"]
    # все субъекты РФ из таблицы регионов резолвера ОКТМО закрыты
    from ecodoc.parsers.oktmo import REGIONS
    missing = {s for _p, s, _n, _r in REGIONS} - set(seen)
    assert not missing, missing


def test_lookup_by_subject_prefix_oktmo_nvos_and_address(monkeypatch):
    monkeypatch.setenv("ECODOC_OFFLINE", "1")
    nw = "Северо-Западное межрегиональное управление Федеральной службы по надзору в сфере природопользования"
    assert rosprirodnadzor_for("78") == nw                       # код субъекта СПб
    assert rosprirodnadzor_for("40") == nw                       # префикс ОКТМО СПб
    assert rosprirodnadzor_for("47") == nw and rosprirodnadzor_for("41") == nw
    assert rosprirodnadzor_for("", "40375000") == nw             # по ОКТМО
    assert rosprirodnadzor_for(nvos_code="40-0178-001234-П") == nw
    assert rosprirodnadzor_for(nvos_code="41-0147-001234-П") == nw
    assert rosprirodnadzor_for(address="Санкт-Петербург, МО Новоизмайловское, Варшавская ул., 16") == nw
    assert "Москве и Калужской" in rosprirodnadzor_for("77")
    assert "Московской и Смоленской" in rosprirodnadzor_for("50")   # бывшее Центральное МУ
    # двузначный код читаем как префикс ОКТМО (как nvos.subject_code): 65 — Свердловская
    assert "Уральское" in rosprirodnadzor_for("65")
    assert "Ярослав" not in rosprirodnadzor_for("78")            # 78 — субъект, не префикс ОКТМО
    assert "Верхне-Волжское" in rosprirodnadzor_for("", "78701000")   # ОКТМО 78… — Ярославль
    assert rosprirodnadzor_for("78", full=False).endswith("Росприроднадзора")
    assert rosprirodnadzor_for("XX") == ""                       # заглушка — не регион
    assert rosprirodnadzor_for("") == ""


def test_declaration_title_body_from_site_address(monkeypatch):
    """Технострой: объект-заглушка «XX-XXXX-…», ОКТМО пустой — орган берём по
    адресу площадки; предупреждение «не определён территориальный орган» уходит."""
    monkeypatch.setenv("ECODOC_OFFLINE", "1")
    ctx = ReportContext(
        organization=Organization(name="ООО Т", inn="7841500188", ogrn="1147847124006",
                                  address="198516, г.Санкт-Петербург, г.Петергоф, "
                                          "Санкт-Петербургский пр-кт, д.60"),
        extra={"report_year": 2026,
               "site_address": "Проектирование строительства школы по адресу: "
                               "Санкт-Петербург, Муниципальный округ Новоизмайловское, "
                               "Варшавская ул., участок 16"})
    ctx.objects = [NVOSObject(name="Площадка", code="XX-XXXX-XXXXXX-Б", region_code="XX")]
    rep = DeclarationNVOS(ctx)
    assert "Северо-Западное" in rep._rospr_name()
    assert not any("территориальный орган" in i.message for i in rep.validate())
    # явное имя пользователя приоритетнее
    ctx.extra["declaration"] = {"rospr": "Моё управление"}
    assert DeclarationNVOS(ctx)._rospr_name() == "Моё управление"


def test_legacy_dict_kept():
    assert set(editions.ROSPRIRODNADZOR) == {"78", "47", "77", "50"}
    assert all(editions.ROSPRIRODNADZOR.values())
