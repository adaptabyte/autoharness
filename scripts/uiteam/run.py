#!/usr/bin/env python3
"""Compile any interface into a plan a small model can run, then test it on inputs it hasn't seen.
  run.py explore <app> <job>        Spark does a job once; the record is saved (cloud)
  run.py compile <app>              Wonder writes the plan from all the records (cloud)
  run.py prove <app> <job> [--n 5]  Glimmer runs it on new inputs; truth comes from the app's own data (local)
  run.py teach <app> <job>          prove, sending each failure to Wonder for repair (cloud), until it holds or the money runs out

THE BAR, written before the first run and not to be moved after a result. Evidence is read from the app's own database or store, never from the run's claim.
  - Each job, 5 runs on inputs not used for teaching.
  - wrong_saved == 0: no run may claim success with a wrong result, or leave a wrong record.
  - passes >= 4 of 5. A run that stops and asks for help isn't a pass, but it isn't an error either.
  - No cloud at run time.
Compared with the earlier results on these same jobs: Glimmer + the harness 0/3 on untaught OpenEMR jobs, Spark 3/3 (179-367 s, $0.09-0.19), Glimmer with guides 0/6 reading a chart, generated programs 0/2 on the portal."""
from __future__ import annotations

import argparse
import json
import pickle
import random
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "priorauth"), str(Path(__file__).parent)]
from autoharness import config, targets, team, uiteam  # noqa: E402
from autoharness.cloud import BudgetExceeded, CloudError, Meter  # noqa: E402
from autoharness.desktop import Display  # noqa: E402

import jobs as J  # noqa: E402

WORK = config.HOME / "uiteam"
OUT = ROOT / "docs" / "uiteam.jsonl"


def records_dir(app: str) -> Path:
    d = WORK / app
    d.mkdir(parents=True, exist_ok=True)
    return d


def with_app(app: str, body):
    spec = J.APPS[app]["spec"]()
    display = Display(*spec.get("size", (1280, 800))).start()
    target = targets.Target(spec, display)
    try:
        return body(display, target)
    finally:
        target.stop()
        display.stop()


def do_explore(app: str, job: str) -> None:
    info = J.APPS[app]["jobs"][job]
    goal = info["goal"](info["teach"])
    meter = Meter()

    def body(display, target):
        return uiteam.explore(display, target, goal, meter, limit_usd=info.get("limit", 0.6), emit=lambda e: print(e.get("turn"), e.get("said", "")[:140], f"${e.get('usd')}", flush=True))
    rec = with_app(app, body)
    (records_dir(app) / f"{job}.pkl").write_bytes(pickle.dumps(rec))
    print(json.dumps({"job": job, "status": rec["status"], "turns": rec["turns"], "usd": rec["usd"]}))


def do_compile(app: str) -> None:
    recs = [pickle.loads(f.read_bytes()) for f in sorted(records_dir(app).glob("*.pkl"))]
    meter = Meter()
    plan = uiteam.compile_plan(recs, J.APPS[app].get("note", ""), meter=meter)
    plan["compile_usd"] = meter.usd
    (records_dir(app) / "plan.json").write_text(json.dumps(plan, indent=1))
    print(json.dumps(meter.snapshot()))
    print(json.dumps({"skills": {s["name"]: len(json.dumps(s["steps"])) for s in plan["skills"]}, "jobs": plan.get("jobs")}))


def one_run(app: str, job: str, i: int, plan: dict, label: str) -> dict:
    info = J.APPS[app]["jobs"][job]
    inputs = info["inputs"](i)
    skill = info.get("skill") or plan.get("jobs", {}).get(job) or job

    def body(display, target):
        before = info["before"](inputs) if info.get("before") else None
        target.reset()
        runner = uiteam.PlanRunner(plan, display, emit=lambda e: print("   ", e["do"], "ok" if e["ok"] else "FAIL", e["what"][:70], e["detail"][:70], e["seconds"], flush=True) if VERBOSE else None, max_seconds=info.get("seconds", 500))
        result = runner.run(skill, info["plan_inputs"](inputs) if info.get("plan_inputs") else inputs)
        ok, detail, wrong = info["judge"](result, inputs, before)
        return dict(result=result, ok=ok, detail=detail, wrong=wrong, frames=runner.frames)
    out = with_app(app, body)
    r = out["result"]
    rec = dict(run=label, app=app, job=job, i=i, ok=out["ok"], wrong_saved=out["wrong"], detail=out["detail"], status=r["status"], reason=r["reason"][:300], seconds=r["seconds"], questions=r["questions"], steps=r["steps"], usd=0.0, at=time.time())
    with OUT.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"{job} {i}: {'PASS' if out['ok'] else 'FAIL'}{' WRONG' if out['wrong'] else ''} {r['seconds']} s, {r['questions']} questions | {r['status']} {r['reason'][:150]} | {out['detail'][:150]}", flush=True)
    return {**out, "rec": rec}


def do_prove(app: str, job: str, n: int, label: str, start: int = 1) -> dict:
    plan = uiteam.check_plan(json.loads((records_dir(app) / "plan.json").read_text()))
    rows = [one_run(app, job, i, plan, label)["rec"] for i in range(start, start + n)]
    secs = sorted(r["seconds"] for r in rows)
    out = dict(job=job, passes=sum(r["ok"] for r in rows), runs=n, wrong_saved=sum(bool(r["wrong_saved"]) for r in rows), median_s=secs[len(secs) // 2], median_questions=sorted(r["questions"] for r in rows)[len(rows) // 2])
    out["passes_bar"] = out["wrong_saved"] == 0 and out["passes"] >= max(1, int(.8 * n))
    print(json.dumps(out), flush=True)
    return out


def do_teach(app: str, job: str, rounds: int = 6, cap: float = 2.0) -> None:
    """Wonder repairs from what each failed proof run shows. Teaching inputs are 100 and up, so the proof inputs stay unseen."""
    path = records_dir(app) / "plan.json"
    plan = uiteam.check_plan(json.loads(path.read_text()))
    meter = Meter()
    for round_no in range(rounds):
        out = one_run(app, job, 100 + round_no, plan, f"teach-{job}")
        if out["ok"]:
            again = one_run(app, job, 150 + round_no, plan, f"teach-{job}")
            if again["ok"]:
                print(f"{job}: holds after {round_no} repairs, ${meter.usd:.3f}", flush=True)
                return
            out = again
        if meter.usd >= cap:
            print(f"{job}: repair money for this job is gone, ${meter.usd:.3f}", flush=True)
            return
        failure = {"job": job, "skill": J.APPS[app]["jobs"][job].get("skill") or plan.get("jobs", {}).get(job) or job, "status": out["result"]["status"], "reason": out["result"]["reason"], "checker": out["detail"], "trace": out["result"]["trace"][-40:]}
        try:
            plan = uiteam.repair_plan(plan, failure, out["frames"], meter=meter)
        except (ValueError, CloudError, BudgetExceeded) as e:
            print("repair failed:", str(e)[:300], flush=True)
            continue
        plan["repair_usd"] = plan.get("repair_usd", 0) + 0
        path.write_text(json.dumps(plan, indent=1))
        print(f"repaired, ${meter.usd:.3f} so far", flush=True)


VERBOSE = True
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["explore", "compile", "prove", "teach"])
    ap.add_argument("app")
    ap.add_argument("job", nargs="?")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--label", default="proof")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--rounds", type=int, default=6)
    a = ap.parse_args()
    VERBOSE = not a.quiet
    if a.what == "explore":
        do_explore(a.app, a.job)
    elif a.what == "compile":
        do_compile(a.app)
    elif a.what == "prove":
        do_prove(a.app, a.job, a.n, a.label)
    else:
        do_teach(a.app, a.job, a.rounds)
