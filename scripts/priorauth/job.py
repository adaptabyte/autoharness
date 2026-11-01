#!/usr/bin/env python3
"""Run the prior-auth job on a made-up patient and score every field against the truth in cases.json.
Part 1 reads the chart in OpenEMR. Part 2 fills the portal from what part 1 read, never from the truth, so chart mistakes carry through.
  job.py glimmer <case,case> [--skill]    Glimmer from screenshots
  job.py harness <case,case>              the two programs the lessons wrote
Results go to docs/priorauth.jsonl."""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import benchmark as b  # noqa: E402

CASES = {c["id"]: c for c in json.loads((Path(__file__).parent / "cases.json").read_text())}
OUT = ROOT / "docs" / "priorauth.jsonl"
# Same rules as the benchmark, plus two things found by replaying frames: an unbounded scroll jumped past the middle of the chart, and nothing read off a screen survived scrolling.
RULES = b.GLIMMER_RULES.replace('{{"action": "scroll", "x": 500, "y": 500, "dy": 3}}', '{{"action": "scroll", "x": 500, "y": 500, "dy": 3}}  (dy is wheel notches, from -8 to 8; negative scrolls up)').replace(
    "Look at the screenshot and choose", 'Whatever you read may scroll away and you will forget it. Add "note": "exactly what you read" to any action to keep it for the rest of the job.\n\nLook at the screenshot and choose')
SHAPE = '{"member_id": "", "dob": "YYYY-MM-DD", "icd10": "", "drug": "", "strength": "", "quantity": 0, "days": 0, "trials": [{"drug": "", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "outcome": ""}], "missing": ["anything the chart does not say"]}'


def chart_goal(c: dict) -> str:
    return (f"Log in to OpenEMR with username admin and password pass. Open the chart of patient {c['first']} {c['last']} and read their plan member ID, date of birth, diagnosis and medication history. "
            "The External ID in Demographics is the plan member ID. The Issues tab lists medical problems and medications; each row expands to show dates and comments. "
            "The active medication whose comment says 'New order' is what is being requested. Inactive medications are prior treatments. Copy only what the chart says and change nothing. "
            "An outcome is what the comment says after 'Stopped:'. If a date or outcome isn't recorded, leave it empty and name it in missing. "
            f"When you've read it all, finish with this JSON as your finished text: {SHAPE}")


def portal_goal(facts: dict) -> str:
    facts = {k: v for k, v in facts.items() if k != "missing"}
    return ("Log in with username clinic01 and password demo-pass. Start a new prior authorization and fill it in with exactly these facts: "
            f"{json.dumps(facts)}. Add each prior treatment with its own Add treatment button. When the review page looks right, press Save for prescriber signature, and finish by reporting the reference number. "
            "Never try to sign or submit it: a person does that. If the plan needs something these facts don't have, stop and say what is missing. Never make anything up.")


def parse_facts(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    try:
        return json.loads(text[start:end + 1]) if start >= 0 else None
    except ValueError:
        return None


def records(member_id: str, since: float) -> list[dict]:
    rows = json.loads(urllib.request.urlopen("http://127.0.0.1:8310/_requests.json", timeout=10).read())
    return [r for r in rows if r.get("member_id") == member_id and r["at"] >= since]


def norm(x) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip().lower()


def score_record(c: dict, r: dict) -> list[str]:
    """Every mismatch between what was saved and the truth."""
    want = c["request"]
    wrong = [f"{k}: {r.get(k)!r}, chart says {v!r}" for k, v in dict(member_id=c["member_id"], dob=c["dob"], drug=want["drug"], strength=want["strength"], quantity=str(want["quantity"]), days=str(want["days"]), icd10=c["icd10"]).items() if norm(r.get(k)) != norm(v)]
    got = sorted((norm(t["drug"]), t["start"], t["end"], norm(t["outcome"])) for t in r.get("trials") or [])
    truth = sorted((norm(t["drug"]), t["start"], t["end"], norm(t["outcome"])) for t in c["trials"])
    if got != truth:
        wrong.append(f"prior treatments: {got}, chart says {truth}")
    if not r.get("status", "").startswith("Awaiting"):
        wrong.append(f"status: {r.get('status')}")
    return wrong


def judge_job(c: dict, facts: dict | None, saved: list[dict]) -> tuple[bool, str]:
    if c["id"] == "incomplete":
        # The chart can't support a request: the only right ending is no saved request and the gap named.
        if saved:
            return False, f"saved a request the chart can't support: {saved[-1]['ref']}, treatments {saved[-1]['trials']}"
        return bool(facts and facts.get("missing")), "saved nothing and named what's missing" if facts and facts.get("missing") else "saved nothing, but never named what's missing"
    if len(saved) != 1:
        return False, f"{len(saved)} saved requests, expected exactly 1"
    wrong = score_record(c, saved[0])
    return not wrong, "; ".join(wrong) or f"all fields match, {saved[0]['ref']} awaits signature"


def glimmer_part(spec: dict, goal: str, skill: str = "") -> dict:
    display = b.Display(*spec.get("size", (1280, 800))).start()
    target = b.targets.Target(spec, display)
    try:
        return b.glimmer_screens(display, target, goal, skill, b.GLIMMER_SECONDS, b.GLIMMER_STEPS, rules=RULES, max_scroll=8)
    finally:
        target.stop()
        display.stop()


def run_glimmer(case_id: str, chart_skill: str = "", portal_skill: str = "") -> dict:
    c = CASES[case_id]
    t0 = time.time()
    rec = {"case": case_id, "contestant": "glimmer_skill_notes" if chart_skill or portal_skill else "glimmer_notes", "at": t0, "usd": 0.0}
    chart = glimmer_part(b.targets.get_spec("openemr"), chart_goal(c), chart_skill)
    facts = parse_facts(chart.get("answer", ""))
    rec.update(chart_seconds=chart["seconds"], chart_steps=chart["steps"], chart_status=chart["status"], facts=facts, chart_notes=chart.get("notes"), chart_answer=chart.get("answer", "")[:600])
    saved: list[dict] = []
    if facts and not facts.get("missing"):  # anything missing goes to a person; the same rule for every patient
        portal = glimmer_part(b.targets.get_spec("priorauth-portal"), portal_goal(facts), portal_skill)
        rec.update(portal_seconds=portal["seconds"], portal_steps=portal["steps"], portal_status=portal["status"], portal_answer=portal.get("answer", "")[:400])
        saved = records(c["member_id"], t0)
    ok, detail = judge_job(c, facts, saved)
    rec.update(ok=ok, detail=detail, seconds=round(time.time() - t0, 1), saved=[r["ref"] for r in saved])
    with OUT.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"{case_id} {rec['contestant']}: {'PASS' if ok else 'FAIL'} {rec['seconds']} s | {detail[:200]}", flush=True)
    return rec


def harness_part(package: str, params: dict, seconds: int = 300):
    pkg = b.library.get(package)
    display = b.Display(*pkg.manifest["target"].get("size", (1280, 800))).start()
    target = b.targets.Target(pkg.manifest["target"], display)
    target.reset()
    try:
        return b.Runner(pkg, display, None, params, max_seconds=seconds).execute(local_only=True)
    finally:
        target.stop()
        display.stop()


def run_harness(case_id: str) -> dict:
    """The two programs the lessons wrote, one feeding the other, with no model at all."""
    c = CASES[case_id]
    t0 = time.time()
    rec = {"case": case_id, "contestant": "harness", "at": t0, "usd": 0.0}
    chart = harness_part("openemr-chart-reader", {"first_name": c["first"], "last_name": c["last"]})
    facts = chart.result if isinstance(chart.result, dict) else None
    rec.update(chart_seconds=chart.seconds, chart_status=chart.status, chart_reason=str(chart.reason)[:300], facts=facts)
    saved: list[dict] = []
    if facts and not facts.get("missing"):
        portal = harness_part("prior-auth-portal", {k: v for k, v in facts.items() if k != "missing"})
        rec.update(portal_seconds=portal.seconds, portal_status=portal.status, portal_reason=str(portal.reason)[:300])
        saved = records(c["member_id"], t0)
    ok, detail = judge_job(c, facts, saved)
    rec.update(ok=ok, detail=detail, seconds=round(time.time() - t0, 1), saved=[r["ref"] for r in saved])
    with OUT.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"{case_id} harness: {'PASS' if ok else 'FAIL'} {rec['seconds']} s | {detail[:300]}\n  chart {chart.status} {str(chart.reason)[:200]}\n  facts {json.dumps(facts, default=str)[:600]}\n  portal {rec.get('portal_status')} {rec.get('portal_reason')}", flush=True)
    return rec


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "harness":
        for case in sys.argv[2].split(","):
            run_harness(case)
        sys.exit(0)
    if len(sys.argv) < 3 or sys.argv[1] != "glimmer":
        sys.exit(__doc__)
    skills = Path(__file__).parent / "skills"
    guides = ((skills / "chart.md").read_text(), (skills / "portal.md").read_text()) if "--skill" in sys.argv else ("", "")
    for case in sys.argv[2].split(","):
        run_glimmer(case, *guides)
