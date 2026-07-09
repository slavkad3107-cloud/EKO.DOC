"""ЭкоДок — командная строка.

    python -m ecodoc list
    python -m ecodoc analyze <файлы...> [-o context.json]
    python -m ecodoc generate <форма> -i context.json [-o out_dir]
    python -m ecodoc validate <форма> -i context.json

Типовой сценарий (гибрид):
    1) analyze  — распознать реквизиты из приложенных doc/pdf/jpg в context.json
    2) (вручную) — открыть context.json, проверить и дозаполнить массы/объёмы
    3) generate — получить XML (для ЛКПП) и .xlsx (печатная форма)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ecodoc import __version__
from ecodoc.core import registry, serialize, workspace


def _cmd_list(args):
    registry.load_all()
    print(f"ЭКО.DOC {__version__} (продукт «ЭКО Проект») — модули и формы:\n")
    reports = registry.all_reports()
    print("КОНТУР «ОТЧЁТНОСТЬ» (формы для генерации):")
    for code, cls in reports.items():
        if getattr(cls, "domain", "reporting") != "reporting":
            continue
        mark = "✓" if getattr(cls, "implemented", True) else "○ каркас"
        print(f"  {code:<20} {mark:<10} {cls.title}")
    print("\nКОНТУР «РАЗРАБОТКА» (документы):")
    print(f"  {'waste-passport':<20} {'✓':<10} Паспорта отходов I–IV класса  (команда: passport)")
    print(f"  {'volume:ndv|nds|szz':<20} {'○ каркас':<10} Тома НДВ/НДС/СЗЗ  (команда: volume)")
    print(f"  {'dispersion':<20} {'✓ эксп.':<10} Расчёт рассеивания МРР-2017  (команда: dispersion)")
    for code, cls in reports.items():
        if getattr(cls, "domain", "") != "development":
            continue
        mark = "✓" if getattr(cls, "implemented", True) else "○ каркас"
        print(f"  {code:<20} {mark:<10} {cls.title}")
    print("\nМОДУЛИ: calendar (календарь) · intake (приём документов) · "
          "ai (ИИ-анализ) · watch (сторож форм) · org/site (организации) · "
          "pdf (экспорт PDF)")


def _cmd_analyze(args):
    from ecodoc.parsers.extractor import parse_files, summary

    ctx = parse_files(args.files, ocr=not args.no_ocr)
    print(summary(ctx))
    out = Path(args.output)
    serialize.to_json(ctx, out)
    print(f"\nКонтекст сохранён: {out}")
    print("→ Проверьте и дозаполните его, затем: python -m ecodoc generate <форма> -i", out)


def _load_report(code: str, args):
    registry.load_all()
    try:
        cls = registry.get(code)
    except KeyError:
        sys.exit(f"Неизвестная форма: {code}. Список: python -m ecodoc list")
    return cls(workspace.resolve(args))


def _print_issues(issues) -> bool:
    if not issues:
        print("Валидация: замечаний нет.")
        return True
    errors = [i for i in issues if i.level == "error"]
    for i in issues:
        print(" ", i)
    return not errors


def _cmd_validate(args):
    report = _load_report(args.form, args)
    ok = _print_issues(report.validate())
    sys.exit(0 if ok else 1)


def _cmd_generate(args):
    report = _load_report(args.form, args)
    if not getattr(report, "implemented", True):
        sys.exit(f"Форма «{report.title}» — каркас, генерация пока недоступна.")
    issues = report.validate()
    ok = _print_issues(issues)
    if not ok and not args.force:
        sys.exit("\nЕсть ошибки. Исправьте context.json или запустите с --force.")
    out_dir = workspace.out_dir(args)
    stem = f"{args.form}_{report.ctx.period.year or 'XXXX'}"
    if getattr(report, "has_xml", True):
        xml_path = report.render_xml(out_dir / f"{stem}.xml")
        print(f"XML:    {xml_path}")
    else:
        print("XML:    (форма не выгружается в ЛКПП — только печатная форма)")
    try:
        print_path = report.render_print(out_dir / f"{stem}.xlsx")
        print(f"Печать: {print_path}")
        if args.pdf:
            from ecodoc.render.pdf import to_pdf
            try:
                print(f"PDF:    {to_pdf(print_path)}")
            except RuntimeError as e:
                print(f"PDF:    не удалось ({e})")
    except NotImplementedError:
        print("Печать: (для этой формы не реализована)")


def _cmd_calendar(args):
    from ecodoc.calendar import engine

    ctx = workspace.resolve(args)
    year = args.year or (ctx.period.year + 1 if ctx.period.year else 0)
    if not year:
        sys.exit("Укажите --year или заполните period.year в context.json")
    print(engine.render_console(ctx, year))
    if args.xlsx:
        path = engine.export_xlsx(ctx, year, Path(args.xlsx))
        print(f"\nExcel: {path}")


def _cmd_passport(args):
    from ecodoc.development import waste_passport

    ctx = workspace.resolve(args)
    paths = waste_passport.generate(ctx, args.outdir)
    if not paths:
        print("Отходов I–IV класса в контексте нет — паспорта не требуются.")
        return
    print(f"Сгенерировано паспортов: {len(paths)}")
    for p in paths:
        print("  ", p)


def _cmd_volume(args):
    from ecodoc.development import volume_builder as vb

    ctx = workspace.resolve(args)
    src = vb.VolumeSources()
    if args.sources_xlsx:
        src.sources_header, src.sources_table = vb.ingest_excel(args.sources_xlsx)
    if args.dispersion_xlsx:
        src.dispersion_header, src.dispersion_table = vb.ingest_excel(args.dispersion_xlsx)
    if args.appendix:
        src.appendices = vb.collect_appendices(args.appendix)
    out = Path(args.outdir) / f"том_{args.type}.docx"
    path = vb.build(args.type, ctx, src, out)
    print(f"Том собран: {path}")
    print("⚠ Каркас тома: разделы и реквизиты сгенерированы; таблицы источников и "
          "результаты рассеивания импортируйте из «Эколога» (--sources-xlsx/--dispersion-xlsx).")


def _cmd_org(args):
    if args.action == "add":
        req = {k: getattr(args, k) or "" for k in ("inn", "kpp", "ogrn", "oktmo", "address")}
        name = args.name
        if not name and req["inn"]:
            # только ИНН — реквизиты из ЕГРЮЛ (открытый сервис ФНС)
            from ecodoc.parsers.egrul import lookup
            found = lookup(req["inn"])
            name = found.get("short_name") or found.get("name", "")
            for k in req:
                req[k] = req[k] or found.get(k, "")
            print(f"ЕГРЮЛ: {found.get('name', '')} (ОГРН {found.get('ogrn', '—')})")
        if not name:
            sys.exit("Укажите наименование или --inn: "
                     "python -m ecodoc org add \"ООО Ромашка\" | org add --inn 780...")
        path = workspace.add_org(name, **req)
        print(f"Организация создана: {path}")
        print(f"→ добавьте площадку: python -m ecodoc site add \"{name}\" \"<площадка>\"")
    else:  # list
        tree = workspace.list_tree()
        if not tree:
            print(f"Рабочее пространство пусто ({workspace.root()}). "
                  f"Создайте: python -m ecodoc org add \"ООО Ромашка\" --inn ...")
        for org, sites in tree.items():
            print(f"● {org}")
            for s in sites:
                print(f"    └ {s}")


def _cmd_site(args):
    path = workspace.add_site(args.org, args.name,
                              address=args.address or args.name)
    print(f"Площадка создана: {path.parent}")
    print(f"→ принесите документы: python -m ecodoc intake <файлы> "
          f"--org \"{args.org}\" --site \"{args.name}\"")


def _cmd_intake(args):
    from ecodoc.intake import intake

    ctx = None
    if args.input:
        ctx = serialize.from_json(args.input)
    print(intake.run(args.files, org=args.org or "", site=args.site or "",
                     ctx=ctx, use_ai=args.ai, forms=args.form,
                     ocr=not args.no_ocr))
    if args.input and ctx is not None:
        serialize.to_json(ctx, args.input)
        print(f"Контекст обновлён: {args.input}")


def _cmd_ai(args):
    from ecodoc.ai import detect, load_config

    if args.action == "setup":
        cfg = detect.setup(prefer=args.provider or "")
        print("── Настройка ИИ ──")
        print(detect.describe(cfg))
        if not cfg.provider:
            print("\nЛокальных ИИ не найдено и ключей внешних API нет.\n"
                  "Варианты: установите Ollama (https://ollama.com) и модель\n"
                  "  `ollama pull qwen2.5:7b`, либо задайте ключ, например\n"
                  "  ANTHROPIC_API_KEY / OPENAI_API_KEY / OPENROUTER_API_KEY,\n"
                  "  затем повторите `ecodoc ai setup`.")
    elif args.action == "status":
        print(detect.describe(load_config()))
    else:  # test
        from ecodoc.ai.providers import chat_with_fallback
        cfg = load_config()
        answer, model = chat_with_fallback(
            cfg, "Отвечай кратко, по-русски.",
            args.prompt or "Назови класс опасности отработанных ртутных ламп.")
        print(f"[{model}] {answer}")


def _cmd_watch(args):
    from ecodoc.watch import watcher

    print(watcher.run_check(xsd_dir=args.xsd))


def _cmd_pdf(args):
    from ecodoc.render.pdf import to_pdf

    for f in args.files:
        print(f"PDF: {to_pdf(f)}")


def _cmd_dispersion(args):
    import json as _json

    from ecodoc.development import dispersion as dp

    # utf-8-sig: Блокнот и пр. сохраняют JSON с BOM
    data = _json.loads(Path(args.sources).read_text(encoding="utf-8-sig"))
    raw = (data if isinstance(data, list)
           else data.get("sources", []) if isinstance(data, dict) else [])
    known = dp.PointSource.__dataclass_fields__
    sources = [dp.PointSource(**{k: v for k, v in s.items() if k in known})
               for s in raw]
    if not sources:
        sys.exit("В файле нет источников. Формат: {\"sources\": [{\"name\":..., "
                 "\"H\":10, \"D\":0.5, \"w0\":5, \"Tg\":120, \"Tv\":25, \"M\":1.0}]}")
    pdk = data.get("pdk") if isinstance(data, dict) else None
    print(dp.report(sources, pdk))


def _load_sources_json(path):
    import json as _json
    from ecodoc.development.dispersion_map import MapSource

    data = _json.loads(Path(path).read_text(encoding="utf-8-sig"))
    raw = data if isinstance(data, list) else data.get("sources", [])
    known = MapSource.__dataclass_fields__
    return [MapSource(**{k: v for k, v in s.items() if k in known}) for s in raw]


def _cmd_dispersion_map(args):
    from ecodoc.development import dispersion_map as dm

    sources = _load_sources_json(args.sources)
    if not sources:
        sys.exit("В файле нет источников.")
    grid = dm.compute_grid(sources, substance=args.substance)
    print(dm.summary(grid))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dm.render_svg(grid), encoding="utf-8")
    print(f"Карта: {out}")


def _cmd_upraza_export(args):
    from ecodoc.development import dispersion_export as ex

    sources = _load_sources_json(args.sources)
    if not sources:
        sys.exit("В файле нет источников.")
    outdir = Path(args.outdir)
    xl = ex.to_excel(sources, outdir / "upraza_sources.xlsx")
    js = ex.to_json(sources, outdir / "upraza_sources.json")
    print(f"Для УПРЗА (Excel): {xl}")
    print(f"Машиночитаемо (JSON): {js}")
    print("→ В «Экологе»: Импорт из Excel; сопоставьте колонки листов "
          "«Источники»/«Выбросы» (см. лист «Инструкция»).")


def _cmd_devdoc(args):
    ctx = workspace.resolve(args)
    out_dir = workspace.out_dir(args)
    if args.kind == "nmu":
        from ecodoc.development import nmu
        path = nmu.generate(ctx, out_dir / "план_НМУ.docx")
    else:
        from ecodoc.development import pek_program
        path = pek_program.generate(ctx, out_dir / "программа_ПЭК.docx")
    print(f"Документ: {path}")


def _cmd_doctor(args):
    """Показать, какие компоненты установлены (для диагностики)."""
    import shutil
    from importlib.util import find_spec

    print(f"ЭКО.DOC {__version__} — проверка окружения\n")
    # python-пакеты
    for mod, label in (("fitz", "PyMuPDF (PDF)"), ("docx", "python-docx (.docx)"),
                       ("openpyxl", "openpyxl (.xlsx)"), ("xlrd", "xlrd (.xls)"),
                       ("striprtf", "striprtf (.rtf)"), ("lxml", "lxml (XML)"),
                       ("pytesseract", "pytesseract (OCR-обёртка)")):
        ok = find_spec(mod) is not None
        print(f"  [{'✓' if ok else '✖'}] {label}")
    # внешние программы
    from ecodoc.parsers.text_extract import _setup_tesseract
    tl = _setup_tesseract()
    print(f"  [{'✓' if tl else '✖'}] Tesseract-OCR (сканы/фото)"
          + (f" — язык: {tl}" if tl else " — не найден"))

    def _found(*paths):
        return any(shutil.which(p) or Path(p).exists() for p in paths)

    soffice = _found("soffice", "soffice.exe",
                     r"C:\Program Files\LibreOffice\program\soffice.exe",
                     r"C:\Program Files (x86)\LibreOffice\program\soffice.exe")
    print(f"  [{'✓' if soffice else '✖'}] LibreOffice (запасное чтение .doc)")
    from ecodoc.intake.intake import _seven_zip
    print(f"  [{'✓' if _seven_zip() else '○'}] 7-Zip (rar/7z-архивы)")
    print(f"  [{'✓' if shutil.which('ollama') else '○'}] Ollama (локальный ИИ)")
    print("\n✓ — установлено, ✖ — нужно для полной работы, ○ — по желанию")


def _cmd_gui(args):
    from ecodoc.gui import server

    server.run(port=args.port, open_browser=not args.no_browser)


def _target_args(sub):
    """Общие аргументы выбора цели: -i контекст ИЛИ --org/--site."""
    sub.add_argument("-i", "--input", help="context.json (или используйте --org/--site)")
    sub.add_argument("--org", help="организация из рабочего пространства")
    sub.add_argument("--site", help="площадка организации")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ecodoc", description="ЭкоДок — экологическая отчётность")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="список форм").set_defaults(func=_cmd_list)

    a = sub.add_parser("analyze", help="разобрать приложенные документы в context.json")
    a.add_argument("files", nargs="+", help="doc/pdf/jpg/png/docx")
    a.add_argument("-o", "--output", default="context.json")
    a.add_argument("--no-ocr", action="store_true", help="не запускать OCR для сканов")
    a.set_defaults(func=_cmd_analyze)

    v = sub.add_parser("validate", help="проверить контекст под форму")
    v.add_argument("form")
    _target_args(v)
    v.set_defaults(func=_cmd_validate)

    g = sub.add_parser("generate", help="сгенерировать XML + печатную форму [+PDF]")
    g.add_argument("form")
    _target_args(g)
    g.add_argument("-o", "--outdir", default="out")
    g.add_argument("--force", action="store_true", help="генерировать несмотря на ошибки")
    g.add_argument("--pdf", action="store_true", help="также сконвертировать печать в PDF")
    g.set_defaults(func=_cmd_generate)

    c = sub.add_parser("calendar", help="календарь подачи + чек-лист документов по категории")
    _target_args(c)
    c.add_argument("--year", type=int, help="календарный год (по умолч. period.year+1)")
    c.add_argument("--xlsx", help="экспортировать в Excel по этому пути")
    c.set_defaults(func=_cmd_calendar)

    pa = sub.add_parser("passport", help="паспорта отходов I–IV класса (.docx)")
    _target_args(pa)
    pa.add_argument("-o", "--outdir", default="out/passports")
    pa.set_defaults(func=_cmd_passport)

    vo = sub.add_parser("volume", help="том НДВ/НДС/СЗЗ (.docx) с импортом из «Эколога»")
    vo.add_argument("type", choices=["ndv", "nds", "szz"])
    _target_args(vo)
    vo.add_argument("-o", "--outdir", default="out")
    vo.add_argument("--sources-xlsx", help="выгрузка таблицы источников из «Эколога»")
    vo.add_argument("--dispersion-xlsx", help="выгрузка результатов рассеивания из «Эколога»")
    vo.add_argument("--appendix", nargs="*", help="файлы-исходники в приложения (КХА и т.п.)")
    vo.set_defaults(func=_cmd_volume)

    # ── рабочее пространство: организации и площадки ──
    og = sub.add_parser("org", help="организации рабочего пространства")
    og.add_argument("action", choices=["add", "list"])
    og.add_argument("name", nargs="?", help="наименование организации (для add)")
    for req in ("inn", "kpp", "ogrn", "oktmo", "address"):
        og.add_argument(f"--{req}")
    og.set_defaults(func=_cmd_org)

    st = sub.add_parser("site", help="площадки организации")
    st.add_argument("action", choices=["add"])
    st.add_argument("org", help="организация")
    st.add_argument("name", help="название/полный адрес площадки")
    st.add_argument("--address", help="полный адрес площадки (если name — короткое имя)")
    st.set_defaults(func=_cmd_site)

    # ── приём документов ──
    ik = sub.add_parser("intake", help="принять документы: что распознано, чего не хватает")
    ik.add_argument("files", nargs="+", help="doc/pdf/jpg/xml/xlsx — справки, акты, протоколы")
    _target_args(ik)
    ik.add_argument("--ai", action="store_true", help="дополнительно ИИ-анализ (см. ai setup)")
    ik.add_argument("--form", action="append", help="проверять полноту только этих форм")
    ik.add_argument("--no-ocr", action="store_true")
    ik.set_defaults(func=_cmd_intake)

    # ── ИИ ──
    ai = sub.add_parser("ai", help="настройка и проверка ИИ-анализа")
    ai.add_argument("action", choices=["setup", "status", "test"])
    ai.add_argument("prompt", nargs="?", help="вопрос для action=test")
    ai.add_argument("--provider", help="принудительный провайдер (ollama, anthropic, ...)")
    ai.set_defaults(func=_cmd_ai)

    # ── сторож форм ──
    w = sub.add_parser("watch", help="проверить изменения форм/ставок/схем загрузки")
    w.add_argument("action", choices=["check"])
    w.add_argument("--xsd", help="папка с локальными XSD ЛКПП для слежения")
    w.set_defaults(func=_cmd_watch)

    # ── PDF и рассеивание ──
    pf = sub.add_parser("pdf", help="сконвертировать .xlsx/.docx в PDF")
    pf.add_argument("files", nargs="+")
    pf.set_defaults(func=_cmd_pdf)

    dpp = sub.add_parser("dispersion", help="экспресс-расчёт рассеивания (МРР-2017)")
    dpp.add_argument("sources", help="JSON с источниками (см. samples/dispersion_sources.json)")
    dpp.set_defaults(func=_cmd_dispersion)

    dm = sub.add_parser("dispersion-map",
                        help="карта рассеивания (суммация источников, SVG)")
    dm.add_argument("sources", help="JSON с источниками (x,y,substance,pdk)")
    dm.add_argument("-o", "--out", default="out/map.svg")
    dm.add_argument("--substance", help="вещество (если в файле несколько)")
    dm.set_defaults(func=_cmd_dispersion_map)

    ue = sub.add_parser("upraza-export",
                        help="выгрузить источники для загрузки в УПРЗА (Excel+JSON)")
    ue.add_argument("sources", help="JSON с источниками")
    ue.add_argument("-o", "--outdir", default="out")
    ue.set_defaults(func=_cmd_upraza_export)

    dd = sub.add_parser("devdoc", help="документ разработки (.docx): НМУ, программа ПЭК")
    dd.add_argument("kind", choices=["nmu", "pek-program"])
    _target_args(dd)
    dd.add_argument("-o", "--outdir", default="out")
    dd.set_defaults(func=_cmd_devdoc)

    doc = sub.add_parser("doctor", help="проверить установленные компоненты")
    doc.set_defaults(func=_cmd_doctor)

    gu = sub.add_parser("gui", help="графический интерфейс (локально, в браузере)")
    gu.add_argument("--port", type=int, default=8737)
    gu.add_argument("--no-browser", action="store_true")
    gu.set_defaults(func=_cmd_gui)
    return p


def main(argv=None):
    # консоль Windows по умолчанию cp1251/cp866 — не печатает ✓/⚠
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    if not (argv if argv is not None else sys.argv[1:]):
        # запуск без команды — показать справку, а не ошибку
        print(f"ЭКО.DOC {__version__} (продукт «ЭКО Проект») — "
              f"генератор экологических документов\n")
        parser.print_help()
        print("\nТиповой сценарий:\n"
              "  ecodoc org add \"ООО Ромашка\" --inn 780...   (один раз)\n"
              "  ecodoc site add \"ООО Ромашка\" \"Площадка 1\"\n"
              "  ecodoc intake справка.pdf --org \"ООО Ромашка\" --site \"Площадка 1\" --ai\n"
              "  ecodoc generate declaration-nvos --org \"ООО Ромашка\" --site \"Площадка 1\" --pdf\n"
              "\nВсе формы и модули:  ecodoc list")
        return
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
