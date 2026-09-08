"""Ставки платы за НВОС: справочник (ПП 913 / Распоряжение 2409-р в ред. 4110-р),
проверка новизны в интернете (сеть подменяется) и обновление из документа."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ecodoc.core import rates_update
from ecodoc.core.refdata import rates_nvos


# ── справочник ───────────────────────────────────────────────────────────────

def test_rates_2026_have_acrolein_and_wood_dust():
    """1301 акролеин и 2936 пыль древесная есть в ПП 913 / 2409-р — ставка
    должна быть (замечание эколога: «нет ставки» по ним — ошибка)."""
    air = rates_nvos()["rates_by_year"]["2026"]["air"]
    assert air["1301"]["rate"] == 983
    assert air["2936"]["rate"] == 65.5 and air["2936"]["as_code"] == "2902"
    assert air["2907"]["rate"] == air["2908"]["rate"] == air["2909"]["rate"] == 196.6
    assert air["0301"]["rate"] == 219              # Азота диоксид, контрольная
    # для 2027-2030 те же коды присутствуют
    for y in ("2027", "2028", "2029", "2030"):
        a = rates_nvos()["rates_by_year"][y]["air"]
        assert "1301" in a and "2936" in a


def test_unrated_explanations():
    """2799 масло хлопковое и 0401 углеводороды (группа) — ставки в перечне
    нет: предупреждение говорит именно это, а не «нет в справочнике»."""
    unr = rates_nvos()["unrated"]
    assert "отсутствует" in unr["2799"] and "не начисляется" in unr["2799"]
    assert "0401" in unr and "компонентам" in unr["0401"]


def test_calc_warnings_for_tehnostroy_like_substances():
    from ecodoc.core.models import Medium, Organization, Pollutant, ReportContext
    from ecodoc.reports.declaration_nvos.calc import calculate
    ctx = ReportContext(
        organization=Organization(name="Т", inn="7801234564", oktmo="40375000"))
    ctx.period.year = 2026
    ctx.pollutants = [
        Pollutant(code="1301", name="Проп-2-ен-1-аль", medium=Medium.AIR, mass_norm=0.1),
        Pollutant(code="2936", name="Пыль древесная", medium=Medium.AIR, mass_norm=0.1),
        Pollutant(code="2799", name="Масло хлопковое", medium=Medium.AIR, mass_norm=0.1),
        Pollutant(code="0401", name="Углеводороды", medium=Medium.AIR, mass_norm=0.1),
    ]
    res = calculate(ctx)
    text = "\n".join(res.warnings)
    assert "нет ставки" not in text
    assert "в перечне ставок платы отсутствует" in text       # 2799
    assert "суммарный/групповой код" in text                  # 0401
    by = {l.code: l for l in res.lines}
    assert by["1301"].rate > 0 and by["2936"].rate > 0
    assert by["2799"].amount == 0 and by["0401"].amount == 0


# ── проверка новизны (без сети) ──────────────────────────────────────────────

CONSULTANT_HTML = ("<html><title>Распоряжение Правительства РФ от 01.09.2025 N 2409-р "
                   "(ред. от 26.12.2025) \\ КонсультантПлюс</title><body>"
                   "Распоряжение Правительства РФ от 01.09.2025 N 2409-р (ред. от 26.12.2025)"
                   "</body></html>")
PRAVO_HTML = """<html><body><div>
<a>Постановление Правительства Российской Федерации от 27.12.2025 № 2167</a>
<span>"О дополнительных коэффициентах к ставкам платы за негативное воздействие на окружающую среду"</span>
<a>Постановление Правительства Российской Федерации от 22.05.2025 № 710</a>
<span>"Об утверждении Правил исчисления платы за негативное воздействие на окружающую среду при выбросах"</span>
<a>Постановление Правительства Российской Федерации от 17.04.2024 № 492</a>
<span>"О применении в 2024 году ставок платы за негативное воздействие на окружающую среду"</span>
</div></body></html>"""


def _fetch_factory(pages: dict, fail: set = ()):
    def fetch(url, timeout):
        for key, html in pages.items():
            if key in url:
                if key in fail:
                    raise OSError("network down")
                return html.encode("utf-8"), "text/html"
        raise OSError("no such page")
    return fetch


def test_our_act_uses_related_dates():
    ours = rates_update.our_act()
    assert "4110-р" in ours["act"]
    assert ours["date"] >= "2025-12-27"          # учтено и ПП 2167 от 27.12.2025


def test_check_online_up_to_date(monkeypatch):
    monkeypatch.setattr(rates_update, "_fetch", _fetch_factory(
        {"consultant.ru": CONSULTANT_HTML, "pravo.gov.ru": PRAVO_HTML}))
    res = rates_update.check_online(timeout=1)
    assert res["newer"] is False and not res["error"]
    assert res["latest_date"] == "2025-12-27" and "2167" in res["latest_act"]
    assert res["our_act"] and res["url"] and res["checked_at"]
    assert "актуальны" in res["text"]
    assert len(res["sources"]) == 2


def test_check_online_detects_newer(monkeypatch):
    newer = PRAVO_HTML.replace("27.12.2025 № 2167", "15.08.2026 № 1200")
    monkeypatch.setattr(rates_update, "_fetch", _fetch_factory(
        {"consultant.ru": CONSULTANT_HTML, "pravo.gov.ru": newer}))
    res = rates_update.check_online(timeout=1)
    assert res["newer"] is True and res["latest_date"] == "2026-08-15"
    assert "1200" in res["latest_act"] and res["url"].startswith("http://publication.pravo.gov.ru")
    assert "более новая" in res["text"]


def test_check_online_offline_never_raises(monkeypatch):
    monkeypatch.setattr(rates_update, "_fetch", _fetch_factory({}, fail=set()))
    res = rates_update.check_online(timeout=1)
    assert res["newer"] is False and res["error"] and "не удалась" in res["text"]
    assert res["our_date"]


def test_parse_pravo_ignores_unrelated_acts():
    info = rates_update._parse_pravo(PRAVO_HTML)
    assert info["date"] == "2025-12-27" and "2167" in info["act"]
    assert "710" not in info["act"]


# ── обновление ───────────────────────────────────────────────────────────────

@pytest.fixture
def rates_sandbox(tmp_path, monkeypatch):
    """Копия справочника во временной папке: apply пишет туда, не в проект."""
    src = ROOT / "data" / "rates_nvos.json"
    dst = tmp_path / "rates_nvos.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(rates_update, "RATES_PATH", dst)
    return dst


def test_apply_json_table(rates_sandbox):
    new = {"year": 2026, "air": {"0301": {"rate": 230.0}, "9999": {"name": "Новое", "rate": 1.5}}}
    p = rates_sandbox.parent / "new_rates.json"
    p.write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")
    res = rates_update.apply(str(p))
    assert res["ok"] and res["updated"] == 2 and Path(res["backup"]).exists()
    data = json.loads(rates_sandbox.read_text(encoding="utf-8"))
    assert data["rates_by_year"]["2026"]["air"]["0301"]["rate"] == 230.0
    assert data["rates_by_year"]["2026"]["air"]["9999"]["name"] == "Новое"
    assert data["_source_2026"]["last_apply"]["updated"] == 2
    # оригинал в проекте не тронут
    assert rates_nvos()["rates_by_year"]["2026"]["air"]["0301"]["rate"] == 219


def test_apply_text_table_by_name(rates_sandbox):
    text = ("Ставки платы за выбросы\n"
            "1. Азота диоксид 250 300 350 400 450\n"
            "2. Азота оксид 160 200 250 300 350\n"
            "3. Вещество, которого нет 1 2 3 4 5\n")
    p = rates_sandbox.parent / "act.txt"
    p.write_text(text, encoding="utf-8")
    res = rates_update.apply(str(p))
    assert res["ok"] and res["updated"] >= 2
    assert any("которого нет" in u for u in res["unmatched"])
    data = json.loads(rates_sandbox.read_text(encoding="utf-8"))
    assert data["rates_by_year"]["2026"]["air"]["0301"]["rate"] == 250
    assert data["rates_by_year"]["2030"]["air"]["0301"]["rate"] == 450


def test_apply_unreadable_is_honest(rates_sandbox):
    p = rates_sandbox.parent / "scan.txt"
    p.write_text("просто текст без таблицы", encoding="utf-8")
    res = rates_update.apply(str(p))
    assert not res["ok"] and "не распознана" in res["message"]
    assert not list(rates_sandbox.parent.glob("*.bak-*"))      # без бэкапа — ничего не менялось
    assert not rates_update.apply("")["ok"]


def test_parse_rows_single_and_multi():
    rows = rates_update.parse_rows("12 Сера диоксид 78,8\n13. Углерод оксид 3,3 3,6 4,0 4,5 5,0")
    assert rows[0]["rates"] == {2026: 78.8}
    assert rows[1]["rates"][2030] == 5.0 and rows[1]["name"] == "Углерод оксид"


def test_server_rates_api(monkeypatch):
    from ecodoc.gui import server
    monkeypatch.setattr(rates_update, "_fetch", _fetch_factory(
        {"consultant.ru": CONSULTANT_HTML, "pravo.gov.ru": PRAVO_HTML}))
    out = server.api_rates_check({}, {"timeout": 1})
    assert set(out) >= {"latest_act", "our_act", "newer", "url"}
    assert server.STARTUP_NOTES["rates"]["newer"] is False
    assert server.api_meta({}, {})["startup"]["rates"]["checked_at"]
    res = server.api_rates_apply({}, {"url": ""})
    assert res["ok"] is False or res.get("updated") == 0
