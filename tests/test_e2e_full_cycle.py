"""Сквозной прогон: документы → данные → выбор → генерация всех форм.

Требование ТЗ: «Прогони генерацию по примеру». Здесь весь путь эколога на
данных, похожих на реальные (ИП Миних, объект 41-0247-005048-П), но в
изолированном рабочем пространстве — без обращения к ИИ и к сети.
"""
from decimal import Decimal

import pytest

from ecodoc.core import registry, workspace
from ecodoc.core.models import Medium, Pollutant, WasteAct, WasteFlow
from ecodoc.intake import candidates as cd
from ecodoc.intake import crosscheck as cc
from ecodoc.intake import intake

ORG, SITE = "ИП Миних Елена Анатольевна", "Промзона Янино"


@pytest.fixture()
def site(tmp_path, make_pdf, monkeypatch):
    monkeypatch.setenv("ECODOC_RESULTS", str(tmp_path / "результаты"))
    workspace.add_org(ORG)
    workspace.add_site(ORG, SITE, address="Ленинградская обл., Промзона Янино")
    docs = [
        make_pdf(tmp_path / "выписка.pdf",
                 ["Выписка ЕГРЮЛ",
                  "ИНН 780600114472 ОГРН 307784705100221 ОКТМО 41612155"]),
        make_pdf(tmp_path / "свидетельство.pdf",
                 ["Свидетельство о постановке на учёт",
                  "Объект НВОС 41-0247-005048-П, Промзона Янино"]),
        make_pdf(tmp_path / "счёт.pdf",          # чужие реквизиты — конфликт
                 ["Счёт-фактура", "ИНН 7801234564"]),
    ]
    intake.run([str(d) for d in docs], org=ORG, site=SITE, use_ai=False)
    return tmp_path


def test_full_cycle(site, tmp_path):
    # 1. ЗАГРУЗКА: данные извлечены, листы-источники сняты
    from ecodoc.intake import sources
    site_dir = workspace.site_dir(ORG, SITE)
    docs = sources.load(site_dir)["docs"]
    assert len(docs) == 3
    assert any(rec.get("images") for rec in docs.values()), "нет сканов листов"

    # 2. ДАННЫЕ: ИНН разошёлся между выпиской и счётом — программа спрашивает
    ctx = workspace.load_context(ORG, SITE)
    store = cd.Store(site_dir)
    groups = {g.key: g for g in cc.group(store.items, ctx)}
    assert groups["organization.inn"].status == cc.CONFLICT
    assert cc.decide(ctx, store, "organization.inn", "780600114472")
    assert cc.decide(ctx, store, "organization.ogrn", "307784705100221")
    assert cc.decide(ctx, store, "organization.oktmo", "41612155")

    # 3. ОБЪЕКТ: код НВОС распознан и признан верным
    from ecodoc.core import nvos
    assert [o.code for o in ctx.objects] == ["41-0247-005048-П"]
    assert nvos.is_valid(ctx.objects[0].code)

    # 4. ОТХОДЫ: справки-акты → движение пересчитывается автоматически
    ctx.period.year = 2025
    ctx.waste_acts = [
        WasteAct(fkko_code="47110101521", name="Лампы ртутные", hazard_class=1,
                 mass=Decimal("0.052"), operation="обезвреживание",
                 receiver="ООО «Меркурий»", date="15.02.2025"),
        WasteAct(fkko_code="73310001724", name="Мусор офисный", hazard_class=4,
                 mass=Decimal("1.9"), operation="размещение",
                 receiver="Полигон ТБО", date="20.03.2025"),
    ]
    ctx.extra["waste_passports"] = [{"fkko": "47110101521", "name": "Лампы ртутные",
                                     "hazard_class": 1,
                                     "components": [{"name": "ртуть", "percent": "0.02"}]}]
    air = Pollutant(code="0301", name="Азота диоксид", mass_norm=Decimal("0.412"))
    air.medium = Medium.AIR
    ctx.pollutants = [air]
    ctx.extra["emission_sources"] = [{"number": "0001", "name": "Котельная",
                                      "pollutants": [{"code": "0301", "t_year": "0.412"}]}]
    workspace.save_context(ORG, SITE, ctx)

    ctx = workspace.load_context(ORG, SITE)          # apply_acts на загрузке
    moved = {w.fkko_code: w for w in ctx.wastes}
    assert moved["47110101521"].generated == Decimal("0.052")
    assert moved["73310001724"].transferred == Decimal("1.9")

    # 5. Проверка ФККО и комплектности протоколов
    from ecodoc.core import fkko
    fkko.seed_builtin()
    checks = {r["code"]: r for r in fkko.check_context(ctx)}
    assert all(r["ok"] for r in checks.values())
    gaps = " | ".join(cc.lab_gaps(ctx))
    assert "IV класс" in gaps                        # у мусора нет протокола КХА

    # 6. ОТЧЁТНОСТЬ: все реализованные формы собираются
    registry.load_all()
    out_dir = tmp_path / "формы"
    made = []
    for code, cls in registry.all_reports().items():
        report = cls(ctx)
        if not getattr(report, "implemented", True):
            continue
        path = report.render_print(out_dir / f"{code}.xlsx")
        assert path.exists() and path.stat().st_size > 3000, code
        made.append(code)
    assert set(made) >= {"declaration-nvos", "waste-movement", "pek", "2tp-waste",
                         "2tp-air", "2tp-water", "cadastre-spb",
                         "waste-report-iii", "4-oos"}

    # 7. РАЗРАБОТКА: документы контура разработки
    from ecodoc.development import (air_inventory, pnoolr, tu_waste,
                                    waste_inventory, waste_passport)
    assert waste_inventory.generate(ctx, out_dir / "инв_отходов.xlsx").exists()
    assert air_inventory.generate(ctx, out_dir / "инв_выбросов.xlsx").exists()
    assert pnoolr.generate(ctx, out_dir / "пноолр.xlsx").exists()
    assert tu_waste.generate(ctx, out_dir / "ту.docx").exists()
    passports = waste_passport.generate(ctx, out_dir / "паспорта")
    assert len(passports) == 2                       # I и IV класс

    # 8. Сводная по отходам с разбивкой по периодам
    from ecodoc.core.waste_summary import build_rows, build_xlsx
    rows = {r["fkko"]: r for r in build_rows(ctx, 2025)}
    assert rows["47110101521"]["mass_q"][1] == Decimal("0.052")   # I квартал
    assert rows["73310001724"]["mass_m"][3] == Decimal("1.9")     # март
    assert build_xlsx(ctx, out_dir / "сводная.xlsx").exists()

    # 9. Пакет к подаче в ЛКПП
    from ecodoc.submit import build_package
    res = build_package(registry.get("2tp-waste")(ctx), out_dir / "пакет")
    assert res["checklist"].exists() and res["files"]


def test_storage_switch_moves_data(site, tmp_path, monkeypatch):
    """Переключение «общая база ↔ этот компьютер» переносит данные.

    Тест НИЧЕГО не пишет в настоящие папки: домашний каталог, OneDrive и файл
    настроек подменены на временные (однажды такой тест уже переключил режим
    хранения на живой машине — поэтому изоляция здесь явная и проверяется)."""
    from pathlib import Path as _Path

    src = workspace.root()
    fake_home = tmp_path / "домашняя"
    (fake_home / "OneDrive").mkdir(parents=True)
    monkeypatch.setattr(workspace.Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setenv("ECODOC_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(workspace, "_onedrive", lambda: fake_home / "OneDrive")
    monkeypatch.setattr(workspace, "root", lambda: src)     # источник — база теста
    monkeypatch.setattr(workspace, "_ROOT_CACHE", None)

    # настройки пишутся в изолированный файл, а не в ~/.ecodoc
    assert workspace._ui_path().parent == tmp_path / "cfg"

    res = workspace.set_storage_mode("local")
    assert res["mode"] == "local"
    moved = _Path(res["root"]) / workspace.slug(ORG) / workspace.slug(SITE)
    assert (moved / "context.json").exists()
    assert str(moved).startswith(str(fake_home))            # только во временную
    assert src.exists(), "исходная база должна остаться на месте"

    back = workspace.set_storage_mode("shared")
    assert back["mode"] == "shared" and "OneDrive" in back["root"]
