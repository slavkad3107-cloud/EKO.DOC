"""«Что подготовить» (intake/requirements.docs_needed): не требовать то, что
уже есть в базе — замечание эколога 08.09.2026."""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecodoc.core.models import Medium, Organization, Pollutant, ReportContext
from ecodoc.intake import requirements


def _ctx(full_requisites=True, with_masses=True):
    org = Organization(name="ООО Т", inn="7841500188", ogrn="1147847124006",
                       address="СПб, Петергоф, Санкт-Петербургский пр., 60",
                       director_name="Салихов Д. Р.")
    if not full_requisites:
        org.ogrn = ""
    ctx = ReportContext(organization=org, extra={"report_year": 2026})
    if with_masses:
        ctx.pollutants = [Pollutant(code="0301", name="Азота диоксид", medium=Medium.AIR,
                                    mass_norm=Decimal("0.004815"), source="ООС")]
    return ctx


def test_egrul_not_required_when_requisites_filled():
    _missing, docs = requirements.check(_ctx(), "declaration-nvos")
    assert not any("ЕГРЮЛ" in d for d in docs)
    _missing, docs = requirements.check(_ctx(full_requisites=False), "declaration-nvos")
    assert any("ЕГРЮЛ" in d for d in docs)


def test_emission_masses_from_oos_ask_for_confirmation_only():
    _missing, docs = requirements.check(_ctx(), "declaration-nvos")
    assert not any(d == "данные учёта выбросов/сбросов за год" for d in docs)
    hint = [d for d in docs if "массы взяты из" in d]
    assert len(hint) == 1 and "ООС" in hint[0] and "журналом учёта" in hint[0]
    # без масс — документ по-прежнему нужен
    _missing, docs = requirements.check(_ctx(with_masses=False), "declaration-nvos")
    assert "данные учёта выбросов/сбросов за год" in docs


def test_check_all_keeps_shape():
    out = requirements.check_all(_ctx())
    assert "declaration-nvos" in out and isinstance(out["declaration-nvos"], list)
