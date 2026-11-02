"""A team of local readers for private paperwork.

A frontier model looks at a sample once and writes a plan (`design`). After that, no cloud: several small local readers go
over every page (`read_packet`), and plain code merges what they said (`merge`). The rule that makes it trustworthy is in
the code, not in a prompt: a value only counts if at least two reads back it and nothing contradicts it. Anything else goes
to a person, with the disagreeing values side by side.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .local import Glimmer, LocalModelError

MAX_READS_AT_ONCE = 8  # measured on one served Glimmer on four GPUs: throughput flattens here, and 20 at once only queue
FIELD_TYPES = {"id", "date", "number", "money", "name", "code", "text", "choice"}
BASE_RULES = ("This is one page from {document}. Copy only what this page itself shows, and never guess or calculate. "
              "Use null for anything this page does not show. Copy dates exactly as written. ")
_lock = threading.Lock()


# ---- Turning what was read into something comparable ------------------------------------------------------------------

MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


def parse_date(raw) -> str | None:
    """A US-style written date as YYYY-MM-DD, or None if it can't be read as one date. Never guesses a day-first order."""
    s = re.sub(r"\s+", " ", str(raw or "")).strip().strip(".,")
    if re.fullmatch(r"[\d\s/.-]+", s):  # readers sometimes add a stray space inside a numeric date: "3/2 3/24"
        s = re.sub(r"\s", "", s)
    y = mo = d = None
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})", s):
        mo, d, y = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{2}|\d{4})", s):
        mo, d, y = MONTHS.get(m[1][:3].lower()), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[ -]([A-Za-z]{3,9})\.?[ -](\d{2}|\d{4})", s):
        d, mo, y = int(m[1]), MONTHS.get(m[2][:3].lower()), int(m[3])
    if y is None or mo is None:
        return None
    if y < 100:  # a two-digit year can't be in the future
        y += 2000 if y <= dt.date.today().year % 100 else 1900
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def normal(value, kind: str = "text") -> str:
    """The form two reads are compared in. Differences in spacing, punctuation and word order aren't disagreements."""
    if value is None:
        return ""
    s = re.sub(r"\s+", " ", str(value)).strip()
    if s.lower() in ("", "null", "none", "n/a", "na", "unknown", "not stated", "not shown", "blank", "-", "--"):
        return ""
    if kind == "date":
        return parse_date(s) or s.lower()
    if kind == "number":
        m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
        return (m[0].rstrip("0").rstrip(".") if "." in m[0] else m[0]) if m else s.lower()
    if kind == "money":
        m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
        return f"{float(m[0]):.2f}" if m else s.lower()
    if kind in ("id", "code"):
        return re.sub(r"[\s\-_.]", "", s).upper() if kind == "id" else s.replace(" ", "").upper()
    if kind == "name":
        return " ".join(sorted(re.sub(r"[.,]", " ", s).lower().split()))
    s = s.lower().rstrip(".")
    return re.sub(r"(\d)\s*(mg|mcg|ml|g|%)\b", r"\1 \2", s)


# ---- The plan ---------------------------------------------------------------------------------------------------------

def check_plan(plan: dict) -> dict:
    """A plan comes from a model, so it's validated like any other outside input. It's data: code runs it, and never evals it."""
    if not isinstance(plan, dict) or not plan.get("document"):
        raise ValueError("the plan must say what the document is")
    fields, tables = plan.get("fields") or [], plan.get("tables") or []
    if not fields and not tables:
        raise ValueError("the plan has nothing to read")
    keys = set()
    for f in fields:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", str(f.get("key", ""))):
            raise ValueError(f"bad field key: {f.get('key')!r}")
        if f.get("type", "text") not in FIELD_TYPES:
            raise ValueError(f"bad type for {f['key']}: {f.get('type')!r}")
        keys.add(f["key"])
    columns = {}
    for t in tables:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", str(t.get("key", ""))) or not t.get("columns"):
            raise ValueError(f"bad table: {t.get('key')!r}")
        keys.add(t["key"])
        for c in t["columns"]:
            if c.get("type", "text") not in FIELD_TYPES:
                raise ValueError(f"bad column type in {t['key']}: {c.get('type')!r}")
        columns[t["key"]] = {c["key"] for c in t["columns"]}
    readers = plan.get("readers") or []
    if not readers:
        raise ValueError("the plan has no readers")
    for r in readers:
        unknown = set(r.get("reads") or []) - keys
        if unknown or not r.get("reads") or not r.get("name"):
            raise ValueError(f"reader {r.get('name')!r} reads unknown or no fields: {sorted(unknown)}")
    missing = keys - {k for r in readers for k in r["reads"]}
    if missing:
        raise ValueError(f"nobody reads: {sorted(missing)}")
    for c in plan.get("checks") or []:
        kind = c.get("kind")
        if kind == "date_order":
            if c.get("table") not in columns or not {c.get("first"), c.get("second")} <= columns[c["table"]]:
                if not {c.get("first"), c.get("second")} <= keys:
                    raise ValueError(f"bad date_order check: {c}")
        elif kind == "sum":
            if c.get("table") not in columns or c.get("column") not in columns[c["table"]] or c.get("total") not in keys:
                raise ValueError(f"bad sum check: {c}")
        elif kind != "min_complete_rows":
            raise ValueError(f"unknown check: {kind!r}")
        elif c.get("table") not in columns:
            raise ValueError(f"bad min_complete_rows check: {c}")
    return plan


PLAN_SHAPE = """{
 "name": "short name for this kind of paperwork",
 "document": "a phrase that finishes 'This is one page from ...', mentioning it may be a scan, fax or phone photo",
 "fields": [{"key": "snake_case", "label": "what a person calls it", "type": "id|date|number|money|name|code|text|choice", "note": "how to tell it apart from look-alikes on the page",
             "required": true, "identity": true, "choices": ["only for type choice"]}],
 "tables": [{"key": "snake_case", "label": "...", "columns": [{"key": "snake_case", "label": "...", "type": "...", "note": "..."}]}],
 "readers": [{"name": "short role", "instruction": "one or two sentences on what to read and what to ignore", "reads": ["field and table keys"]}],
 "checks": [{"kind": "min_complete_rows", "table": "key", "count": 1, "message": "why it matters"},
            {"kind": "date_order", "table": "key or omit for two fields", "first": "key", "second": "key"},
            {"kind": "sum", "table": "key", "column": "key", "total": "field key"}]
}"""
DESIGN_RULES = """You're designing a team of small, cheap vision models that will check stacks of this paperwork on someone's own computer, long after you're gone. Each small model sees one page at a time, can't remember anything, and is good at copying what's in front of it but bad at deciding things. Plain code merges what they say. A value only counts when two reads agree, and any disagreement goes to a person.

Design the plan for the paperwork shown:
- Fields: every value someone would need to check or copy into a system, including who or what the stack is about, marked "identity": true, so a page from the wrong stack is caught because identifiers disagree. Every field must have ONE true value for the whole stack, because any two different values are treated as a problem: never add a field that naturally differs from page to page, such as a document type, page title or per-document date or number. Fields that appear on several kinds of page are the most valuable, because pages check each other. Set "required": false for values that often aren't there. Use tables for repeating rows; the first column must name the row, and a table's columns must also agree between pages, so leave out any column that only some pages have unless they're marked in its note to be left blank elsewhere.
- Notes: warn the reader about look-alikes (a group number next to a member number, a shipping address next to a bank account).
- Readers: the first reads everything. Then add two or three specialists, each reading a subset, so every field is read at least twice per page. Say what to ignore.
- Checks: only ones that the document's logic implies. There's no other kind of check.
{note}
Reply with only one JSON object in this shape, no other text:
{shape}"""


def design(samples: list, note: str = "", model: str | None = None, limit_usd: float = 0.25, effort: str = "low") -> tuple[dict, dict]:
    """The one cloud step: the frontier model sees a blank form or sample once and writes the team. Returns the plan and what it cost."""
    from . import config
    from .cloud import Cloud, Meter, image_url, response_text
    from .local import extract_json

    meter = Meter()
    cloud = Cloud(meter=meter, limit_usd=limit_usd)
    extra = f"\nWhat the person told you: {note.strip()}\n" if note.strip() else ""
    content = [{"type": "input_text", "text": DESIGN_RULES.format(note=extra, shape=PLAN_SHAPE)}]
    for s in samples:
        im = Image.fromarray(load_page(s))
        im.thumbnail((1100, 1100))
        content.append({"type": "input_image", "image_url": image_url(np.asarray(im), 80)})
    resp = cloud.respond(model=model or config.TEACHER_MODEL, reasoning={"effort": effort}, max_output_tokens=4000, input=[{"role": "user", "content": content}])
    plan = check_plan(extract_json(response_text(resp)))
    return plan, meter.snapshot()


def _field_note(f: dict) -> str | None:
    note = f.get("note") or f.get("label") or None
    if f.get("choices"):
        note = (note + ". " if note else "") + "Exactly one of: " + ", ".join(f["choices"]) + ", or null if the page doesn't say"
    return note


def reader_prompt(plan: dict, reader: dict) -> tuple[str, dict]:
    prompt = BASE_RULES.format(document=plan["document"]) + (reader.get("instruction") or "")
    by_key = {f["key"]: f for f in plan.get("fields") or []}
    tables = {t["key"]: t for t in plan.get("tables") or []}
    shape: dict = {}
    for key in reader["reads"]:
        if key in by_key:
            shape[key] = _field_note(by_key[key])
        else:
            t = tables[key]
            shape[key] = [{c["key"]: _field_note(c) for c in t["columns"]}]
    return prompt, shape


# ---- Reading ----------------------------------------------------------------------------------------------------------

def load_page(source) -> np.ndarray:
    im = source if isinstance(source, Image.Image) else Image.open(source)
    im = im.convert("RGB")
    im.thumbnail((1700, 1700))
    return np.asarray(im)


def second_look(page: np.ndarray) -> np.ndarray:
    """The same page with stronger contrast and sharper edges. Identical input makes identical mistakes, and two identical mistakes look like agreement."""
    im = ImageOps.autocontrast(Image.fromarray(page).convert("L"), cutoff=1).filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=2))
    return np.asarray(im.convert("RGB"))


def _read_once(page_index: int, page: np.ndarray, plan: dict, reader: dict, url: str | None) -> dict:
    prompt, shape = reader_prompt(plan, reader)
    t0 = time.time()
    try:
        glimmer = Glimmer(url=url)
        view = second_look(page) if reader.get("view") == "second_look" else page
        data = glimmer.ask(prompt, image=view, schema=shape, max_tokens=1800) if reader.get("thinks") else glimmer.read_json(prompt, view, shape)
        return {"page": page_index, "reader": reader["name"], "data": data if isinstance(data, dict) else {}, "seconds": round(time.time() - t0, 1)}
    except (LocalModelError, ValueError) as e:
        return {"page": page_index, "reader": reader["name"], "data": {}, "seconds": round(time.time() - t0, 1), "error": str(e)[:200]}


def _found_something(answer: dict, keys: list[str]) -> bool:
    data = answer["data"]
    return any(data.get(k) not in (None, "", [], {}) and normal(data.get(k)) != "" for k in keys)


def read_packet(plan: dict, pages: list, readers: list[dict] | None = None, url: str | None = None,
                on_read: Callable[[dict], None] | None = None) -> list[dict]:
    """Nothing leaves this machine. The first reader scans every page. Then each specialist reads only the pages where the scan
    found something in its area, with a second view of the page so that two reads can't simply repeat one mistake. A page the scan
    wrongly passes over loses its second read, which can only send a value to a person, never settle one."""
    readers = plan["readers"] if readers is None else readers
    frames = [load_page(p) for p in pages]

    def work(job):
        out = _read_once(*job)
        if on_read:
            on_read(out)
        return out

    with ThreadPoolExecutor(MAX_READS_AT_ONCE) as ex:
        first = list(ex.map(work, [(i, f, plan, readers[0], url) for i, f in enumerate(frames)]))
        later = []
        for i, f in enumerate(frames):
            for r in readers[1:]:
                if first[i].get("error") or _found_something(first[i], r["reads"]):
                    later.append((i, f, plan, {**r, "view": r.get("view", "second_look")}, url))
                elif on_read:
                    on_read({"page": i, "reader": r["name"], "data": {}, "skipped": True})
        return first + list(ex.map(work, later))


# ---- Merging, in plain code -------------------------------------------------------------------------------------------

def _rows_match(a: str, b: str) -> bool:
    """Two rows are the same row if their names are equal, or one is the start of the other ("Hex bolts" and "Hex bolts, box of 100")."""
    if a == b:
        return True
    x, y = a.split(), b.split()
    n = min(len(x), len(y))
    return n > 0 and x[:n] == y[:n]


def vocabulary(name: str) -> set[str]:
    """A list of known words, one per line, for values where a slip of one letter matters and every reader makes the same slip."""
    file = Path(__file__).resolve().parent.parent / "plans" / "vocab" / f"{name}.txt"
    return {line.strip().lower() for line in file.read_text().splitlines() if line.strip()} if file.exists() else set()


def known_word(value, name: str) -> bool:
    """True if any word of the value is in the vocabulary, so a known name with a size after it passes and a misspelled one doesn't."""
    words = vocabulary(name)
    return not words or any(w in words for w in re.findall(r"[a-z]+", str(value).lower()))


def well_formed(value, kind: str) -> bool:
    """A value that can't be understood can't be checked, so it must never pass silently."""
    if kind == "date":
        return parse_date(value) is not None
    if kind in ("number", "money"):
        return re.search(r"\d", str(value)) is not None
    return True


def _votes(items: list[tuple[str, dict]]) -> list[dict]:
    """Group sightings by comparable value, most-backed first."""
    groups: dict[str, dict] = {}
    for value, seen in items:
        g = groups.setdefault(value, {"value": seen["raw"], "normal": value, "seen": []})
        g["seen"].append(seen)
    return sorted(groups.values(), key=lambda g: -len(g["seen"]))


def _settle(items: list[tuple[str, dict]], min_support: int) -> dict:
    votes = _votes(items)
    if not votes:
        return {"status": "missing", "value": None, "votes": []}
    if len(votes) > 1:
        return {"status": "conflict", "value": None, "votes": votes}
    if len(votes[0]["seen"]) < min_support:
        return {"status": "unconfirmed", "value": votes[0]["value"], "votes": votes}
    return {"status": "ok", "value": votes[0]["value"], "votes": votes}


def merge(plan: dict, answers: list[dict], min_support: int = 2) -> dict:
    """Decide what's settled and what a person must look at. No model is involved here."""
    started = time.time()
    fields, issues = [], []
    for f in plan.get("fields") or []:
        kind = f.get("type", "text")
        items = []
        for a in answers:
            raw = a["data"].get(f["key"])
            n = normal(raw, kind)
            if n:
                items.append((n, {"raw": str(raw).strip(), "page": a["page"], "reader": a["reader"]}))
        s = _settle(items, min_support)
        fields.append({"key": f["key"], "label": f.get("label") or f["key"], "type": kind, **s})
        required = f.get("required", True)
        if s["status"] == "conflict":
            issues.append({"kind": "identity" if f.get("identity") else "conflict", "field": f["key"], "label": f.get("label") or f["key"], "votes": s["votes"]})
        elif s["status"] == "missing" and required:
            issues.append({"kind": "missing", "field": f["key"], "label": f.get("label") or f["key"]})
        elif s["status"] == "unconfirmed" and required:
            issues.append({"kind": "unconfirmed", "field": f["key"], "label": f.get("label") or f["key"], "votes": s["votes"]})
        elif s["value"] and f.get("vocabulary") and not known_word(s["value"], f["vocabulary"]):
            issues.append({"kind": "unknown_word", "field": f["key"], "label": f.get("label") or f["key"], "votes": s["votes"]})
        elif s["value"] and not well_formed(s["value"], kind):
            issues.append({"kind": "unreadable", "field": f["key"], "label": f.get("label") or f["key"], "votes": s["votes"]})
        elif s["value"] and f.get("choices") and normal(s["value"]) not in [normal(c) for c in f["choices"]]:
            issues.append({"kind": "not_allowed", "field": f["key"], "label": f.get("label") or f["key"], "votes": s["votes"]})

    tables = []
    for t in plan.get("tables") or []:
        key_col = t["columns"][0]
        rows: list[dict] = []
        for a in answers:
            got = a["data"].get(t["key"])
            for row in got if isinstance(got, list) else []:
                if not isinstance(row, dict):
                    continue
                name = normal(row.get(key_col["key"]), key_col.get("type", "text"))
                if not name:
                    continue
                home = next((r for r in rows if _rows_match(r["name"], name)), None)
                if home is None:
                    home = {"name": name, "cells": {c["key"]: [] for c in t["columns"]}, "pages": set()}
                    rows.append(home)
                elif len(name) > len(home["name"]):
                    home["name"] = name
                home["pages"].add(a["page"])
                for c in t["columns"]:
                    n = normal(row.get(c["key"]), c.get("type", "text"))
                    if c is key_col:
                        home["cells"][c["key"]].append((home["name"], {"raw": str(row.get(c["key"])).strip(), "page": a["page"], "reader": a["reader"]}))
                    elif n:
                        home["cells"][c["key"]].append((n, {"raw": str(row.get(c["key"])).strip(), "page": a["page"], "reader": a["reader"]}))
        out_rows = []
        for r in rows:
            cells = {}
            for c in t["columns"]:
                items = r["cells"][c["key"]]
                if c is key_col:  # the longest spelling names the row; shorter ones were already matched to it
                    best = max(items, key=lambda it: len(it[1]["raw"]))[1]["raw"]
                    cells[c["key"]] = {"status": "ok" if len(items) >= min_support else "unconfirmed", "value": best, "votes": _votes([(r["name"], s) for _, s in items])}
                else:
                    cells[c["key"]] = _settle(items, min_support)
            out_rows.append({"cells": cells})
            for c in t["columns"]:
                s = cells[c["key"]]
                label = f"{cells[key_col['key']]['value']}: {c.get('label') or c['key']}"
                if s["status"] == "conflict":
                    issues.append({"kind": "conflict", "field": f"{t['key']}.{c['key']}", "label": label, "votes": s["votes"]})
                elif s["status"] == "unconfirmed":
                    issues.append({"kind": "unconfirmed", "field": f"{t['key']}.{c['key']}", "label": label, "votes": s["votes"]})
                elif s["value"] and c.get("vocabulary") and not known_word(s["value"], c["vocabulary"]):
                    issues.append({"kind": "unknown_word", "field": f"{t['key']}.{c['key']}", "label": label, "votes": s["votes"]})
                elif s["value"] and not well_formed(s["value"], c.get("type", "text")):
                    issues.append({"kind": "unreadable", "field": f"{t['key']}.{c['key']}", "label": label, "votes": s["votes"]})
                elif s["value"] and c.get("choices") and normal(s["value"]) not in [normal(x) for x in c["choices"]]:
                    issues.append({"kind": "not_allowed", "field": f"{t['key']}.{c['key']}", "label": label, "votes": s["votes"]})
        tables.append({"key": t["key"], "label": t.get("label") or t["key"], "columns": [{"key": c["key"], "label": c.get("label") or c["key"], "type": c.get("type", "text")} for c in t["columns"]], "rows": out_rows})

    by_table = {t["key"]: t for t in tables}
    by_field = {f["key"]: f for f in fields}
    for c in plan.get("checks") or []:
        if c["kind"] == "date_order":
            if c.get("table") in by_table:
                t = by_table[c["table"]]
                for r in t["rows"]:
                    a, b = r["cells"][c["first"]]["value"], r["cells"][c["second"]]["value"]
                    if a and b and parse_date(a) and parse_date(b) and parse_date(a) > parse_date(b):
                        name = r["cells"][t["columns"][0]["key"]]["value"]
                        issues.append({"kind": "date_order", "field": f"{t['key']}.{c['second']}", "label": f"{name}: ends before it starts", "text": f"{a} to {b}"})
            else:
                a, b = by_field[c["first"]]["value"], by_field[c["second"]]["value"]
                if a and b and parse_date(a) and parse_date(b) and parse_date(a) > parse_date(b):
                    issues.append({"kind": "date_order", "field": c["second"], "label": f"{by_field[c['first']]['label']} is after {by_field[c['second']]['label']}", "text": f"{a} to {b}"})
        elif c["kind"] == "min_complete_rows":
            t = by_table[c["table"]]
            done = sum(all(r["cells"][col["key"]]["status"] == "ok" for col in t["columns"]) for r in t["rows"])
            if done < c.get("count", 1):
                issues.append({"kind": "gap", "field": t["key"], "label": t["label"], "text": c.get("message") or f"needs {c.get('count', 1)} complete rows, found {done}"})
        elif c["kind"] == "sum":
            t = by_table[c["table"]]
            total = by_field[c["total"]]["value"]
            cells = [r["cells"][c["column"]]["value"] for r in t["rows"]]
            if total and cells and all(cells):
                added = round(sum(float(normal(v, "money")) for v in cells if re.fullmatch(r"-?\d+\.\d\d", normal(v, "money"))), 2)
                if f"{added:.2f}" != normal(total, "money"):
                    issues.append({"kind": "sum", "field": c["total"], "label": f"{by_field[c['total']]['label']} doesn't add up", "text": f"the rows add up to {added:.2f}, the page says {total}"})
    errors = [a for a in answers if a.get("error")]
    if errors:
        issues.append({"kind": "unread", "field": "", "label": "Some reads failed", "text": f"{len(errors)} of {len(answers)} reads gave no usable answer"})
    return {"status": "clear" if not issues else "needs_person", "fields": fields, "tables": tables, "issues": issues, "reads": len(answers),
            "merge_seconds": round(time.time() - started, 3)}


def process(plan: dict, pages: list, readers: list[dict] | None = None, min_support: int = 2, url: str | None = None,
            on_read: Callable[[dict], None] | None = None) -> dict:
    t0 = time.time()
    answers = read_packet(plan, pages, readers, url, on_read)
    out = merge(plan, answers, min_support)
    out.update(seconds=round(time.time() - t0, 1), pages=len(pages), answers=answers, cloud_usd=0.0)
    return out


def jsonable(x):
    return json.loads(json.dumps(x, default=lambda v: sorted(v) if isinstance(v, set) else str(v)))
