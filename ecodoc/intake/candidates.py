"""Кандидаты данных: что нашлось в документах и откуда именно.

Требование ТЗ: «показать в таблице какие найдены данные из каких документов /
разделов / файлов: файл и скан/фото листа из файла откуда данные взяты и
предложить выбрать какие взять в базу».

Хранится отдельным файлом `candidates.json` рядом с `context.json`, потому что
`serialize.from_json` собирает контекст заново и выбрасывает незнакомые ключи —
секция внутри context.json просто исчезла бы при первом «Сохранить». К тому же
контекст переписывается целиком на каждом чанке приёма.

Ключ поля (`key`) — СТАБИЛЬНЫЙ адрес значения, не зависящий от порядка строк:
    organization.inn
    period.year
    objects[code=41-0247-005048-П].name
    wastes[fkko=47110101521].generated
    waste_acts[fkko=47110101521;d=15022025;r=меркурий;m=0.052].mass
    pollutants[air;code=0301].mass_norm
Индексы (`wastes[3].generated`) для этого не годятся: движение пересчитывается
из актов при каждой загрузке и позиции «переезжают».
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

FILE = "candidates.json"
_LOCK = threading.Lock()

NEW, ACCEPTED, REJECTED, MANUAL = "new", "accepted", "rejected", "manual"


@dataclass
class Candidate:
    key: str                     # стабильный адрес поля (см. модуль-докстринг)
    value: str = ""
    label: str = ""              # человекочитаемо: «ИНН», «Отход 7331…: масса, т»
    doc: str = ""                # sha1 документа (см. intake/sources.py)
    file: str = ""               # имя файла — для показа без обращения к sources
    page: int = 0                # лист-источник (0 — неизвестен)
    exact: bool = False          # цитата реально найдена на этом листе
    quote: str = ""
    method: str = "ai"           # ai | regex | manual
    model: str = ""
    unit: str = ""               # единица из документа («кг», «т», «м3»)
    state: str = NEW
    seen: int = 1

    @property
    def id(self) -> str:
        # источник в ключе — иначе одинаковое значение из РАЗНЫХ документов
        # схлопнется в одну запись и потеряется подтверждение вторым файлом.
        # sha1 документа известен не сразу, поэтому пока его нет — имя файла.
        src = (self.doc or "")[:16] or (self.file or "nodoc")
        return f"{src}:{self.key}:{_norm_value(self.key, self.value)}"


# ── ключи полей ──────────────────────────────────────────────────────────

_KEY_RE = re.compile(r"^(?P<coll>\w+)\[(?P<sel>[^\]]*)\]\.(?P<attr>\w+)$")


def act_key(fkko: str, date: str, receiver: str, mass) -> str:
    """Ключ справки-акта — тот же принцип, что у дедупа в analyzer._act_key."""
    from ecodoc.core.waste_agg import norm_fkko
    d = re.sub(r"\D", "", str(date or ""))
    r = re.sub(r"\s+", " ", str(receiver or "")).strip().lower()
    try:
        m = str(Decimal(str(mass).replace(",", ".")).normalize())
    except (InvalidOperation, ValueError, TypeError):
        m = str(mass or "")
    return f"waste_acts[fkko={norm_fkko(fkko)};d={d};r={r};m={m}]"


def parse_key(key: str) -> tuple[str, dict, str]:
    """«wastes[fkko=733…].generated» → ("wastes", {"fkko": "733…"}, "generated")."""
    m = _KEY_RE.match(key or "")
    if not m:
        head, _, attr = (key or "").rpartition(".")
        return head, {}, attr
    sel = {}
    for part in m.group("sel").split(";"):
        if not part:
            continue
        k, _, v = part.partition("=")
        sel[k.strip()] = v.strip() if v else ""
        if not v:                       # «air» в pollutants[air;code=0301]
            sel["medium"] = k.strip()
    return m.group("coll"), sel, m.group("attr")


def _norm_value(key: str, value) -> str:
    """Нормализованное значение — для дедупа и сравнения между документами."""
    s = str(value or "").strip()
    _coll, _sel, attr = parse_key(key)
    if attr in ("inn", "kpp", "ogrn", "okpo", "oktmo", "fkko_code", "code"):
        return re.sub(r"\D", "", s)
    if attr in ("date",):
        return re.sub(r"\D", "", s)
    try:
        return str(Decimal(s.replace(",", ".").replace(" ", "")).normalize())
    except (InvalidOperation, ValueError):
        return re.sub(r"\s+", " ", s).strip().lower().replace("ё", "е")


def resolve(ctx, key: str) -> str | None:
    """Ключ → data-path для формы GUI («wastes[7].generated»), None — если нет."""
    from ecodoc.core.models import Medium
    from ecodoc.core.waste_agg import norm_fkko
    coll, sel, attr = parse_key(key)
    if not coll:
        return None
    if coll in ("organization", "period"):
        return f"{coll}.{attr}"
    if coll == "objects":
        for i, o in enumerate(ctx.objects):
            if o.code == sel.get("code"):
                return f"objects[{i}].{attr}"
        return None
    if coll == "wastes":
        code = norm_fkko(sel.get("fkko", ""))
        for i, w in enumerate(ctx.wastes):
            if norm_fkko(w.fkko_code) == code:
                return f"wastes[{i}].{attr}"
        return None
    if coll == "waste_acts":
        want = key.rsplit(".", 1)[0]
        for i, a in enumerate(ctx.waste_acts):
            if act_key(a.fkko_code, a.date, a.receiver, a.mass) == want:
                return f"waste_acts[{i}].{attr}"
        return None
    if coll == "pollutants":
        medium = sel.get("medium", "air")
        # в форме вещества разнесены по средам: _pair (воздух) / _pwater (вода)
        table = "_pair" if medium == "air" else "_pwater"
        want_medium = Medium.AIR if medium == "air" else Medium.WATER
        idx = 0
        for p in ctx.pollutants:
            if p.medium != want_medium:
                continue
            if (sel.get("code") and p.code == sel["code"]) or \
               (not sel.get("code") and p.name == sel.get("name")):
                return f"{table}[{idx}].{attr}"
            idx += 1
        return None
    return None


def read(ctx, key: str):
    """Текущее значение поля в базе (или None, если позиции нет)."""
    from ecodoc.core.models import Medium
    from ecodoc.core.waste_agg import norm_fkko
    coll, sel, attr = parse_key(key)
    obj = None
    if coll == "organization":
        obj = ctx.organization
    elif coll == "period":
        obj = ctx.period
    elif coll == "objects":
        obj = next((o for o in ctx.objects if o.code == sel.get("code")), None)
    elif coll == "wastes":
        code = norm_fkko(sel.get("fkko", ""))
        obj = next((w for w in ctx.wastes if norm_fkko(w.fkko_code) == code), None)
    elif coll == "waste_acts":
        want = key.rsplit(".", 1)[0]
        obj = next((a for a in ctx.waste_acts
                    if act_key(a.fkko_code, a.date, a.receiver, a.mass) == want), None)
    elif coll == "pollutants":
        want_medium = Medium.AIR if sel.get("medium", "air") == "air" else Medium.WATER
        obj = next((p for p in ctx.pollutants
                    if p.medium == want_medium
                    and ((sel.get("code") and p.code == sel["code"])
                         or (not sel.get("code") and p.name == sel.get("name")))), None)
    return getattr(obj, attr, None) if obj is not None else None


_DEC_ATTRS = {"generated", "transferred", "used", "neutralized", "placed_norm",
              "placed_over", "accumulated_start", "accumulated_end", "mass",
              "volume_m3", "density", "mass_norm", "mass_limit", "mass_over",
              "k_st", "k_ot"}
_INT_ATTRS = {"year", "quarter", "hazard_class"}


def write(ctx, key: str, value) -> bool:
    """Записать принятое значение в контекст с правильным типом.

    Значения приходят строками (из документа или от пользователя), а модель
    хранит Decimal/int — поэтому приведение здесь, а не в вызывающем коде."""
    from ecodoc.core.models import (Medium, NVOSObject, Pollutant, WasteAct,
                                    WasteFlow)
    from ecodoc.core.waste_agg import norm_fkko
    coll, sel, attr = parse_key(key)
    obj = None
    if coll == "organization":
        obj = ctx.organization
    elif coll == "period":
        obj = ctx.period
    elif coll == "objects":
        obj = next((o for o in ctx.objects if o.code == sel.get("code")), None)
        if obj is None and sel.get("code"):
            obj = NVOSObject(code=sel["code"],
                             region_code=sel["code"].split("-")[0])
            ctx.objects.append(obj)
    elif coll == "wastes":
        code = norm_fkko(sel.get("fkko", ""))
        obj = next((w for w in ctx.wastes if norm_fkko(w.fkko_code) == code), None)
        if obj is None and code:
            obj = WasteFlow(fkko_code=code)
            ctx.wastes.append(obj)
    elif coll == "waste_acts":
        want = key.rsplit(".", 1)[0]
        obj = next((a for a in ctx.waste_acts
                    if act_key(a.fkko_code, a.date, a.receiver, a.mass) == want), None)
        if obj is None and sel.get("fkko"):
            obj = WasteAct(fkko_code=sel["fkko"], date=sel.get("d", ""),
                           receiver=sel.get("r", ""))
            ctx.waste_acts.append(obj)
    elif coll == "pollutants":
        want_medium = Medium.AIR if sel.get("medium", "air") == "air" else Medium.WATER
        obj = next((p for p in ctx.pollutants
                    if p.medium == want_medium
                    and ((sel.get("code") and p.code == sel["code"])
                         or (not sel.get("code") and p.name == sel.get("name")))), None)
        if obj is None and (sel.get("code") or sel.get("name")):
            obj = Pollutant(code=sel.get("code", ""), name=sel.get("name", ""))
            obj.medium = want_medium
            ctx.pollutants.append(obj)
    if obj is None or not hasattr(obj, attr):
        return False
    if attr in _DEC_ATTRS:
        try:
            value = Decimal(str(value).replace(",", ".").replace(" ", ""))
        except (InvalidOperation, ValueError):
            return False
    elif attr in _INT_ATTRS:
        try:
            value = int(float(str(value).replace(",", ".")))
        except (TypeError, ValueError):
            return False
    else:
        value = str(value)
    setattr(obj, attr, value)
    return True


# ── хранилище ────────────────────────────────────────────────────────────

def path_for(site_dir: str | Path) -> Path:
    return Path(site_dir) / FILE


class Store:
    """Кандидаты площадки: чтение, дозапись с дедупом, решения пользователя."""

    def __init__(self, site_dir: str | Path):
        self.site_dir = Path(site_dir)
        self.items: list[Candidate] = []
        self.load()

    def load(self) -> "Store":
        p = path_for(self.site_dir)
        self.items = []
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                known = set(Candidate.__dataclass_fields__)
                self.items = [Candidate(**{k: v for k, v in it.items() if k in known})
                              for it in data.get("items", [])]
            except (OSError, json.JSONDecodeError, TypeError):
                self.items = []
        return self

    def save(self) -> Path:
        p = path_for(self.site_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1,
                                   "items": [asdict(c) for c in self.items]},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
        return p

    def add(self, cand: Candidate) -> Candidate:
        """Добавить находку. Повтор того же значения из того же файла не плодит
        дублей и НЕ воскрешает отклонённое пользователем."""
        with _LOCK:
            for c in self.items:
                if c.id == cand.id:
                    c.seen += 1
                    if not c.quote and cand.quote:
                        c.quote, c.page, c.exact = cand.quote, cand.page, cand.exact
                    return c
            self.items.append(cand)
            return cand

    def by_id(self, cid: str) -> Candidate | None:
        return next((c for c in self.items if c.id == cid), None)

    def fresh(self) -> list[Candidate]:
        return [c for c in self.items if c.state == NEW]


class Sink:
    """Приёмник находок для разбора: копит кандидатов и разом пишет в файл."""

    def __init__(self, site_dir: str | Path | None):
        self.store = Store(site_dir) if site_dir else None
        self.added: list[Candidate] = []

    def add(self, key: str, value, *, label: str = "", doc: str = "", file: str = "",
            page: int = 0, exact: bool = False, quote: str = "",
            method: str = "ai", model: str = "", unit: str = "") -> None:
        if self.store is None or not key or value in (None, ""):
            return
        c = Candidate(key=key, value=str(value), label=label or key, doc=doc,
                      file=file, page=page, exact=exact, quote=quote,
                      method=method, model=model, unit=unit)
        self.added.append(self.store.add(c))

    def flush(self) -> int:
        if self.store is None:
            return 0
        self.store.save()
        return len(self.added)
