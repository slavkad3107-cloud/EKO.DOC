"""Ставки платы за НВОС: проверка новизны в интернете и обновление справочника.

Требование эколога (08.09.2026): «при запуске искать ставки в интернете и
использовать всегда». Что реально возможно без ключей и подписок:

  check_online(timeout) — открытые страницы (КонсультантПлюс: карточка
      Распоряжения № 2409-р с пометкой «ред. от ДД.ММ.ГГГГ», поиск на
      publication.pravo.gov.ru) → дата новейшей редакции акта о ставках →
      сравнение с тем, что вшито в data/rates_nvos.json (_source_2026).
      Возвращает {latest_act, latest_date, our_act, our_date, newer, url, …}.
      Сеть недоступна → newer=False и текст ошибки, старт GUI не блокируется.

  apply(url) — скачивает документ (PDF/HTML/JSON) и обновляет ставки.
      Честно: сами акты — это PDF-таблицы «№ | наименование | 2026 … 2030»
      БЕЗ кодов веществ; извлечение регэкспом по строкам работает на
      машиночитаемом тексте (текстовый слой PDF, HTML КонсультантПлюс) и
      сопоставляет позиции по наименованию с уже вшитыми (sanitize.norm_name).
      Скан без текстового слоя не разбирается — apply сообщает об этом и
      ничего не меняет. Перед записью — бэкап rates_nvos.json.bak-<дата>.
      Надёжный путь — JSON того же вида, что rates_by_year[год]
      ({"year": 2026, "air": {...}, "water": {...}, "waste_by_class": {...}}).
"""
from __future__ import annotations

import json
import re
import shutil
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

from ecodoc.core import sanitize
from ecodoc.core.refdata import DATA_DIR, rates_nvos

RATES_PATH = DATA_DIR / "rates_nvos.json"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EKO.DOC"}

# Открытые источники, где видна дата последней редакции акта о ставках.
# kind: consultant — карточка документа «(ред. от ДД.ММ.ГГГГ)»;
#       pravo — поиск официального опубликования по названию.
SOURCES = [
    {"name": "КонсультантПлюс — Распоряжение № 2409-р (ставки 2026-2030)",
     "url": "https://www.consultant.ru/document/cons_doc_LAW_513952/", "kind": "consultant"},
    # официальное опубликование: поиск по названию находит постановления
    # «О ставках платы…», «О дополнительных коэффициентах к ставкам платы…»
    # (распоряжения со ставками в этом поиске не показываются — их ведёт
    # карточка КонсультантПлюс выше)
    {"name": "publication.pravo.gov.ru — поиск «платы за негативное воздействие»",
     "url": "http://publication.pravo.gov.ru/search?name=%D0%BF%D0%BB%D0%B0%D1%82%D1%8B+%D0%B7%D0%B0+%D0%BD%D0%B5%D0%B3%D0%B0%D1%82%D0%B8%D0%B2%D0%BD%D0%BE%D0%B5+%D0%B2%D0%BE%D0%B7%D0%B4%D0%B5%D0%B9%D1%81%D1%82%D0%B2%D0%B8%D0%B5",
     "kind": "pravo"},
]
_PRAVO_ACT = re.compile(
    r"(Постановление|Распоряжение)\s+Правительства\s+Российской\s+Федерации\s+от\s+"
    r"(\d{2}\.\d{2}\.\d{4})\s+№\s*([\d\-рp]+)\s*\n?\s*[\"«]([^\"»]{0,200})")

_RU_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def _iso(d: str) -> str:
    m = _RU_DATE.search(d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else str(d or "")


def our_act() -> dict:
    """Что вшито: акт, дата его последней известной редакции, ссылка."""
    src = rates_nvos().get("_source_2026") or {}
    known = src.get("latest_known_act") or {}
    if known.get("date"):
        # учтённые смежные акты (доп. коэффициенты и т. п.) — «мы знаем и про них»
        date_ = max([known["date"]] + [str(r.get("date") or "")
                                       for r in (known.get("related") or [])])
        return {"act": known.get("act", src.get("act", "")), "date": date_,
                "url": known.get("url", ""), "checked": src.get("checked_online", "")}
    s4110 = src.get("source_4110r") or {}
    return {"act": src.get("act", ""), "date": _iso(s4110.get("publish_date", "")),
            "url": s4110.get("pdf", ""), "checked": src.get("checked_at", "")}


def _fetch(url: str, timeout: float) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), str(r.headers.get("Content-Type") or "")


def _parse_consultant(html: str) -> dict:
    """Карточка КонсультантПлюс: заголовок и «(ред. от ДД.ММ.ГГГГ)»."""
    title = ""
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if m:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
    red = re.search(r"ред\.\s*от\s*(\d{2}\.\d{2}\.\d{4})", html)
    act = re.search(r"(Распоряжение|Постановление)\s+Правительства\s+РФ\s+от\s+"
                    r"(\d{2}\.\d{2}\.\d{4})\s+N\s*([\d\-рp]+)", html)
    out = {"title": title[:200]}
    if red:
        out["date"] = _iso(red.group(1))
        out["act"] = f"редакция от {red.group(1)}"
    elif act:
        out["date"] = _iso(act.group(2))
        out["act"] = f"{act.group(1)} Правительства РФ от {act.group(2)} № {act.group(3)}"
    if act:
        out["base_act"] = f"{act.group(1)} Правительства РФ от {act.group(2)} № {act.group(3)}"
    return out


def _parse_pravo(html: str) -> dict:
    """Результаты поиска на pravo.gov.ru: берём самую свежую дату документа
    со словами «ставк… платы за негативное воздействие»."""
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"[ \t\r]+", " ", text)
    best: dict = {}
    for m in _PRAVO_ACT.finditer(text):
        kind, d, num, title = m.groups()
        # только акты о ставках / коэффициентах к ставкам платы за НВОС
        if not re.search(r"ставк\w*\s+платы\s+за\s+негативное", title, re.I):
            continue
        iso = _iso(d)
        if iso > best.get("date", ""):
            best = {"act": f"{kind} Правительства РФ от {d} № {num} «{title.strip()}»",
                    "date": iso}
    return best


def check_online(timeout: float = 10) -> dict:
    """Есть ли акт о ставках новее вшитого. Никогда не бросает исключений."""
    ours = our_act()
    res = {"our_act": ours.get("act", ""), "our_date": ours.get("date", ""),
           "our_url": ours.get("url", ""), "latest_act": "", "latest_date": "",
           "newer": False, "url": "", "checked": date.today().isoformat(),
           "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "sources": [], "error": ""}
    errors = []
    for src in SOURCES:
        try:
            body, ctype = _fetch(src["url"], timeout)
            html = body.decode("utf-8", "replace")
            info = _parse_consultant(html) if src["kind"] == "consultant" else _parse_pravo(html)
            entry = {"name": src["name"], "url": src["url"], **info}
            res["sources"].append(entry)
            if info.get("date") and info["date"] > res["latest_date"]:
                res["latest_date"] = info["date"]
                res["latest_act"] = info.get("act", "")
                res["url"] = src["url"]
        except (urllib.error.URLError, OSError, ValueError) as e:
            errors.append(f"{src['name']}: {str(e)[:120]}")
    if errors:
        res["error"] = "; ".join(errors)
    if res["latest_date"] and res["our_date"]:
        res["newer"] = res["latest_date"] > res["our_date"]
    res["text"] = summary(res)
    return res


def summary(res: dict) -> str:
    """Одна строка для плашки при запуске."""
    if res.get("newer"):
        return (f"⚠ ставки платы за НВОС: в интернете найдена более новая редакция "
                f"({res.get('latest_act') or res.get('latest_date')}) — в программе "
                f"редакция от {res.get('our_date')}. Проверьте и обновите "
                f"(Сервис → Ставки платы за НВОС).")
    if res.get("latest_date"):
        return (f"ставки платы за НВОС актуальны: последняя редакция {res['latest_date']} "
                f"(проверено в интернете {res.get('checked')})")
    if res.get("error"):
        return (f"ставки платы за НВОС: проверка в интернете не удалась "
                f"({res['error'][:100]}) — работаем по вшитым ставкам "
                f"(редакция от {res.get('our_date')})")
    return f"ставки платы за НВОС: редакция от {res.get('our_date')}"


# ── обновление ───────────────────────────────────────────────────────────────
_ROW = re.compile(
    r"^\s*(?P<n>\d{1,3})[.)]?\s+(?P<name>[^\d].*?)\s+"
    r"(?P<nums>(?:\d[\d ]*(?:[.,]\d+)?\s+){0,5}\d[\d ]*(?:[.,]\d+)?)\s*$")


# число в строке акта: «1 965,9» (пробел — разделитель тысяч, только вместе с
# дробной частью, иначе «250 300 350» — это три ставки, а не одна)
_NUM_RX = re.compile(r"\d{1,3}(?: \d{3})+[.,]\d+|\d+(?:[.,]\d+)?")


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace(",", "."))


def parse_rows(text: str, years: list[int] | None = None) -> list[dict]:
    """Строки «№ | наименование | ставка(и)» из текста акта.

    Возвращает [{'n', 'name', 'rates': {год: ставка}}]. Если в строке одна
    ставка — она относится к первому году из years (или к 'rate')."""
    years = years or [2026, 2027, 2028, 2029, 2030]
    rows = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        nums = [_num(x) for x in _NUM_RX.findall(m.group("nums"))]
        name = m.group("name").strip(" -–—|")
        if not nums or len(name) < 3:
            continue
        if len(nums) == 1:
            rates = {years[0]: nums[0]}
        else:
            rates = {y: v for y, v in zip(years, nums[-len(years):])}
        rows.append({"n": int(m.group("n")), "name": name, "rates": rates})
    return rows


def _text_of(body: bytes, ctype: str, url: str) -> tuple[str, str]:
    """(вид, текст): json / text. PDF читаем через PyMuPDF, если он есть."""
    head = body[:8]
    if head.startswith(b"%PDF"):
        try:
            import fitz  # PyMuPDF — уже есть в проекте
        except ImportError:
            raise ValueError("PDF без PyMuPDF не прочитать — установите pymupdf")
        doc = fitz.open(stream=body, filetype="pdf")
        text = "\n".join(page.get_text("text") for page in doc)
        if len(text.strip()) < 200:
            raise ValueError("в PDF нет текстового слоя (скан) — таблицу ставок "
                             "автоматически не извлечь, обновите вручную")
        return "text", text
    txt = body.decode("utf-8", "replace")
    if "json" in ctype or url.lower().endswith(".json") or txt.lstrip().startswith("{"):
        return "json", txt
    if "<" in txt[:500]:
        txt = re.sub(r"<br\s*/?>|</(p|tr|div|li|h\d)>", "\n", txt, flags=re.I)
        txt = re.sub(r"</t[dh]>", " | ", txt, flags=re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"&nbsp;", " ", txt)
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = txt.replace(" | ", "  ")
    return "text", txt


def _backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = RATES_PATH.with_name(f"{RATES_PATH.name}.bak-{stamp}")
    shutil.copy2(RATES_PATH, dst)
    return dst


def _synonyms(name: str) -> set[str]:
    """Наименование и его синонимы в скобках, нормализованные."""
    out = {sanitize.norm_name(name)}
    for grp in re.findall(r"\(([^)]*)\)", str(name or "")):
        for syn in re.split(r"[;,]", grp):
            s = sanitize.norm_name(syn)
            if len(s) >= 4:
                out.add(s)
    out.discard("")
    return out


def apply(url_or_path: str, year: int | None = None, timeout: float = 30,
          medium: str = "air") -> dict:
    """Обновить ставки из документа по ссылке (или локальному файлу).

    Возвращает {'ok', 'updated', 'unmatched', 'backup', 'message'}. Изменяет
    только те позиции, чьи наименования сопоставились с вшитыми; новые
    вещества добавляет под ключом «имя:…» (без кода)."""
    src = str(url_or_path or "").strip()
    if not src:
        return {"ok": False, "message": "не указана ссылка на документ"}
    try:
        if re.match(r"^https?://", src, re.I):
            body, ctype = _fetch(src, timeout)
        else:
            p = Path(src)
            body, ctype = p.read_bytes(), ""
            src = p.name
        kind, text = _text_of(body, ctype, src)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "message": f"документ не прочитан: {str(e)[:200]}"}

    data = json.loads(RATES_PATH.read_text(encoding="utf-8"))
    by_year = data.setdefault("rates_by_year", {})
    updated = 0
    unmatched: list[str] = []
    if kind == "json":
        try:
            new = json.loads(text)
        except ValueError as e:
            return {"ok": False, "message": f"JSON не разобран: {e}"}
        y = str(new.get("year") or year or "")
        if not y:
            return {"ok": False, "message": "в JSON нет поля year"}
        table = by_year.setdefault(y, {"air": {}, "water": {}, "waste_by_class": {}})
        for section in ("air", "water", "waste_by_class"):
            for code, rec in (new.get(section) or {}).items():
                if not isinstance(rec, dict) or "rate" not in rec:
                    continue
                cur = table.setdefault(section, {}).setdefault(code, {})
                cur.update(rec)
                updated += 1
        applied_years = [y]
    else:
        rows = parse_rows(text)
        if not rows:
            return {"ok": False, "updated": 0,
                    "message": "таблица «№ | наименование | ставка» в документе не "
                               "распознана — автоматическое обновление невозможно, "
                               "внесите ставки вручную в data/rates_nvos.json"}
        applied_years = []
        for row in rows:
            names = _synonyms(row["name"])
            hit = False
            for y, rate in row["rates"].items():
                table = by_year.get(str(y))
                if not table:
                    continue
                sect = table.get(medium) or {}
                for key, rec in sect.items():
                    if not isinstance(rec, dict):
                        continue
                    if names & _synonyms(rec.get("name", "")):
                        if rec.get("rate") != rate:
                            rec["rate"] = rate
                            updated += 1
                        hit = True
                        if str(y) not in applied_years:
                            applied_years.append(str(y))
            if not hit:
                unmatched.append(row["name"][:80])
    if not updated:
        return {"ok": False, "updated": 0, "unmatched": unmatched[:30],
                "message": "ни одна ставка не изменилась (документ совпадает с "
                           "вшитыми ставками или позиции не сопоставились)"}
    backup = _backup()
    src26 = data.setdefault("_source_2026", {})
    src26["last_apply"] = {"url": src, "date": date.today().isoformat(),
                           "updated": updated, "years": applied_years}
    RATES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
    return {"ok": True, "updated": updated, "unmatched": unmatched[:30],
            "backup": str(backup), "years": applied_years,
            "message": f"обновлено ставок: {updated}; бэкап {backup.name}"
                       + (f"; не сопоставлено позиций: {len(unmatched)}" if unmatched else "")}


def mark_checked(res: dict) -> None:
    """Записать в справочник дату проверки и найденную редакцию (без ставок)."""
    try:
        data = json.loads(RATES_PATH.read_text(encoding="utf-8"))
        src26 = data.setdefault("_source_2026", {})
        src26["checked_online"] = res.get("checked", date.today().isoformat())
        if res.get("latest_date"):
            src26["latest_seen_online"] = {"act": res.get("latest_act", ""),
                                           "date": res["latest_date"], "url": res.get("url", "")}
        RATES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
    except (OSError, ValueError):
        pass
