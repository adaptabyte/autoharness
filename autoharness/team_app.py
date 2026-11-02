"""The paperwork app's server side: plans, stacks of pages, reading, a person's decisions, and handing off to the demo portal."""
from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from . import config, team

BUILTIN_PLANS = config.REPO / "plans"
SAMPLES = config.REPO / "samples"
PLANS = config.HOME / "plans"
STACKS = config.HOME / "stacks"
MAX_PAGES = 30
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic"}


def all_plans() -> dict[str, dict]:
    out = {}
    for folder in (BUILTIN_PLANS, PLANS):
        for f in sorted(folder.glob("*.json")) if folder.exists() else []:
            try:
                out[f.stem] = {**team.check_plan(json.loads(f.read_text())), "id": f.stem}
            except ValueError:
                continue
    return out


def get_plan(plan_id: str) -> dict:
    plan = all_plans().get(plan_id)
    if not plan:
        raise KeyError(plan_id)
    return plan


def plan_brief(p: dict) -> dict:
    return {"id": p["id"], "name": p.get("name") or p["id"], "designed_by": p.get("designed_by"), "cost": p.get("design_usd"), "hand_off": (p.get("hand_off") or {}).get("label"),
            "readers": [r["name"] for r in p["readers"]], "fields": [f.get("label") or f["key"] for f in p.get("fields") or []] + [t.get("label") or t["key"] for t in p.get("tables") or []],
            "checks": [c["kind"] for c in p.get("checks") or []]}


def all_samples() -> list[dict]:
    out = []
    for meta in sorted(SAMPLES.glob("*/meta.json")) if SAMPLES.exists() else []:
        d = json.loads(meta.read_text())
        out.append({**d, "id": meta.parent.name, "pages": len(d.get("files") or [])})
    return sorted(out, key=lambda s: s.get("order", 99))


def _pages_from(source: Path, dest: Path, start: int) -> int:
    """One uploaded file into numbered page images. A PDF becomes one image per page."""
    n = start
    if source.suffix.lower() == ".pdf":
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["pdftoppm", "-r", "170", "-jpeg", "-l", str(MAX_PAGES), str(source), f"{tmp}/p"], check=True, capture_output=True, timeout=120)
            for f in sorted(Path(tmp).glob("*.jpg")):
                shutil.move(str(f), dest / f"{n:03d}.jpg")
                n += 1
        return n
    if source.suffix.lower() not in IMAGE_TYPES:
        raise ValueError(f"{source.name}: use photos, scans or PDFs")
    im = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    im.thumbnail((2000, 2000))
    im.save(dest / f"{n:03d}.jpg", quality=90)
    return n + 1


def new_stack(plan_id: str, sources: list[Path], title: str = "") -> dict:
    get_plan(plan_id)
    if not sources:
        raise ValueError("add at least one page")
    stack_id = secrets.token_hex(5)
    d = STACKS / stack_id
    d.mkdir(parents=True, mode=0o700)
    n = 0
    for s in sources:
        n = _pages_from(s, d, n)
    if not 1 <= n <= MAX_PAGES:
        shutil.rmtree(d)
        raise ValueError(f"a stack can have 1 to {MAX_PAGES} pages")
    meta = {"id": stack_id, "plan": plan_id, "pages": n, "title": title, "created": time.time()}
    (d / "stack.json").write_text(json.dumps(meta))
    return meta


def stack_dir(stack_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{10}", stack_id) or not (STACKS / stack_id).is_dir():
        raise KeyError(stack_id)
    return STACKS / stack_id


def sample_files(sample_id: str) -> tuple[list[Path], dict]:
    meta = next((s for s in all_samples() if s["id"] == sample_id), None)
    if not meta:
        raise KeyError(sample_id)
    return [SAMPLES / sample_id / f for f in meta["files"]], meta


def page_files(stack_id: str) -> list[Path]:
    return sorted(stack_dir(stack_id).glob("[0-9][0-9][0-9].jpg"))


def run_stack(job, stack_id: str) -> None:
    """Read and merge, entirely on this machine, emitting each finished read so the screen can show the team working."""
    d = stack_dir(stack_id)
    meta = json.loads((d / "stack.json").read_text())
    plan = get_plan(meta["plan"])
    pages = page_files(stack_id)
    total = len(pages) * len(plan["readers"])
    done = [0]
    job.emit({"type": "start", "stack": stack_id, "pages": len(pages), "readers": [r["name"] for r in plan["readers"]], "total": total})

    def on_read(a: dict) -> None:
        done[0] += 1
        job.emit({"type": "read", "page": a["page"], "reader": a["reader"], "ok": not a.get("error"), "skipped": bool(a.get("skipped")), "done": done[0], "total": total})

    result = team.process(plan, pages, on_read=on_read)
    add_close_ups(d, pages, result)
    (d / "result.json").write_text(json.dumps(team.jsonable(result)))
    job.emit({"type": "result", "stack": stack_id, "result": public_result(result)})


def add_close_ups(d: Path, pages: list[Path], result: dict) -> None:
    """For each disagreement, a close-up of each value where it's written, so a person can see the difference at a glance."""
    n = 0
    for issue in result["issues"][:6]:
        for vote in issue.get("votes") or []:
            if not vote.get("seen"):
                continue
            page = vote["seen"][0]["page"]
            im = Image.open(pages[page]).convert("RGB")
            spot = team.where_is(np.asarray(im), str(vote["value"]))
            if not spot:
                continue
            w, h = im.size
            box = (max(0, int((spot[0] - .24) * w)), max(0, int((spot[1] - .045) * h)), min(w, int((spot[0] + .24) * w)), min(h, int((spot[1] + .045) * h)))
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            im.crop(box).save(d / f"closeup{n}.jpg", quality=88)
            vote["closeup"] = n
            n += 1


def public_result(result: dict) -> dict:
    return team.jsonable({k: v for k, v in result.items() if k != "answers"})


def read_result(stack_id: str) -> dict:
    d = stack_dir(stack_id)
    meta = json.loads((d / "stack.json").read_text())
    file = d / "result.json"
    return {"stack": meta, "plan": plan_brief(get_plan(meta["plan"])), "result": public_result(json.loads(file.read_text())) if file.exists() else None,
            "decision": json.loads((d / "decision.json").read_text()) if (d / "decision.json").exists() else None}


def decide(stack_id: str, body: dict) -> dict:
    """A person's decision is recorded with what they saw. Nothing downstream runs without one."""
    d = stack_dir(stack_id)
    if not (d / "result.json").exists():
        raise ValueError("this stack hasn't been read yet")
    action = body.get("action")
    if action not in ("approve", "send_back"):
        raise ValueError("approve or send_back")
    record = {"action": action, "values": body.get("values") or {}, "rows": body.get("rows") or {}, "resolved": body.get("resolved") or [], "reason": str(body.get("reason") or "")[:500], "at": time.time()}
    (d / "decision.json").write_text(json.dumps(record, indent=1))
    return record


def design_plan(sources: list[Path], note: str, limit_usd: float = 0.25) -> dict:
    """The only cloud step, and only when someone asks for it. It sends the sample pages to Meta's API, so use a blank form."""
    with tempfile.TemporaryDirectory() as tmp:
        n = 0
        for s in sources:
            n = _pages_from(s, Path(tmp), n)
        pages = sorted(Path(tmp).glob("*.jpg"))[:4]
        plan, cost = team.design(pages, note, limit_usd=limit_usd)
    plan["designed_by"] = config.TEACHER_MODEL
    plan["design_usd"] = cost["usd"]
    PLANS.mkdir(parents=True, exist_ok=True)
    plan_id = re.sub(r"[^a-z0-9]+", "-", str(plan.get("name", "paperwork")).lower()).strip("-")[:40] or "paperwork"
    if plan_id in all_plans():
        plan_id += "-" + secrets.token_hex(2)
    (PLANS / f"{plan_id}.json").write_text(json.dumps(plan, indent=1))
    return plan_brief(get_plan(plan_id)) | {"cost": cost}


# ---- The hand-off: approved values go to a compiled interface, so no connector is ever written by hand --------------------

def hand_off_inputs(stack_id: str) -> tuple[str, str, dict]:
    """A plan's hand_off says which compiled interface takes the approved values, and under what names. Dates are normalised, since the receiving form has its own format."""
    d = stack_dir(stack_id)
    decision = json.loads((d / "decision.json").read_text())
    if decision["action"] != "approve":
        raise ValueError("a person hasn't approved this stack")
    plan = get_plan(json.loads((d / "stack.json").read_text())["plan"])
    off = plan.get("hand_off")
    if not off:
        raise ValueError("this kind of paperwork doesn't hand off to anything")
    kinds = {f["key"]: f.get("type", "text") for f in plan.get("fields") or []}
    columns = {t["key"]: {c["key"]: c.get("type", "text") for c in t["columns"]} for t in plan.get("tables") or []}

    def clean(value, kind: str):
        if kind == "date":
            return team.parse_date(value) or value
        if kind == "number":
            return team.normal(value, "number")
        return value

    inputs = dict(off.get("fixed") or {})
    for name, source in off.get("map", {}).items():
        if source in kinds:
            inputs[name] = clean(decision["values"].get(source, ""), kinds[source])
        else:
            inputs[name] = [{c: clean(v, columns[source].get(c, "text")) for c, v in row.items()} for row in decision["rows"].get(source, [])]
    return off["interface"], off["skill"], inputs


def proof() -> dict | None:
    """The home page's table, worked out from the raw runs each time so no number is typed in."""
    file = config.REPO / "docs" / "paperwork-final.json"
    return json.loads(file.read_text()) if file.exists() else None
