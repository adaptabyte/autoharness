"""Command line. `python -m autoharness serve` starts the app; the rest is for scripting and for the gauntlet."""
from __future__ import annotations

import argparse
import json
import sys
import threading

from . import config, library, targets
from .desktop import Display


def printer(event: dict) -> None:
    t = event.get("type")
    if t == "cost":
        print(f"  [spent ${event['usd']:.4f}, {event['calls']} calls]", flush=True)
    elif t in ("action", "frame"):
        pass
    elif t == "code":
        print(f"* harness v{event['version']}: {event['lines']} lines", flush=True)
    else:
        print({k: (v if not isinstance(v, str) else v[:600]) for k, v in event.items()}, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(prog="autoharness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=4140)
    t = sub.add_parser("teach", help="teach an app")
    t.add_argument("target", help="a catalog id, URL or command")
    t.add_argument("goal", nargs="?", help="what it should do")
    t.add_argument("--limit", type=float, default=4.0)
    t.add_argument("--verify", type=int, default=5)
    t.add_argument("--effort", default="high")
    r = sub.add_parser("run", help="run a taught app")
    r.add_argument("id")
    r.add_argument("--local-only", action="store_true")
    r.add_argument("--repeat", type=int, default=1)
    b = sub.add_parser("baseline", help="measure Spark doing the job itself, every step")
    b.add_argument("id")
    b.add_argument("--limit", type=float, default=2.0)
    v = sub.add_parser("verify", help="run proof runs again on a program, without teaching")
    v.add_argument("id")
    v.add_argument("--runs", type=int, default=5)
    i = sub.add_parser("improve", help="send a program back to the teacher, without exploring again")
    i.add_argument("id")
    i.add_argument("instruction")
    i.add_argument("--limit", type=float, default=3.0)
    i.add_argument("--verify", type=int, default=5)
    sub.add_parser("list", help="list taught apps")
    args = ap.parse_args()

    if args.cmd == "serve":
        from .server import serve
        return serve(args.host, args.port)
    if args.cmd == "list":
        print(json.dumps([p.summary() for p in library.all_packages()], indent=1))
        return None

    from .teacher import Repairer, Teacher, app_notes, baseline, goal_with_inputs, verify_only
    from .runtime import Runner
    if args.cmd == "teach":
        try:
            spec = targets.get_spec(args.target)
        except KeyError:
            spec = targets.spec_from_text(args.target)
        goal = args.goal or spec.get("suggested_goal")
        if not goal:
            sys.exit("say what it should do")
        pkg = library.create(spec.get("name", args.target), goal, spec)
        d = Display(*spec.get("size", (1280, 800))).start()
        tgt = targets.Target(spec, d)
        try:
            m = Teacher(pkg, d, tgt, printer, limit_usd=args.limit, verify_runs=args.verify, effort=args.effort,
                        sample_params=spec.get("sample_params")).teach()
        finally:
            tgt.stop()
            d.stop()
        print(json.dumps({k: m.get(k) for k in ("status", "failure", "verified", "teach_usd", "teach_seconds", "how")}, indent=1))
        print("package:", pkg.id)
        return None
    pkg = library.get(args.id)
    spec = pkg.manifest["target"]
    d = Display(*spec.get("size", (1280, 800))).start()
    tgt = targets.Target(spec, d)
    try:
        if args.cmd == "run":
            for _ in range(args.repeat):
                tgt.reset()
                runner = Runner(pkg, d, printer, spec.get("sample_params"))
                res = runner.execute(repair=Repairer(pkg, d, tgt, printer), local_only=args.local_only)
                pkg.add_run(res.record("run"))
                print(json.dumps(res.record("run"), indent=0))
        elif args.cmd == "improve":
            m = Teacher(pkg, d, tgt, printer, limit_usd=args.limit, verify_runs=args.verify, sample_params=spec.get("sample_params")).improve(args.instruction)
            print(json.dumps({k: m.get(k) for k in ("status", "failure", "verified", "interface_verified", "teach_usd")}, indent=1))
        elif args.cmd == "verify":
            print(json.dumps(verify_only(pkg, d, tgt, printer, args.runs, spec.get("sample_params")), indent=1))
        elif args.cmd == "baseline":
            res = baseline(d, tgt, goal_with_inputs(pkg.manifest["goal"], spec.get("sample_params")), printer, limit_usd=args.limit, notes=app_notes(pkg))
            pkg.update(baseline=res)
            print(json.dumps(res, indent=1))
    finally:
        tgt.stop()
        d.stop()
    return None


if __name__ == "__main__":
    main()
