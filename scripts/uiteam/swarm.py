#!/usr/bin/env python3
"""A swarm: many copies of one interface, each run by its own PlanRunner, all sharing one served Glimmer.
  swarm.py portal save_request 1 4 8     runs that many at once, on made-up patients
Every result is checked against the portal's own store. Results go to docs/uiteam.jsonl with run swarm-N."""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "priorauth"), str(Path(__file__).parent)]
from autoharness import config, targets, uiteam  # noqa: E402
from autoharness.desktop import Display  # noqa: E402

import jobs as J  # noqa: E402

CASES = json.loads((ROOT / "scripts" / "priorauth" / "swarm_cases.json").read_text())
OUT = ROOT / "docs" / "uiteam.jsonl"


def one(plan, spec, info, case, label, lock):
    display = Display(*spec.get("size", (1280, 800))).start()
    target = targets.Target(spec, display)
    try:
        since = time.time()
        with lock:  # opening many browsers at the same instant isn't what's being measured
            target.reset()
        runner = uiteam.PlanRunner(plan, display, max_seconds=900)
        result = runner.run(info["skill"] if info.get("skill") else "save_request", J.portal_inputs(case))
        ok, detail, wrong = J.portal_judge(result, case, since)
        rec = dict(run=label, app="portal", job="save_request", i=case["id"], ok=ok, wrong_saved=wrong, detail=detail, status=result["status"], reason=result["reason"][:200], seconds=result["seconds"], questions=result["questions"], steps=result["steps"], usd=0.0, at=time.time())
        with OUT.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        print(f"  {case['id']}: {'PASS' if ok else 'FAIL'} {result['seconds']} s | {detail[:120]}", flush=True)
        return rec
    finally:
        target.stop()
        display.stop()


def main():
    app, job, sizes = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3:]]
    plan = uiteam.check_plan(json.loads((config.HOME / "uiteam" / app / "plan.json").read_text()))
    spec = J.APPS[app]["spec"]()
    info = J.APPS[app]["jobs"][job]
    lock = threading.Lock()
    for n in sizes:
        t0 = time.time()
        with ThreadPoolExecutor(n) as ex:
            rows = list(ex.map(lambda c: one(plan, spec, info, c, f"swarm-{n}", lock), CASES[:n]))
        wall = time.time() - t0
        print(json.dumps(dict(at_once=n, passes=sum(r["ok"] for r in rows), wrong=sum(bool(r["wrong_saved"]) for r in rows), wall_s=round(wall, 1), jobs_per_hour=round(sum(r["ok"] for r in rows) / wall * 3600))), flush=True)


if __name__ == "__main__":
    main()
