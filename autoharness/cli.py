"""The commands people use: up, check, teach, tools, call, connect, mcp, down.

Each one talks to the running app over HTTP on this computer. So a job started from the terminal or by an agent can be
watched live in the browser, and the terminal, the web page and every agent see the same jobs."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__, config

APP = os.environ.get("AUTOHARNESS_URL", "http://127.0.0.1:4140").rstrip("/")
STATE = config.HOME / "up.json"
LOGS = config.HOME / "logs"


def demo_apps() -> dict[str, dict]:
    """The made-up apps this repo ships, from scripts/demo_apps.json. The engine itself knows no app."""
    try:
        return json.loads((config.REPO / "scripts/demo_apps.json").read_text())["apps"]
    except (OSError, ValueError, KeyError):
        return {}


def colour(code: str, text: str, stream=sys.stdout) -> str:
    return f"\033[{code}m{text}\033[0m" if stream.isatty() and not os.environ.get("NO_COLOR") else text


def good(text: str = "✓") -> str:
    return colour("32", text)


def bad(text: str = "✗") -> str:
    return colour("31", text)


def dim(text: str) -> str:
    return colour("90", text)


# ---------------------------------------------------------------- talking to the app

class AppError(RuntimeError):
    pass


def http(method: str, path: str, body=None, timeout: float = 15, caller: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if caller:
        headers["X-Caller"] = caller
    req = urllib.request.Request(APP + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        try:
            raise AppError(json.loads(e.read()).get("error") or str(e)) from None
        except ValueError:
            raise AppError(str(e)) from None
    except (urllib.error.URLError, OSError) as e:
        raise AppError(f"Autoharness isn't answering at {APP} ({getattr(e, 'reason', e)}). Start it with: autoharness up") from None
    return json.loads(raw) if raw else None


def rpc(method: str, params: dict | None = None, interface: str | None = None, timeout: float = 15):
    reply = http("POST", "/mcp/ui" + (f"/{interface}" if interface else ""), {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, timeout)
    if "error" in reply:
        raise AppError(reply["error"]["message"])
    return reply["result"]


def answering(url: str, timeout: float = 2.0) -> bool:
    """Anything that answers HTTP counts, even with an error page or a redirect to a login."""
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def app_running() -> bool:
    try:
        return bool(http("GET", "/api/health", timeout=2).get("ok"))
    except AppError:
        return False


def _local(url: str) -> bool:
    return urllib.parse.urlsplit(url).hostname in ("127.0.0.1", "localhost")


# ---------------------------------------------------------------- starting and stopping

def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _alive(entry: dict) -> bool:
    """Still running, and still the process that was started: a reused process number never gets stopped by mistake."""
    try:
        cmdline = Path(f"/proc/{entry['pid']}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return False
    return entry["mark"] in cmdline


def launch(name: str, argv: list[str], mark: str) -> subprocess.Popen:
    """Starts something in the background, in its own process group, with its output in ~/.autoharness/logs/<name>.log."""
    LOGS.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(LOGS / f"{name}.log", "ab") as log:
        proc = subprocess.Popen(argv, cwd=config.REPO, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    state = _state()
    state[name] = {"pid": proc.pid, "mark": mark}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))
    return proc


def _wait_until(test, seconds: float, proc: subprocess.Popen | None = None) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(0.4)
    return test()


def _log_tail(name: str, lines: int = 4) -> str:
    try:
        return "\n".join("      " + line for line in (LOGS / f"{name}.log").read_text(errors="replace").strip().splitlines()[-lines:])
    except OSError:
        return ""


def ensure_app(quiet: bool = False, out=sys.stdout, tailscale: bool = False) -> None:
    """The app, started in the background if it isn't running. Only ever on this computer."""
    if app_running():
        return
    if not _local(APP):
        raise AppError(f"Autoharness isn't answering at {APP}")
    port = urllib.parse.urlsplit(APP).port or 4140
    if not quiet:
        print(dim(f"Starting Autoharness at {APP} ..."), file=out, flush=True)
    proc = launch("app", [sys.executable, "-m", "autoharness", "serve", "--port", str(port)] + (["--tailscale"] if tailscale else []), "autoharness serve")
    if not _wait_until(app_running, 30, proc):
        raise AppError(f"Autoharness didn't start. Its log, {LOGS / 'app.log'}, ends:\n{_log_tail('app')}")


def _python_with(module: str) -> str | None:
    for python in (sys.executable, str(config.HOME / "backoffice-venv/bin/python")):
        if Path(python).exists() and subprocess.run([python, "-c", f"import {module}"], capture_output=True).returncode == 0:
            return python
    return None


def up(demo: bool = True, tailscale: bool = False) -> int:
    print(f"Autoharness {__version__}\n", flush=True)
    started: dict[str, str] = {}
    if not app_running():
        try:
            ensure_app(quiet=True, tailscale=tailscale)
            started["App"] = "started"
        except AppError as e:
            print(f"  {bad()} App  {e}")
            return 1
    logins, example = config.HOME / "logins.json", config.REPO / "plans/logins.example.json"
    if demo and not logins.exists() and example.exists():
        logins.parent.mkdir(parents=True, exist_ok=True)
        logins.touch(mode=0o600)
        logins.write_text(example.read_text())
        print(f"  {good()} {'Demo logins':<16}copied to {logins}, readable by you only. They're all made up\n")
    for name, app in demo_apps().items() if demo else ():
        if answering(app["url"]):
            continue
        python = _python_with(app["needs"]) if app.get("needs") else sys.executable
        if not python:
            started[name] = f"needs {app['needs']} to start: pip install -e '.[demo]'"
            continue
        proc = launch(name, [python, *app["start"]], app["start"][0])
        started[name] = "started, made-up data" if _wait_until(lambda u=app["url"]: answering(u), 40, proc) else f"didn't start: see {LOGS / (name + '.log')}"
    glimmer_url = config.GLIMMER_URL.rstrip("/")
    if not answering(glimmer_url + "/models") and _local(glimmer_url):
        if (config.REPO / ".venv/bin/python").exists() and (config.REPO / "models/Muse-Glimmer-30B-NVFP4").exists():
            proc = launch("glimmer", ["bash", "serve/serve_glimmer.sh"], "serve_glimmer.sh")
            time.sleep(4)
            started["Muse Glimmer"] = "loading on this computer's GPUs, which takes a few minutes" if proc.poll() is None else f"couldn't start:\n{_log_tail('glimmer')}"
    return check(header=False, notes=started)


def down() -> int:
    state = _state()
    for name, entry in state.items():
        if _alive(entry):
            os.killpg(entry["pid"], signal.SIGTERM)
            print(f"  stopped {name}")
    STATE.unlink(missing_ok=True)
    if not state:
        print("Nothing that autoharness up started is running.")
    return 0


# ---------------------------------------------------------------- checking

def check(header: bool = True, notes: dict | None = None) -> int:
    from . import desktop, targets, uiteam
    from .cloud import Ledger

    notes = notes or {}
    if header:
        print(f"Autoharness {__version__}\n")
    needed_ok = True

    def row(ok: bool | None, name: str, text: str, fix: str = "", needed: bool = True, width: int = 16) -> None:
        nonlocal needed_ok
        if ok is False and needed:
            needed_ok = False
        mark = good() if ok else dim("–") if ok is None or not needed else bad()
        note = f"   {notes[name]}" if name in notes else ""
        print(f"  {mark} {name:<{width}}{text}{dim(note)}")
        if fix and not ok:
            print(f"    {'':<{width}}{dim('fix: ' + fix)}")

    row(app_running(), "App", APP, "autoharness up")
    glimmer_url = config.GLIMMER_URL.rstrip("/")
    try:
        with urllib.request.urlopen(glimmer_url + "/models", timeout=3) as r:
            served = [m.get("id") for m in json.load(r).get("data", [])]
        if config.GLIMMER_MODEL in served:
            row(True, "Muse Glimmer", f"{glimmer_url}, runs every job on this computer")
        else:
            row(False, "Muse Glimmer", f"{glimmer_url} answers, but serves {', '.join(map(str, served)) or 'nothing'}", f"serve it as {config.GLIMMER_MODEL}, or set GLIMMER_MODEL")
    except (urllib.error.URLError, OSError, ValueError):
        state = _state().get("glimmer")
        loading = state is not None and _alive(state)
        row(False, "Muse Glimmer", f"{glimmer_url} {'is still loading' if loading else 'is not answering'}",
            f"wait, and see {LOGS / 'glimmer.log'}" if loading else "bash serve/serve_glimmer.sh (about 25 GB of GPU memory), or set GLIMMER_URL")
    xvfb = desktop.find_tool("Xvfb")
    row(bool(xvfb), "Virtual screen", "Xvfb, so jobs never touch your own screen" if xvfb else "Xvfb is missing", "bash scripts/setup_desktop.sh")
    try:
        targets.chromium_path()
        row(True, "Browser", "Chromium, for web interfaces")
    except Exception:  # noqa: BLE001 - any failure here means no usable browser
        row(False, "Browser", "no Chromium found, needed for web interfaces", "bash scripts/setup_desktop.sh")
    spent = Ledger.read()["spent_usd"]
    row(True if config.api_key() else None, "Meta API key", ("set" if config.api_key() else "not set") + dim(f". Only teaching needs it: ${spent:.2f} of the ${config.BUDGET_USD:.2f} cap spent"),
        "put MODEL_API_KEY=... in .env to teach new interfaces", needed=False)

    plans = uiteam.saved_plans()
    tools = sum(len(uiteam.plan_tools(p, uiteam.kept_logins(k))) for k, p in plans.items())
    width = max([len(k) for k in plans] + [14]) + 3
    print(f"\n  {colour('1', f'{len(plans)} interfaces, offering {tools} tools')}")
    for plan_id, plan in plans.items():
        spec = plan.get("target") or {}
        where = spec.get("url") or " ".join(spec.get("command") or [])
        demo = next((n for n, a in demo_apps().items() if urllib.parse.urlsplit(a["url"]).netloc == urllib.parse.urlsplit(spec.get("url") or "").netloc), None)
        if demo in notes:
            notes[plan_id] = notes[demo]
        if spec.get("url"):
            fix = "autoharness up starts it" if demo else "start that app (the test apps are in scripts/)"
            live = answering(spec["url"])
            row(live, plan_id, where if live else f"{where} isn't answering", fix, needed=False, width=width)
        else:
            found = bool(spec.get("command")) and bool(desktop.find_tool(spec["command"][0]))
            row(found, plan_id, where if found else f"{where} isn't installed", f"install {where}", needed=False, width=width)
    print()
    if needed_ok:
        print(f"Ready. Open {APP}, or plug it into an agent: {colour('1', 'autoharness connect')}")
        return 0
    print("Not ready yet: fix the lines marked " + bad() + ".")
    return 1


# ---------------------------------------------------------------- teaching and calling

def follow(job_id: str, on_event) -> None:
    """The job's live events, as the browser gets them."""
    req = urllib.request.Request(f"{APP}/api/jobs/{job_id}/events", headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        for raw in r:
            line = raw.decode(errors="replace").strip()
            if line.startswith("data: "):
                event = json.loads(line[6:])
                on_event(event)
                if event.get("type") == "end":
                    return


STEP_WORDS = {"ensure": "check", "read_list": "read", "for_each": "each", "call": "skill", "stop_for_person": "stop"}


def print_step(e: dict) -> None:
    if e.get("type") == "step" and e.get("do") != "wait":
        mark = good() if e.get("ok") else colour("33", "!")
        verb = STEP_WORDS.get(e.get("do"), e.get("do") or "")
        what = str(e.get("what") or e.get("detail") or "")
        what = what if len(what) <= 96 else what[:95] + "…"
        print(f"  {mark} {dim(f'{verb:<8}')} {what}", flush=True)
        if not e.get("ok") and e.get("detail"):
            print(f"    {dim(str(e['detail'])[:160])}", flush=True)
    elif e.get("type") == "stage":
        print(colour("1", e.get("text", "")), flush=True)
    elif e.get("type") == "error":
        print(bad("  " + str(e.get("text"))), flush=True)


def parse_inputs(pairs: list[str], raw_json: str | None) -> dict:
    """key=value pairs. A value that reads as JSON (30, true, a list) keeps its type; anything else is text."""
    inputs = json.loads(raw_json) if raw_json else {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise AppError(f"{pair!r} isn't key=value")
        try:
            inputs[key] = json.loads(value)
        except ValueError:
            inputs[key] = value
    return inputs


def call(tool: str, pairs: list[str], raw_json: str | None) -> int:
    ensure_app()
    inputs = parse_inputs(pairs, raw_json)
    start = http("POST", "/api/ui/call", {"tool": tool, "inputs": inputs, "wait": 0}, caller="The terminal")
    print(dim(f"{tool} {json.dumps(inputs)}\nRunning on this computer. Watch it live: {APP}/#/job/{start['job']}\n"), flush=True)
    follow(start["job"], print_step)
    out = http("GET", f"/api/ui/call/{start['job']}?wait=10")
    print()
    if out["status"] == "running":
        print(colour("33", f"Still running: {APP}/#/job/{out['job']}"))
        return 3
    if out["ok"]:
        extra = f", then stopped for a person: {out['stopped_for_person']}" if out.get("stopped_for_person") else ""
        print(good(f"✓ Verified in {out['seconds']:.0f} s") + dim(f", {out['steps_checked']} checks, $0 in the cloud{extra}"))
        print(json.dumps(out["outputs"], indent=2, ensure_ascii=False))
        return 0
    print(colour("33", f"! Stopped, with nothing guessed: {out['reason']}"))
    return 2


def tools(interface: str | None) -> int:
    ensure_app()
    listed = rpc("tools/list", interface=interface)["tools"]
    for t in listed:
        if t["name"] == "wait_for_job":
            continue
        args = ", ".join(t["inputSchema"].get("properties") or {})
        print(f"{colour('1', t['name'])}({args})")
        for line in textwrap.wrap(t["description"].split(" Runs on the user")[0], 96):
            print(f"  {dim(line)}")
    print(dim(f"\n{len(listed) - 1} tools. Run one: autoharness call <tool> key=value ...   Give them to an agent: autoharness connect"))
    return 0


def teach(address: str, job: str, pairs: list[str], name: str | None = None) -> int:
    ensure_app()
    from .cloud import Ledger
    spent = Ledger.read()["spent_usd"]
    print(dim(f"Teaching spends Meta API budget once, usually $0.10 to $4. ${spent:.2f} of the ${config.BUDGET_USD:.2f} cap is spent so far."))
    brief = http("POST", "/api/ui/teach", {"target": address, "goal": job, "inputs": parse_inputs(pairs, None), "name": name})
    print(dim(f"Watch it live: {APP}/#/job/{brief['id']}\n"), flush=True)
    seen: dict = {}

    def on_event(e: dict) -> None:
        kind = e.get("type")
        if kind == "explore":
            print(f"  {dim('Spark')} {str(e.get('said') or '').strip()[:110]}", flush=True)
        elif kind == "plan":
            seen["plan"] = plan = e["plan"]
            for t in plan["tools"]:
                shown = [k for k in t["inputs"] if k in ((plan.get("samples") or {}).get(t["name"]) or {})]
                kept = " The login is kept on this computer, out of the tool." if len(shown) < len(t["inputs"]) else ""
                print(f"  {good()} Wonder wrote the plan: {t['name']}({', '.join(shown)}).{kept}", flush=True)
        elif kind == "proof":
            mark = good() if e.get("achieved") else colour("33", "!")
            print(f"  {mark} Glimmer's run {e.get('attempt')}: {'passed' if e.get('achieved') else 'failed: ' + str(e.get('why'))[:120]} ({e.get('seconds', 0):.0f} s)", flush=True)
        elif kind == "learned":
            seen["learned"] = e
        elif kind == "not_learned":
            seen["failed"] = e
        elif kind in ("stage", "error"):
            print_step(e)

    follow(brief["id"], on_event)
    print()
    if "learned" in seen:
        e, plan = seen["learned"], seen.get("plan") or {}
        print(good(f"Learned, for ${e.get('usd', 0):.2f}, once.") + " It's now a tool any agent can call:\n")
        for t in plan.get("tools", []):
            sample = (plan.get("samples") or {}).get(t["name"]) or {}
            args = " ".join(f"{k}={json.dumps(sample[k]) if not isinstance(sample.get(k), str) or ' ' in sample[k] else sample[k]}" for k in t["inputs"] if k in sample)
            print(f"  autoharness call {e['id']}__{t['name']} {args}")
        return 0
    why = (seen.get("failed") or {}).get("why", "it stopped")
    print(colour("33", f"Not learned: {why} Nothing was saved."))
    return 2


def connect() -> int:
    from .server import autoharness_command
    command = autoharness_command()
    stdio = f'{{\n  "mcpServers": {{\n    "autoharness": {{"command": {json.dumps(command)}, "args": ["mcp"]}}\n  }}\n}}'
    print(f"""{colour('1', 'Any MCP client that takes an address')} (streamable HTTP)
  {APP}/mcp/ui

{colour('1', 'Any MCP client that starts a command')} (stdio; Claude Desktop, Cursor and others use this format)
{chr(10).join('  ' + line for line in stdio.splitlines())}

{colour('1', 'Claude Code')}
  claude mcp add autoharness -- {command} mcp

{colour('1', 'Muse Spark, from this repo')}
  python scripts/ask.py "What's the total on order ORD-10530?"

{dim('Add /<interface> to the address, or --interface <id> to the command, to offer one interface only.')}
{dim('A job still running after 50 s answers with a job id, and the agent collects it with wait_for_job,')}
{dim('so clients that give up on a call after 60 s still work. The agent never sees your screen or a kept login.')}""")
    return 0


# ---------------------------------------------------------------- MCP over stdio

def mcp_stdio(interface: str | None, wait: float) -> int:
    """For MCP clients that start a command: JSON-RPC on stdin and stdout, passed to the app's own MCP endpoint. Only
    protocol messages go to stdout; everything else goes to stderr."""
    try:
        ensure_app(quiet=False, out=sys.stderr)
    except AppError as e:
        print(e, file=sys.stderr)
    path = "/mcp/ui" + (f"/{interface}" if interface else "") + f"?wait={wait:g}"
    out, lock = sys.stdout, threading.Lock()
    caller = {"name": "An agent"}
    workers: list[threading.Thread] = []

    def send(message: dict) -> None:
        with lock:
            out.write(json.dumps(message) + "\n")
            out.flush()

    def handle(message: dict) -> None:
        if message.get("method") == "initialize":
            info = (message.get("params") or {}).get("clientInfo") or {}
            caller["name"] = str(info.get("title") or info.get("name") or "An agent")[:40]
        try:
            reply = http("POST", path, message, timeout=wait + 60, caller=caller["name"])
        except AppError as e:
            reply = {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": str(e)}}
        if reply is not None and message.get("id") is not None:
            send(reply)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not JSON"}})
            continue
        for one in message if isinstance(message, list) else [message]:
            worker = threading.Thread(target=handle, args=(one,), daemon=True)
            worker.start()
            workers.append(worker)
    end = time.time() + 2  # the client has gone; answers already on their way get a moment, long calls keep running in the app
    for worker in workers:
        worker.join(max(0.0, end - time.time()))
    return 0
