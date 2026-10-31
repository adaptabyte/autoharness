"""The proof. Teach every target in the catalog from nothing, then run each harness more times than it was
verified on, and write one table of results. Nothing is hand-tuned between targets.

    python scripts/gauntlet.py [--only id,id] [--runs 10] [--baseline]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autoharness import config, library, targets  # noqa: E402
from autoharness.cloud import Ledger  # noqa: E402
from autoharness.desktop import Display  # noqa: E402
from autoharness.runtime import Runner  # noqa: E402
from autoharness.teacher import Teacher, app_notes, baseline, goal_with_inputs, judge_final_screen  # noqa: E402
from autoharness.cloud import Cloud  # noqa: E402


def quiet(prefix):
    def emit(e):
        if e.get("type") in ("phase", "trial_end", "verify_end", "taught", "code"):
            print(prefix, {k: (v if not isinstance(v, str) else v[:160]) for k, v in e.items() if k not in ("code", "interface", "seq")}, flush=True)
    return emit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--limit", type=float, default=4.0)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--reuse", action="store_true", help="use an existing ready package for a target instead of teaching")
    args = ap.parse_args()
    specs = targets.catalog()
    if args.only:
        wanted = args.only.split(",")
        specs = [s for s in specs if s["id"] in wanted]
    rows = []
    out = config.HOME / "gauntlet.json"
    for spec in specs:
        name = spec["id"]
        print(f"=== {name}", flush=True)
        d = Display(*spec.get("size", (1280, 800))).start()
        t = targets.Target(spec, d)
        row = {"target": name, "name": spec.get("name"), "goal": spec.get("suggested_goal")}
        try:
            pkg = None
            if args.reuse:
                for p in library.all_packages():
                    if p.manifest.get("target", {}).get("id") == name and p.manifest.get("status") == "ready":
                        pkg = p
                        break
            if pkg is None:
                pkg = library.create(spec.get("name", name), spec["suggested_goal"], spec)
                Teacher(pkg, d, t, quiet(name), limit_usd=args.limit, sample_params=spec.get("sample_params")).teach()
            m = pkg.manifest
            row.update(package=pkg.id, status=m.get("status"), failure=m.get("failure"), teach_usd=m.get("teach_usd"),
                       teach_seconds=m.get("teach_seconds"), verified=m.get("verified"), lines=pkg.code.count("\n"),
                       verbs=len((m.get("interface") or {}).get("verbs", [])))
            if m.get("status") == "ready":
                results = []
                judge = Cloud()
                for i in range(args.runs):
                    t.reset()
                    r = Runner(pkg, d, None, spec.get("sample_params")).execute(local_only=True)
                    verdict = judge_final_screen(judge, goal_with_inputs(m["goal"], spec.get("sample_params")), d.shot(), r.summary, app_notes(pkg)) if r.status == "done" else {"achieved": False, "why": r.reason}
                    ok = r.status == "done" and verdict["achieved"]
                    rec = r.record("run")
                    rec.update(status="done" if ok else "failed", judge=verdict)
                    pkg.add_run(rec)
                    results.append((ok, r.seconds, r.actions, r.glimmer_calls))
                    print(name, f"run {i + 1}: {'ok' if ok else 'FAILED'} {r.seconds}s actions={r.actions} glimmer={r.glimmer_calls} {verdict['why'][:120]}", flush=True)
                times = sorted(x[1] for x in results if x[0])
                row.update(runs=len(results), passed=sum(x[0] for x in results), median_seconds=times[len(times) // 2] if times else None,
                           glimmer_calls=sum(x[3] for x in results), actions=sum(x[2] for x in results), judge_usd=round(judge.meter.usd, 4))
                if args.baseline:
                    b = baseline(d, t, goal_with_inputs(m["goal"], spec.get("sample_params")), limit_usd=2.0, notes=app_notes(pkg))
                    pkg.update(baseline=b)
                    row["baseline"] = b
                    print(name, "baseline", {k: b[k] for k in ("achieved", "seconds", "usd", "turns")}, flush=True)
        except Exception as e:  # noqa: BLE001 - one failure must not lose the others
            row.update(status="error", failure=f"{type(e).__name__}: {e}")
            print(name, "ERROR", e, flush=True)
        finally:
            t.stop()
            d.stop()
        rows.append(row)
        out.write_text(json.dumps({"at": time.time(), "spent_total": Ledger.read()["spent_usd"], "rows": rows}, indent=1))
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
