"""Command line. `autoharness up` starts everything; `autoharness --help` lists the rest."""
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
    ap = argparse.ArgumentParser(prog="autoharness", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description="Teach an AI an app once. Then any agent can call its jobs as tools,\n"
                                             "run by a small open model on this computer, with every step checked.",
                                 epilog="Start here:  autoharness up")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")
    u = sub.add_parser("up", help="start it, with the made-up demo apps, and check what's ready")
    u.add_argument("--no-demo", action="store_true", help="don't start the made-up demo apps")
    u.add_argument("--tailscale", action="store_true", help="also open the app on this machine's Tailscale address, with a token")
    sub.add_parser("check", help="what's ready, what's missing, and the fix for each")
    t = sub.add_parser("teach", help='teach it a new interface: autoharness teach <address> "<the job, in plain words>"')
    t.add_argument("address", help="a web address, or a desktop app's command")
    t.add_argument("job", help="what it should do, in plain words. Put any login in it; it's kept on this computer")
    t.add_argument("--input", action="append", default=[], metavar="KEY=VALUE", help="a sample input to teach on")
    t.add_argument("--name", help="what to call the interface, like orders. Otherwise it's named after the app")
    o = sub.add_parser("tools", help="every job an agent can call, with its inputs")
    o.add_argument("interface", nargs="?", help="only this interface")
    c = sub.add_parser("call", help="run one job: autoharness call <tool> key=value ...")
    c.add_argument("tool", help="a name from autoharness tools, like backoffice__read_order")
    c.add_argument("inputs", nargs="*", metavar="KEY=VALUE")
    c.add_argument("--json", help="the inputs as one JSON object instead")
    sub.add_parser("connect", help="plug it into an agent: the settings for MCP clients, with this computer's paths")
    m = sub.add_parser("mcp", help="an MCP server on stdin and stdout, for agents that start a command")
    m.add_argument("--interface", help="offer only this interface's jobs")
    m.add_argument("--wait", type=float, default=50, help="seconds a call waits before answering with a job id (default 50)")
    sub.add_parser("down", help="stop what autoharness up started")
    s = sub.add_parser("serve", help="run the app in this terminal instead of in the background")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=4140)
    s.add_argument("--tailscale", action="store_true", help="also listen on this machine's Tailscale address, with a token")
    pr = sub.add_parser("program", help="the earlier Program mode, which writes a Python harness (see docs/BENCHMARK.md)")
    program(pr)
    args = ap.parse_args()

    if args.cmd == "serve":
        from .server import serve
        return serve(args.host, args.port, args.tailscale)
    if args.cmd == "program":
        return run_program(args)
    from . import cli
    try:
        code = {"up": lambda: cli.up(not args.no_demo, args.tailscale), "check": cli.check, "down": cli.down, "connect": cli.connect,
                "teach": lambda: cli.teach(args.address, args.job, args.input, args.name), "tools": lambda: cli.tools(args.interface),
                "call": lambda: cli.call(args.tool, args.inputs, args.json),
                "mcp": lambda: cli.mcp_stdio(args.interface, args.wait)}[args.cmd]()
    except cli.AppError as e:
        print(e, file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


def program(pr: argparse.ArgumentParser) -> None:
    sub = pr.add_subparsers(dest="pcmd", required=True)
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


def run_program(args) -> None:
    """Program mode: Spark explores, Wonder writes a Python harness, and Glimmer answers the questions it asks."""
    args.cmd = args.pcmd
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
