"""Санитар входных данных: что пускать в базу, а что вернуть пользователю.

Зачем. ИИ читает документы и предлагает значения; раньше они писались в базу
как есть. На реальных объектах это дало мусор: одно вещество под кодами «301»
и «0301», группы суммации и названия работ («сварочные работы») в перечне
веществ, виды сточных вод («ливневые стоки») вместо загрязняющих веществ,
значения ПДК из справочной колонки вместо массы выброса, выдуманные коды ФККО
и один отход под четырьмя кодами.

Здесь — правила, по которым значение либо принимается, либо отклоняется с
понятной причиной. Отклонённое НЕ пропадает: оно уходит в отчёт приёма и в
кандидаты, где пользователь решает сам. Программа не выдумывает данные и не
исправляет их молча.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── коды веществ ────────────────────────────────────────────────────────
# Коды загрязняющих веществ атмосферного воздуха — четырёхзначные; в
# документах их пишут и с ведущим нулём («0301»), и без («301»), поэтому в
# базе храним в одном виде — иначе одно вещество двоится.
CODE_LEN = 4
SUM_GROUP_MIN, SUM_GROUP_MAX = 6000, 6999   # группы суммации, не вещества


@dataclass
class Verdict:
    """Решение по одному значению."""
    ok: bool = True
    code: str = ""            # нормализованный код (может отличаться от входа)
    reason: str = ""          # почему отклонено / на что обратить внимание
    suspect: bool = False     # принять, но показать пользователю
    fixed: list = field(default_factory=list)   # что нормализовано


def norm_code(value) -> str:
    """Код вещества к единому виду: «301» → «0301», «0301» → «0301».

    Возвращает пустую строку, если это не код вещества (буквы, точки,
    больше четырёх цифр — например «01.01.00.11.01» из классификатора видов
    сточных вод)."""
    s = str(value or "").strip()
    if not s:
        return ""
    if not s.isdigit():
        return ""
    if len(s) > CODE_LEN:
        return ""
    return s.zfill(CODE_LEN)


def is_sum_group(code: str) -> bool:
    """Код группы суммации (6001, 6204…) — это не вещество, а их сочетание."""
    c = norm_code(code)
    return bool(c) and SUM_GROUP_MIN <= int(c) <= SUM_GROUP_MAX


def norm_name(value) -> str:
    """Наименование к сравнимому виду: регистр, ё, скобки-уточнения, пробелы.

    «Бытовая канализация» и «бытовая канализация» — одно и то же;
    «Азота диоксид (Двуокись азота)» и «Азота диоксид» — тоже."""
    s = str(value or "").lower().replace("ё", "е")
    s = re.sub(r"\([^)]*\)", " ", s)        # уточнения в скобках
    s = re.sub(r"[«»\"']", " ", s)
    s = re.sub(r"[^\w\s\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ── что веществом не является ───────────────────────────────────────────
# Работы и процессы: попадают в перечень, когда ИИ читает таблицу источников
# выбросов и принимает столбец «наименование источника» за вещество.
_OPERATION_WORDS = (
    "работ", "движение", "эксплуатац", "погрузк", "разгрузк", "укладк",
    "сварк", "сварочн", "покрасочн", "окрасочн", "заправк", "хранение",
    "стоянк", "проезд", "техник", "автотранспорт", "автомобил", "машин",
    "оборудован", "источник", "участок", "площадк", "цех", "котельн",
    "труба", "вентиляц", "выделяющиеся",
)
# Виды сточных вод: это ПОТОКИ водоотведения, а не загрязняющие вещества.
_WATER_FLOW_WORDS = (
    "сточные воды", "сточных вод", "стоки", "стоков", "канализац",
    "водоотведен", "водопотреблен", "ливнев", "дождев", "хоз-бытов",
    "хозбытов", "хозяйственно-бытов", "поверхностн сток",
)


def _hits(name: str, words) -> str:
    low = norm_name(name)
    for w in words:
        if w in low:
            return w
    return ""


# ── сверка «код ↔ наименование» по официальному перечню ─────────────────
# Ошибки распознавания дают записи вроде «0325 Керосин» (0325 — мышьяк),
# «0333 Азот (II) оксид» (0333 — сероводород), «3003 диоксид серы» (такого
# кода нет). Каждая — дубль настоящего вещества под чужим кодом; без сверки
# с перечнем санитар их пропускал, и вещество двоилось в отчётности.
#
# Сравнение осторожное: русские окончания («углерод»/«углерода») сводятся
# основой слова, одно общее слово («углеводороды») совпадением не считается,
# а код меняется только когда наименованию соответствует РОВНО один код.
_STOP = {"в", "на", "по", "и", "с", "смесь", "пересчете", "пересчёте",
         "прочие", "соединения", "соединений", "его"}
_ENDINGS = ("ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими",
            "ов", "ев", "ах", "ях", "ой", "ей", "ий", "ый", "ая", "яя",
            "ое", "ее", "ые", "ие", "ом", "ем", "ам", "ям",
            "а", "я", "ы", "и", "у", "ю", "е", "о")


def _stem(word: str) -> str:
    if len(word) <= 4 or not re.fullmatch(r"[а-я]+", word):
        return word
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 4:
            return word[: -len(end)]
    return word


def _tokens(text: str) -> set:
    t = str(text or "").lower().replace("ё", "е")
    t = re.sub(r"\([^)]*\)", " ", t)
    return {_stem(w) for w in re.findall(r"[а-яa-z0-9]+", t)} - _STOP


def _name_variants(official: str) -> list:
    """Главное имя и каждый синоним из скобок — отдельными наборами слов."""
    out = [_tokens(official)]
    for inner in re.findall(r"\(([^)]*)\)", str(official or "")):
        for syn in inner.split(";"):
            t = _tokens(syn)
            if t:
                out.append(t)
    return [v for v in out if v]


def _strong(nm: set, var: set) -> bool:
    """Сильное совпадение двух наборов слов-основ."""
    if not nm or not var:
        return False
    if nm == var:
        return True
    common = nm & var
    if len(common) >= 2:
        return True
    # одно слово — только если это полное имя с обеих сторон и слово длинное
    if len(nm) == 1 and len(var) == 1:
        w = next(iter(common), "")
        return len(w) >= 5
    return False


def _names_agree(ours: str, official: str) -> bool:
    """Не противоречит ли наше наименование официальному для этого кода."""
    nm = _tokens(ours)
    if not nm:
        return True                     # нечего сравнивать — код решает
    for var in _name_variants(official):
        if _strong(nm, var):
            return True
        if nm & var:                    # хоть одно общее слово — не спорим
            return True
    return False


def codes_for_name(name: str) -> list:
    """Коды официального перечня, которым наименование соответствует сильно."""
    from ecodoc.core.refdata import official_air
    nm = _tokens(name)
    if not nm:
        return []
    hits = []
    for code, official in official_air().items():
        if any(_strong(nm, var) for var in _name_variants(official)):
            hits.append(code)
    return hits


def code_name_conflict(code: str, name: str) -> tuple:
    """(причина, верный_код) если код расходится с наименованием.

    Верный код возвращается ТОЛЬКО когда он единственный; если кандидатов
    несколько или нет — причина есть, кода нет (пользователь решит сам)."""
    from ecodoc.core.refdata import official_air
    table = official_air()
    if not table or not code:
        return "", ""
    official = table.get(code)
    if official is not None and _names_agree(name, official):
        return "", ""
    want = codes_for_name(name)
    if official is not None:
        if not want:
            return "", ""               # имя незнакомое — код решает
        if code in want:
            return "", ""
        fix = want[0] if len(want) == 1 else ""
        return (f"код {code} — это «{official[:40]}», а наименование "
                f"«{name[:40]}» соответствует коду "
                f"{fix or '/'.join(want[:3])}"), fix
    if want:
        fix = want[0] if len(want) == 1 else ""
        return (f"кода {code} нет в перечне загрязняющих веществ, а "
                f"наименование соответствует коду "
                f"{fix or '/'.join(want[:3])}"), fix
    return "", ""


def check_substance(code, name, medium: str = "air") -> Verdict:
    """Пускать ли позицию в перечень веществ (выбросы/сбросы).

    medium — «air» или «water»: для воды коды атмосферного перечня не
    применяются, поэтому четырёхзначный код там подозрителен."""
    raw = str(code or "").strip()
    nm = str(name or "").strip()
    v = Verdict(code=norm_code(raw))

    if not raw and not nm:
        return Verdict(ok=False, reason="пустая позиция: нет ни кода, ни наименования")

    hit = _hits(nm, _OPERATION_WORDS)
    if hit:
        return Verdict(ok=False, code=v.code,
                       reason=f"это не вещество, а работа/источник выброса "
                              f"(«{hit}» в наименовании) — место таким строкам "
                              f"в перечне источников, не в перечне веществ")

    flow = _hits(nm, _WATER_FLOW_WORDS)
    if flow:
        return Verdict(ok=False, code=v.code,
                       reason=f"это вид сточных вод («{flow}»), а не "
                              f"загрязняющее вещество — учитывается объёмом "
                              f"водоотведения, а не массой вещества")

    if is_sum_group(raw):
        return Verdict(ok=False, code=v.code,
                       reason=f"код {v.code} — группа суммации, а не вещество; "
                              f"в отчётность идут вещества, входящие в группу")

    if raw and not v.code:
        # код есть, но это не код вещества: точки, буквы, длинные номера
        return Verdict(ok=True, code="", suspect=True,
                       reason=f"код «{raw}» не похож на код загрязняющего "
                              f"вещества (ожидаются 4 цифры) — принято по "
                              f"наименованию, код не сохранён",
                       fixed=["код отброшен"])

    if medium == "water" and v.code:
        return Verdict(ok=True, code=v.code, suspect=True,
                       reason=f"код {v.code} — из перечня веществ АТМОСФЕРНОГО "
                              f"воздуха, а позиция отнесена к сбросам: "
                              f"проверьте среду",
                       fixed=[])

    if v.code and medium != "water":
        reason, want = code_name_conflict(v.code, nm)
        if reason:
            # дубль настоящего вещества под чужим кодом: если верный код
            # единственный — чиним и показываем; если нет — только показываем
            v.suspect = True
            v.reason = reason
            if want:
                v.fixed.append(f"код {v.code} → {want}")
                v.code = want
            return v

    if v.code and v.code != raw:
        v.fixed.append(f"код {raw} → {v.code}")
    return v


def pdk_conflict(code: str, value) -> str:
    """Похоже ли, что вместо массы выброса записали ПДК из справочника.

    Частая ошибка распознавания: в таблице перечня веществ рядом стоят
    колонки «ПДК» и «выброс», и в базу попадает ПДК. Точное совпадение с
    ПДК — повод показать значение пользователю, а не принять молча."""
    try:
        from ecodoc.core.refdata import substances
    except Exception:
        return ""
    c = norm_code(code)
    if not c or value in (None, ""):
        return ""
    try:
        val = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return ""
    if val <= 0:
        return ""
    for s in substances():
        if norm_code(s.get("code")) != c:
            continue
        for key, label in (("pdk_mr", "ПДК м.р."), ("pdk_ss", "ПДК с.с.")):
            ref = s.get(key)
            if ref and abs(float(ref) - val) < 1e-12:
                return (f"значение {val} совпадает с {label} вещества "
                        f"{c} — похоже, вместо массы выброса (т/год) взято "
                        f"значение ПДК из справочной колонки")
    return ""


# ── отходы ──────────────────────────────────────────────────────────────
def check_waste(fkko, name="", hazard=0) -> Verdict:
    """Пускать ли отход в перечень: код сверяется с каталогом ФККО.

    Каталог полный (все действующие позиции), поэтому отсутствие кода —
    основание не пускать значение в базу молча, а показать пользователю."""
    from ecodoc.core import fkko as cat
    raw = str(fkko or "").strip()
    nm = str(name or "").strip()
    code = cat.norm(raw)
    if not raw and not nm:
        return Verdict(ok=False, reason="пустая позиция: нет ни кода, ни наименования")
    if not raw:
        return Verdict(ok=True, code="", suspect=True,
                       reason="отход без кода ФККО — подберите код по каталогу")

    chk = cat.check(code, nm)
    if not chk.ok:
        return Verdict(ok=False, code=code, reason=chk.problem)
    if not chk.verified:
        return Verdict(ok=True, code=code, suspect=True, reason=chk.note)

    v = Verdict(ok=True, code=code)
    if code != raw:
        v.fixed.append(f"код {raw} → {code}")
    if chk.name_mismatch:
        v.suspect = True
        v.reason = (f"наименование расходится с каталогом ФККО: "
                    f"у нас «{nm[:40]}», в каталоге «{chk.name_mismatch[:40]}»")
    elif chk.hazard and hazard and int(hazard) != chk.hazard:
        v.suspect = True
        v.reason = (f"класс опасности {hazard} не совпадает с каталогом "
                    f"({chk.hazard}) — последняя цифра кода задаёт класс")
    return v


# ── чистка уже накопленной базы ─────────────────────────────────────────
def audit_context(ctx) -> dict:
    """Разобрать данные площадки: что достоверно, что мусор, где дубли.

    Ничего не меняет — только отчёт, по которому пользователь решает."""
    from ecodoc.core.models import Medium

    out = {"pollutants": [], "wastes": [], "duplicates": []}
    seen: dict[tuple, int] = {}
    for i, p in enumerate(ctx.pollutants):
        medium = "water" if p.medium == Medium.WATER else "air"
        v = check_substance(p.code, p.name, medium)
        row = {"index": i, "medium": medium, "code": p.code, "name": p.name,
               "ok": v.ok, "suspect": v.suspect, "reason": v.reason,
               "norm_code": v.code}
        mass = p.mass_norm + p.mass_limit + p.mass_over
        note = pdk_conflict(p.code, p.mass_norm)
        if note:
            row["suspect"] = True
            row["reason"] = "; ".join(x for x in (row["reason"], note) if x)
        row["mass"] = str(mass)
        if v.ok and not mass:
            row["suspect"] = True
            row["reason"] = "; ".join(x for x in (
                row["reason"], "нет ни одной массы — позиция ничего не даёт "
                               "отчётности") if x)
        out["pollutants"].append(row)

        key = (medium, v.code or norm_name(p.name))
        if key in seen:
            out["duplicates"].append(
                {"kind": "вещество", "index": i, "same_as": seen[key],
                 "label": f"{p.code} {p.name}"[:60]})
        else:
            seen[key] = i

    from ecodoc.core import fkko as _cat
    wseen: dict[str, int] = {}
    for i, w in enumerate(ctx.wastes):
        v = check_waste(w.fkko_code, w.name, w.hazard_class)
        mass = sum([w.generated, w.transferred, w.placed_norm, w.placed_over,
                    w.accumulated_end, w.used, w.neutralized])
        row = {"index": i, "fkko": w.fkko_code, "name": w.name,
               "hazard": w.hazard_class, "ok": v.ok, "suspect": v.suspect,
               "reason": v.reason, "norm_code": v.code, "mass": str(mass)}
        if not v.ok and w.name:
            # код неверный, но наименование обычно верное — предлагаем замену
            row["suggest"] = [s for s in _cat.suggest_by_name(w.name, 2)
                              if s["score"] >= 0.5]
        out["wastes"].append(row)
        key = v.code or norm_name(w.name)
        if key in wseen:
            out["duplicates"].append(
                {"kind": "отход", "index": i, "same_as": wseen[key],
                 "label": f"{w.fkko_code} {w.name}"[:60]})
        else:
            wseen[key] = i

    # справки-акты: движение отходов пересчитывается из них, поэтому мусорный
    # код в акте вернёт мусор в перечень даже после чистки перечня
    out["acts"] = []
    for i, a in enumerate(ctx.waste_acts):
        v = check_waste(a.fkko_code, a.name, a.hazard_class)
        if v.ok and not v.suspect:
            continue
        out["acts"].append(
            {"index": i, "fkko": a.fkko_code, "name": a.name, "ok": v.ok,
             "suspect": v.suspect, "reason": v.reason, "norm_code": v.code,
             "mass": str(a.mass), "date": a.date, "receiver": a.receiver})

    out["totals"] = {
        "acts": len(ctx.waste_acts),
        "acts_bad": sum(1 for r in out["acts"] if not r["ok"]),
        "acts_suspect": sum(1 for r in out["acts"] if r["ok"] and r["suspect"]),
        "pollutants": len(ctx.pollutants),
        "pollutants_bad": sum(1 for r in out["pollutants"] if not r["ok"]),
        "pollutants_suspect": sum(1 for r in out["pollutants"]
                                  if r["ok"] and r["suspect"]),
        "wastes": len(ctx.wastes),
        "wastes_bad": sum(1 for r in out["wastes"] if not r["ok"]),
        "wastes_suspect": sum(1 for r in out["wastes"]
                              if r["ok"] and r["suspect"]),
        "duplicates": len(out["duplicates"]),
    }
    return out


def clean_context(ctx, drop_bad: bool = True, drop_dupes: bool = True,
                  drop_empty: bool = False) -> dict:
    """Убрать из данных то, что признано мусором. Возвращает отчёт о правках.

    drop_bad — отбракованные позиции (не вещества, коды вне ФККО);
    drop_dupes — повторы одного вещества/отхода (остаётся тот, у кого есть
    массы, иначе первый);
    drop_empty — позиции без единой массы."""
    from ecodoc.core.models import Medium

    report = {"removed_pollutants": [], "removed_wastes": [], "fixed_codes": [],
              "removed_acts": []}

    # ── справки-акты (первичны: движение считается из них) ──────────
    keep_a = []
    for a in ctx.waste_acts:
        v = check_waste(a.fkko_code, a.name, a.hazard_class)
        label = f"{a.fkko_code} {a.name}".strip()[:70]
        if drop_bad and not v.ok:
            report["removed_acts"].append(
                {"label": label, "reason": v.reason, "mass": str(a.mass),
                 "date": a.date})
            continue
        if v.code and v.code != a.fkko_code:
            report["fixed_codes"].append(
                {"label": label, "was": a.fkko_code, "now": v.code})
            a.fkko_code = v.code
        keep_a.append(a)
    ctx.waste_acts = keep_a

    # ── вещества ────────────────────────────────────────────────────
    keep_p, groups = [], {}
    for p in ctx.pollutants:
        medium = "water" if p.medium == Medium.WATER else "air"
        v = check_substance(p.code, p.name, medium)
        label = f"{p.code} {p.name}".strip()[:70]
        if drop_bad and not v.ok:
            report["removed_pollutants"].append(
                {"label": label, "reason": v.reason})
            continue
        if v.code and v.code != p.code:
            report["fixed_codes"].append(
                {"label": label, "was": p.code, "now": v.code})
            p.code = v.code
        mass = p.mass_norm + p.mass_limit + p.mass_over
        if drop_empty and not mass:
            report["removed_pollutants"].append(
                {"label": label, "reason": "нет ни одной массы"})
            continue
        key = (medium, p.code or norm_name(p.name))
        if drop_dupes and key in groups:
            prev = groups[key]
            prev_mass = prev.mass_norm + prev.mass_limit + prev.mass_over
            if mass and not prev_mass:      # у первой масс нет — берём эту
                keep_p[keep_p.index(prev)] = p
                groups[key] = p
                report["removed_pollutants"].append(
                    {"label": f"{prev.code} {prev.name}".strip()[:70],
                     "reason": "повтор того же вещества (без масс)"})
            elif mass and prev_mass and mass != prev_mass:
                # обе с массами и они разные — не выбираем молча большую:
                # остаётся первая (из основного документа), а расхождение
                # показываем, чтобы пользователь сверил с источником
                report["removed_pollutants"].append(
                    {"label": label,
                     "reason": f"повтор того же вещества с ДРУГОЙ массой "
                               f"({mass} против {prev_mass}) — оставлена "
                               f"первая, сверьте с источником"})
                report.setdefault("mass_conflicts", []).append(
                    {"code": prev.code, "name": prev.name[:60],
                     "kept": str(prev_mass), "dropped": str(mass)})
            else:
                report["removed_pollutants"].append(
                    {"label": label, "reason": "повтор того же вещества"})
            continue
        groups[key] = p
        keep_p.append(p)
    ctx.pollutants = keep_p

    # ── отходы ──────────────────────────────────────────────────────
    keep_w, wgroups = [], {}
    for w in ctx.wastes:
        v = check_waste(w.fkko_code, w.name, w.hazard_class)
        label = f"{w.fkko_code} {w.name}".strip()[:70]
        mass = sum([w.generated, w.transferred, w.placed_norm, w.placed_over,
                    w.accumulated_end, w.used, w.neutralized])
        if drop_bad and not v.ok:
            report["removed_wastes"].append({"label": label, "reason": v.reason,
                                             "mass": str(mass)})
            continue
        if v.code and v.code != w.fkko_code:
            report["fixed_codes"].append(
                {"label": label, "was": w.fkko_code, "now": v.code})
            w.fkko_code = v.code
        if drop_empty and not mass:
            report["removed_wastes"].append(
                {"label": label, "reason": "нет ни одной массы", "mass": "0"})
            continue
        key = v.code or norm_name(w.name)
        if drop_dupes and key in wgroups:
            prev = wgroups[key]
            prev_mass = sum([prev.generated, prev.transferred, prev.placed_norm,
                             prev.placed_over, prev.accumulated_end,
                             prev.used, prev.neutralized])
            if mass > prev_mass:
                keep_w[keep_w.index(prev)] = w
                wgroups[key] = w
                report["removed_wastes"].append(
                    {"label": f"{prev.fkko_code} {prev.name}".strip()[:70],
                     "reason": "повтор того же отхода (меньше данных)",
                     "mass": str(prev_mass)})
            else:
                report["removed_wastes"].append(
                    {"label": label, "reason": "повтор того же отхода",
                     "mass": str(mass)})
            continue
        wgroups[key] = w
        keep_w.append(w)
    ctx.wastes = keep_w

    # движение пересчитываем из оставшихся актов: иначе очищенный перечень
    # снова наполнится мусором при первой же загрузке площадки
    if ctx.waste_acts:
        try:
            from ecodoc.core.waste_agg import apply_acts
            apply_acts(ctx)
        except Exception:
            pass
    return report
