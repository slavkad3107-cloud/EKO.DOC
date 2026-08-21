"""Санитар: код вещества сверяется с наименованием по официальному перечню.

На реальной базе OCR дал «0325 Керосин» (0325 — мышьяк), «0333 Азот (II)
оксид» (0333 — сероводород), «3003 диоксид серы» (кода нет) — дубли
настоящих веществ под чужими кодами. Правильные записи трогать нельзя."""
from decimal import Decimal

from ecodoc.core import sanitize
from ecodoc.core.models import Medium, Pollutant, ReportContext


def _v(code, name):
    return sanitize.check_substance(code, name, "air")


def test_wrong_code_fixed_to_unique_match():
    assert _v("0325", "Керосин (Керосин прямой перегонки)").code == "2732"
    assert _v("0333", "Азот (II) оксид (Азот монооксид)").code == "0304"
    assert _v("3003", "диоксид серы").code == "0330"
    assert _v("3004", "диоксид азота").code == "0301"
    assert _v("3332", "оксид углерода").code == "0337"
    v = _v("0325", "Керосин")
    assert v.ok and v.suspect and "0325" in v.reason and "2732" in v.reason


def test_correct_records_untouched():
    """Морфология («углерод»/«углерода») и общие слова не должны ломать верное."""
    for code, name in [("337", "Углерод оксид"), ("0401", "Углеводороды"),
                       ("2907", "Пыль неорганическая >70% SiO2"),
                       ("0301", "Азота диоксид"), ("0328", "Углерод (сажа)"),
                       ("0123", "диЖелезо триоксид (Железа оксид)"),
                       ("2902", "Взвешенные вещества"), ("0703", "Бенз(а)пирен"),
                       ("0349", "HCl")]:
        v = _v(code, name)
        assert v.ok and not v.suspect, (code, name, v.reason)
        assert v.code == code.zfill(4)


def test_ambiguous_name_not_rewritten():
    """Если кандидатов несколько или нет — код не трогаем, только помечаем."""
    v = _v("0340", "Фтористые газообразные соединения")   # 0340 нет в перечне
    assert v.ok and v.code == "0340"


def test_clean_merges_fixed_duplicates_and_reports_mass_conflict():
    ctx = ReportContext()
    for code, name, mass in [("0330", "Сера диоксид", "0.16"),
                             ("3003", "диоксид серы", "0.000018"),
                             ("0337", "Углерод оксид", "1.45"),
                             ("0337", "Углерода оксид (угарный газ)", "3")]:
        ctx.pollutants.append(Pollutant(code=code, name=name, medium=Medium.AIR,
                                        mass_norm=Decimal(mass)))
    rep = sanitize.clean_context(ctx)
    codes = sorted(p.code for p in ctx.pollutants)
    assert codes == ["0330", "0337"]                 # дубли слиты
    co = next(p for p in ctx.pollutants if p.code == "0337")
    assert co.mass_norm == Decimal("1.45")           # первая, а не большая
    conflicts = rep.get("mass_conflicts") or []
    assert any(c["code"] == "0337" and c["dropped"] == "3" for c in conflicts)
