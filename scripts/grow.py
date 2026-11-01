#!/usr/bin/env python3
"""Can a harness grow? Glimmer is asked for jobs its program can't do. The teacher extends the program once, using
example patients. Then Glimmer gets the same kinds of job on patients the teacher never saw, checked by a separate login.

  grow.py before    Glimmer + the original program, and Glimmer + screenshots + markdown skill, on the held-out jobs
  grow.py teach     one call to the teacher, on a copy of the program, with a spending limit
  grow.py after     Glimmer + the grown program on the held-out jobs
Results go to docs/grow.jsonl."""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "priorauth")]
import benchmark as b  # noqa: E402
import job  # noqa: E402

OUT = ROOT / "docs" / "grow.jsonl"
LOGIN = "Log in with username admin and password pass. "
LIMIT_USD = 1.00
HELD_OUT = [
    ("read_dob", "Lena Brightman", "1", LOGIN + "Find the patient Lena Brightman and report their date of birth."),
    ("read_dob", "Imani Thackwell", "2", LOGIN + "Find the patient Imani Thackwell and report their date of birth."),
    ("set_phone", "Tobias Winterton", "1", LOGIN + "Open the patient Tobias Winterton and set their home phone number to 555-0123, then save."),
    ("set_phone", "Dariusz Fenwick", "2", LOGIN + "Open the patient Dariusz Fenwick and set their home phone number to 555-0124, then save."),
    ("count", "Okafor", "1", LOGIN + "Report how many patient records have the last name Okafor."),
    ("count", "Ashby", "2", LOGIN + "Report how many patient records have the last name Ashby."),
]
INSTRUCTION = """Do this first, before anything else: registering a patient already works, so leave it alone. Use try_interface to test each new verb. Muse Glimmer, a small local model that only has observe() and the verbs, was asked for three kinds of job and correctly said it had no verb for them. Add general verbs for them, working for ANY patient, and keep everything that works now:
1. find a patient by name and read their date of birth. Example: Marcus Oyelaran.
2. open an existing patient by name and set their home phone. Example: Priya Nakamura.
3. count how many patient records have a given last name, across every page of the list. Example: Synthetic.
Every verb must return what it found, and must confirm on screen the right patient is open before reading or changing anything. Similar names exist, so match first and last name exactly. Report failure rather than guessing. Don't hard-code the example patients. Try each new verb on its example before finishing, then keep passing the existing goal."""


def dob_of(name: str) -> str:
    return next(c["dob"] for c in job.CASES.values() if f"{c['first']} {c['last']}" == name)


def check(kind: str, who: str, goal: str, answer: str) -> tuple[bool, str]:
    last = who.split()[-1]
    if kind == "read_dob":
        return dob_of(who) in answer, f"chart says {dob_of(who)}"
    found = b.read_records(last)
    if kind == "set_phone":
        phone = re.search(r"555-\d{4}", goal).group().replace("-", "")
        rows = [r for r in found["records"] if f"{r['first']} {r['last']}" == who]
        return any(phone in re.sub(r"\D", "", r.get("phone") or "") for r in rows), f"saved rows: {[r.get('phone') for r in rows]}"
    return str(found["total"]) in re.findall(r"\d+", answer), f"the patient list holds {found['total']}"


def attempt(contestant: str, package: str, kind: str, who: str, i: str, goal: str) -> dict:
    pkg = b.library.get(package)
    display = b.Display(*pkg.manifest["target"].get("size", (1280, 800))).start()
    target = b.targets.Target(pkg.manifest["target"], display)
    rec = {"contestant": contestant, "job": kind, "who": who, "i": i, "at": time.time(), "usd": 0.0}
    try:
        if contestant == "glimmer_skill":
            out = b.glimmer_screens(display, target, goal, b.skill_for(pkg), 600, b.GLIMMER_STEPS, rules=job.RULES, max_scroll=8)
            claimed, answer, steps = out["claimed"], out["answer"], out["steps"]
            seconds = out["seconds"]
        else:
            target.reset()
            session = b.Session(pkg, display, target, None)
            session.interface = pkg.manifest.get("interface") or {}
            o = b.operate(session, goal, lambda e: None, max_steps=25)
            claimed, answer, steps, seconds = o["finished"], o["answer"], o["steps"], o["seconds"]
        right, detail = check(kind, who, goal, answer)
        rec.update(claimed=claimed, answer=answer[:400], steps=steps, seconds=seconds, right=right, detail=detail, ok=bool(claimed and right))
    except Exception as e:  # noqa: BLE001 - one bad run is a data point
        rec.update(claimed=False, ok=False, right=False, detail=f"crashed: {type(e).__name__}: {e}"[:300], seconds=round(time.time() - rec["at"], 1))
    finally:
        target.stop()
        display.stop()
    with OUT.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"{contestant} {kind} {who}: {'PASS' if rec['ok'] else 'FAIL'} {rec.get('seconds')} s | {rec.get('detail')} | {str(rec.get('answer'))[:160]}", flush=True)
    return rec


def teach() -> None:
    from autoharness.teacher import Teacher
    src = Path.home() / ".autoharness" / "library" / "openemr"
    dst = src.parent / "openemr-grown"
    if not dst.exists():
        shutil.copytree(src, dst)
    pkg = b.library.get("openemr-grown")
    pkg.update(name="OpenEMR, grown")
    spec = pkg.manifest["target"]
    display = b.Display(*spec.get("size", (1280, 800))).start()
    target = b.targets.Target(spec, display)
    t0 = time.time()
    start = b.cloudmod.Ledger.read()["spent_usd"]
    try:
        m = Teacher(pkg, display, target, lambda e: print(str(e)[:220], flush=True) if e.get("type") in ("log", "say", "error", "verify_end", "interface_end", "phase") else None,
                    limit_usd=LIMIT_USD, verify_runs=3, sample_params=spec.get("sample_params")).improve(INSTRUCTION, add_verbs=True)
    finally:
        target.stop()
        display.stop()
    rec = {"contestant": "teacher", "at": t0, "seconds": round(time.time() - t0), "usd": round(b.cloudmod.Ledger.read()["spent_usd"] - start, 4), "attempt": 2, "status": m.get("status"), "failure": m.get("failure"), "improvement_failed": m.get("improvement_failed"),
           "verified": m.get("verified"), "interface_verified": m.get("interface_verified"), "verbs": [v["name"] for v in (m.get("interface") or {}).get("verbs", [])]}
    with OUT.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(json.dumps(rec, indent=1), flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "before":
        for case in HELD_OUT[::2]:
            attempt("glimmer_program", "openemr", *case)
        for case in HELD_OUT[::2]:
            attempt("glimmer_skill", "openemr", *case)
    elif cmd == "teach":
        teach()
    elif cmd == "after":
        for case in HELD_OUT:
            attempt("glimmer_grown", "openemr-grown", *case)
    else:
        sys.exit(__doc__)
