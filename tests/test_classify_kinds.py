"""Классификация документов: машинные коды kind, проектная документация,
классификация только по имени файла и doc_type в реестре источников."""
from pathlib import Path

from ecodoc.intake import classify, sources
from ecodoc.parsers.text_extract import ExtractedDoc


def _doc(name: str, text: str) -> ExtractedDoc:
    return ExtractedDoc(Path(name), text, [text], "pdf-text")


def test_oos_by_text_is_project():
    """Раньше ООС падал в «не распознано»; в тексте полно слов «акт»/«размещени»
    — общие правила справок его не должны перехватывать."""
    text = ("Раздел 8. Перечень мероприятий по охране окружающей среды. "
            "Характеристика отходов: фактический объём размещения отходов "
            "приведён в таблице 8.1. Утилизация — по актам операторов.")
    c = classify.classify(_doc("том8.pdf", text))
    assert c.kind == "oos" and c.project
    assert "ООС" in c.doc_type


def test_pnoolr_ndv_and_others_by_text():
    assert classify.classify(_doc("x.docx",
                                  "Проект нормативов образования отходов и лимитов "
                                  "на их размещение (ПНООЛР)")).kind == "pnoolr"
    assert classify.classify(_doc("x.pdf", "Проект НДВ для ООО Ромашка")).kind == "ndv"
    assert classify.classify(_doc("x.pdf",
                                  "Инвентаризация отходов производства и потребления")
                             ).kind == "inventory_waste"
    assert classify.classify(_doc("x.pdf", "Проект рекультивации нарушенных земель")
                             ).kind == "recultivation"
    assert classify.classify(_doc("x.pdf",
                                  "Заключение государственной экологической экспертизы")
                             ).kind == "expertise"
    assert classify.classify(_doc("x.pdf",
                                  "Протокол общественных обсуждений по ОВОС")
                             ).kind == "hearings"
    assert classify.classify(_doc("x.pdf",
                                  "Отчёт об организации и о результатах осуществления "
                                  "производственного экологического контроля")
                             ).kind == "pek_report"
    assert classify.classify(_doc("x.pdf", "Программа ПЭК")).kind == "pek_program"


def test_old_rules_keep_kinds_and_are_not_project():
    act = classify.classify(_doc("x.pdf", "Справка об утилизации отходов"))
    assert act.kind == "act" and not act.project
    assert classify.classify(_doc("x.pdf", "Протокол КХА № 5")).kind == "protocol_kha"
    assert classify.classify(_doc("x.pdf", "Паспорт отхода")).kind == "passport"
    assert classify.classify(_doc("x.pdf", "Договор № 1")).kind == "contract"
    unknown = classify.classify(_doc("x.pdf", "текст ни о чём"))
    assert unknown.kind == "other" and not unknown.project


def test_docclass_defaults_keep_old_calls_working():
    dc = classify.DocClass("тип", "данные", [])
    assert dc.kind == "other" and dc.project is False


def test_classify_name_by_filename_only():
    cases = {
        "ООС.pdf": "oos", "ПМООС_том8.pdf": "oos", "ООС.pdf (лист 3)": "oos",
        "ПНООЛР 2025.docx": "pnoolr", "проект НДВ.pdf": "ndv",
        "паспорт ТБО.pdf": "passport", "П.о.о ТБО.pdf": "passport",
        "протокол КХА.pdf": "protocol_kha", "БИО_26312.pdf": "biotest",
        "акт №5.pdf": "act", "справка об утилизации.pdf": "act",
        "лицензия.pdf": "license", "договор.pdf": "contract",
        "журнал 1028.xlsx": "journal", "выписка ЕГРЮЛ.pdf": "egrul",
        "инвентаризация отходов.docx": "inventory_waste",
        "инвентаризация ИЗАВ.xlsx": "inventory_air",
        "рекультивация.pdf": "recultivation",
        "заключение экспертизы.pdf": "expertise",
        "обсуждения.pdf": "hearings",
        "характеристика.pdf": "other",       # «акт» внутри слова — не акт
        "справка по отходам.pdf": "act",     # «по» — не «П.О.О»
        "006_1.jpg": "other",
    }
    for name, kind in cases.items():
        assert classify.classify_name(name).kind == kind, name
    assert classify.classify_name("ООС.pdf").project
    assert not classify.classify_name("акт №5.pdf").project


def test_render_marks_project_docs():
    out = classify.render([_doc("ООС.pdf", "Перечень мероприятий по охране "
                                           "окружающей среды")])
    assert "проектная документация" in out


def test_sources_kind_of_uses_doc_type_then_name(tmp_path):
    sources.remember(tmp_path, "a" * 40, file="документ.pdf", doc_type="oos")
    sources.remember(tmp_path, "b" * 40, file="старый акт.pdf")   # без doc_type
    assert sources.kind_of(tmp_path, "документ.pdf") == "oos"
    assert sources.kind_of(tmp_path, "документ.pdf (лист 2)") == "oos"
    assert sources.kind_of(tmp_path, "старый акт.pdf") == "act"
    assert sources.kind_of(tmp_path, "нет такого ПНООЛР.pdf") == "pnoolr"
    assert sources.kind_of(tmp_path, "") == "other"


def test_snap_sources_writes_doc_type(tmp_path, monkeypatch):
    """_snap_sources кладёт в sources.json машинный класс документа."""
    from ecodoc.ai.analyzer import ExtractionReport
    from ecodoc.core import workspace
    from ecodoc.core.models import ReportContext
    from ecodoc.intake import intake

    workspace.add_org("Орг")
    workspace.add_site("Орг", "Пл")
    site_dir = workspace.site_dir("Орг", "Пл")
    att = site_dir / "attachments"
    att.mkdir(parents=True, exist_ok=True)
    f = att / "ООС.txt"
    f.write_text("Перечень мероприятий по охране окружающей среды", encoding="utf-8")
    doc = _doc(str(f), f.read_text(encoding="utf-8"))
    intake._snap_sources([doc], ExtractionReport(), ReportContext(), "Орг", "Пл")
    rec = next(iter(sources.load(site_dir)["docs"].values()))
    assert rec["file"] == "ООС.txt" and rec["doc_type"] == "oos"
    assert sources.kind_of(site_dir, "ООС.txt") == "oos"
