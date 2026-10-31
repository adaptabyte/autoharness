"""The web app. Standard library only, and no outside assets, so it keeps working with the internet unplugged."""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import shutil
import socket
import tempfile
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

from . import __version__, config, library, targets
from .cloud import Ledger
from .desktop import Display
from .local import Glimmer
from .runtime import Runner
from .session import Session, operate
from .teacher import Repairer, Teacher, app_notes, baseline, goal_with_inputs

STATIC = Path(__file__).resolve().parent / "static"
JOBS: dict[str, "Job"] = {}
_jobs_lock = threading.Lock()
_status = {"internet": None, "glimmer": False}
TOKEN: str | None = None
UPLOADS = Path(tempfile.gettempdir()) / f"autoharness-uploads-{os.getuid()}"


class Job:
    def __init__(self, kind: str, title: str, package_id: str | None = None):
        self.id = secrets.token_hex(4)
        self.kind, self.title, self.package_id = kind, title, package_id
        self.events: list[dict] = []
        self.cond = threading.Condition()
        self.stop = threading.Event()
        self.displays: dict[str, Display] = {}
        self.status = "running"
        self.created = time.time()
        self.pending_confirm: dict | None = None
        self.session: Session | None = None

    def emit(self, event: dict, lane: str | None = None) -> None:
        event = dict(event, t=round(time.time() - self.created, 2))
        if lane:
            event["lane"] = lane
        with self.cond:
            event["seq"] = len(self.events)
            self.events.append(event)
            self.cond.notify_all()

    def lane(self, lane: str):
        return lambda e: self.emit(e, lane)

    def finish(self, status: str) -> None:
        self.status = status
        self.emit({"type": "end", "status": status})

    def approve(self, message: str) -> bool:
        """Blocks the harness until a person answers in the UI. No answer within 10 minutes means no."""
        ticket = {"message": message, "answer": None, "event": threading.Event()}
        self.pending_confirm = ticket
        ticket["event"].wait(600)
        self.pending_confirm = None
        return bool(ticket["answer"])

    def brief(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title, "package": self.package_id, "status": self.status,
                "created": self.created, "lanes": list(self.displays), "confirm": self.pending_confirm["message"] if self.pending_confirm else None}


def _start(kind: str, title: str, package_id, body) -> Job:
    with _jobs_lock:
        active = [j for j in JOBS.values() if j.status == "running"]
        if len(active) >= 3:
            raise ValueError("three jobs are already running; stop one first")
        job = Job(kind, title, package_id)
        JOBS[job.id] = job

    def wrapper():
        try:
            body(job)
            if job.status == "running":
                job.finish("stopped" if job.stop.is_set() else "done")
        except Exception as e:  # noqa: BLE001 - a failed job must say so in the UI
            job.emit({"type": "error", "text": f"{type(e).__name__}: {e}", "detail": traceback.format_exc()[-1500:]})
            job.finish("failed")
        finally:
            for d in job.displays.values():
                d.stop()

    threading.Thread(target=wrapper, daemon=True, name=f"job-{job.id}").start()
    return job


def _resolve_target(text: str) -> dict:
    try:
        return targets.get_spec(text)
    except KeyError:
        return targets.spec_from_text(text)


def start_teach(target_text: str, goal: str, limit: float, params: dict | None) -> Job:
    spec = _resolve_target(target_text)
    goal = goal.strip() or spec.get("suggested_goal", "")
    if not goal:
        raise ValueError("say what it should do")
    pkg = library.create(spec.get("name", target_text), goal, spec)

    def body(job: Job):
        display = Display(*spec.get("size", (1280, 800))).start()
        job.displays["main"] = display
        tgt = targets.Target(spec, display)
        try:
            manifest = Teacher(pkg, display, tgt, job.emit, job.stop, limit_usd=limit,
                               sample_params=params or spec.get("sample_params"), approve=job.approve).teach()
            job.finish("done" if manifest.get("status") == "ready" else "failed")
        finally:
            tgt.stop()

    return _start("teach", f"Teaching {spec.get('name', target_text)}", pkg.id, body)


def changed_spec(spec: dict) -> dict:
    """The same app with its appearance and window changed: what happens when software updates under a harness."""
    changed = dict(spec, size=[1100, 720], env={**spec.get("env", {}), "GTK_THEME": "Adwaita:dark"})
    return changed


def start_run(package_id: str, local_only: bool, params: dict | None, repeat: int = 1, change_app: bool = False) -> Job:
    pkg = library.get(package_id)
    spec = pkg.manifest["target"]
    if change_app:
        spec = changed_spec(spec)

    def body(job: Job):
        display = Display(*spec.get("size", (1280, 800))).start()
        job.displays["main"] = display
        tgt = targets.Target(spec, display)
        try:
            for n in range(repeat):
                if job.stop.is_set():
                    break
                job.emit({"type": "run_start", "n": n + 1, "of": repeat})
                tgt.reset()
                runner = Runner(pkg, display, job.emit, params or spec.get("sample_params"), approve=job.approve, stop=job.stop)
                result = runner.execute(repair=Repairer(pkg, display, tgt, job.emit, job.stop), local_only=local_only)
                pkg.add_run(result.record("run"))
                job.emit({"type": "run_end", "n": n + 1, **{k: v for k, v in result.record("run").items()}})
            job.finish("stopped" if job.stop.is_set() else "done")
        finally:
            tgt.stop()

    return _start("run", f"Running {pkg.manifest.get('name')}", package_id, body)


def start_race(package_id: str) -> Job:
    """Side by side: Spark doing the job itself, and the harness doing it over and over until Spark finishes."""
    pkg = library.get(package_id)
    spec = pkg.manifest["target"]

    def body(job: Job):
        left = Display(*spec.get("size", (1280, 800))).start()
        right = Display(*spec.get("size", (1280, 800))).start()
        job.displays.update(spark=left, harness=right)
        t_spark, t_harness = targets.Target(spec, left), targets.Target(spec, right)
        spark_done = threading.Event()
        outcome: dict = {}

        def spark():
            try:
                outcome.update(baseline(left, t_spark, goal_with_inputs(pkg.manifest["goal"], spec.get("sample_params")), job.lane("spark"), job.stop, limit_usd=1.5, notes=app_notes(pkg)))
                pkg.update(baseline=outcome)
                job.emit({"type": "race_end", **outcome}, "spark")
            except Exception as e:  # noqa: BLE001
                job.emit({"type": "error", "text": str(e)}, "spark")
            finally:
                spark_done.set()

        def harness():
            n = wins = 0
            t_start = time.time()
            while not spark_done.is_set() and not job.stop.is_set():
                n += 1
                t_harness.reset()
                r = Runner(pkg, right, job.lane("harness"), spec.get("sample_params"), stop=job.stop).execute(local_only=True)
                wins += r.status == "done"
                pkg.add_run(r.record("run"))
                job.emit({"type": "race_lap", "lap": n, "wins": wins, "seconds": r.seconds, "status": r.status,
                          "elapsed": round(time.time() - t_start, 1), "glimmer": r.glimmer_calls}, "harness")
                if n >= 200:
                    break

        threads = [threading.Thread(target=spark, daemon=True), threading.Thread(target=harness, daemon=True)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        t_spark.stop()
        t_harness.stop()

    return _start("race", f"Race on {pkg.manifest.get('name')}", package_id, body)


def start_session(package_id: str) -> Job:
    """Keep an app open and offer it through its model-designed interface, until someone stops it."""
    pkg = library.get(package_id)
    spec = pkg.manifest["target"]
    if not pkg.manifest.get("interface"):
        raise ValueError("this harness has no model interface; teach it again")
    opened = threading.Event()

    def body(job: Job):
        display = Display(*spec.get("size", (1280, 800))).start()
        job.displays["main"] = display
        tgt = targets.Target(spec, display)
        try:
            tgt.reset()
            job.session = Session(pkg, display, tgt, job.emit, job.stop, job.approve)
            job.emit({"type": "session_ready", "tools": job.session.tools()})
            opened.set()
            job.stop.wait()
        finally:
            opened.set()
            tgt.stop()

    job = _start("session", f"Talking to {pkg.manifest.get('name')}", package_id, body)
    opened.wait(60)
    return job


def session_for(package_id: str) -> Job:
    """The running session for this app, starting one if needed. This is how outside agents get in."""
    for job in JOBS.values():
        if job.kind == "session" and job.package_id == package_id and job.status == "running" and job.session:
            return job
    return start_session(package_id)


def mcp_reply(package_id: str, message: dict) -> dict | None:
    """Model Context Protocol, over plain JSON-RPC. Lets any MCP client use the app through its verbs."""
    method, mid = message.get("method"), message.get("id")
    if mid is None:
        return None  # a notification
    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        return ok({"protocolVersion": message.get("params", {}).get("protocolVersion", "2025-06-18"),
                   "capabilities": {"tools": {}}, "serverInfo": {"name": f"autoharness-{package_id}", "version": __version__},
                   "instructions": library.get(package_id).manifest.get("how", "")})
    if method == "ping":
        return ok({})
    job = session_for(package_id)
    if method == "tools/list":
        return ok({"tools": [{"name": t["name"], "description": t.get("description", ""), "inputSchema": t["parameters"]} for t in job.session.tools()]})
    if method == "tools/call":
        params = message.get("params", {})
        job.emit({"type": "op_call", "verb": params.get("name"), "args": params.get("arguments") or {}, "source": "an outside agent"})
        try:
            value = job.session.call(params.get("name"), params.get("arguments") or {})
            text = json.dumps(value, default=str)
            job.emit({"type": "op_result", "verb": params.get("name"), "result": text[:600], "ok": True})
            return ok({"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:  # noqa: BLE001 - a failed tool call is a result the calling model can act on
            job.emit({"type": "op_result", "verb": params.get("name"), "result": str(e)[:600], "ok": False})
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}


def _background_status() -> None:
    glimmer = Glimmer()
    while True:
        try:
            with socket.create_connection((urllib.parse.urlparse(config.API_BASE).hostname, 443), timeout=1.5):
                _status["internet"] = True
        except OSError:
            _status["internet"] = False
        _status["glimmer"] = glimmer.available(1.5)
        time.sleep(2)


def state() -> dict:
    with _jobs_lock:
        jobs = [j.brief() for j in sorted(JOBS.values(), key=lambda j: -j.created)][:20]
    ledger = Ledger.read()
    catalog = [{k: s.get(k) for k in ("id", "name", "blurb", "suggested_goal", "kind")} for s in targets.catalog()]
    return {"version": __version__, "library": [p.summary() for p in library.all_packages()], "catalog": catalog, "jobs": jobs,
            "spent_usd": ledger["spent_usd"], "budget_usd": config.BUDGET_USD, "internet": _status["internet"],
            "glimmer": _status["glimmer"], "has_key": bool(config.api_key())}


def package_detail(package_id: str) -> dict:
    pkg = library.get(package_id)
    understanding = pkg.path / "teach" / "understanding.md"
    versions = sorted(int(f.stem[1:]) for f in (pkg.path / "versions").glob("v*.py")) if (pkg.path / "versions").exists() else []
    return {**pkg.summary(), "code": pkg.code, "how": pkg.manifest.get("how", ""), "failure": pkg.manifest.get("failure"),
            "understanding": understanding.read_text() if understanding.exists() else "", "notes": pkg.manifest.get("notes", []),
            "runs_list": pkg.runs()[-40:], "versions": versions, "interface": pkg.manifest.get("interface"), "assets": [f.name for f in pkg.assets.glob("*.png")],
            "verified": pkg.manifest.get("verified")}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, value, status: int = 200) -> None:
        data = json.dumps(value, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw or b"{}")

    def _authorized(self, query: dict) -> bool:
        if TOKEN is None:
            return True
        cookie = self.headers.get("Cookie", "")
        return (query.get("token", [""])[0] == TOKEN or f"autoharness={TOKEN}" in cookie
                or self.headers.get("Authorization") == f"Bearer {TOKEN}")

    def do_GET(self):  # noqa: N802
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        path = url.path
        if not self._authorized(query):
            return self._json({"error": "add ?token=... to the address"}, 401)
        try:
            if path == "/":
                data = (STATIC / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                if TOKEN:
                    self.send_header("Set-Cookie", f"autoharness={TOKEN}; HttpOnly; SameSite=Strict; Path=/")
                self.end_headers()
                self.wfile.write(data)
                return None
            if path == "/api/state":
                return self._json(state())
            m = re.fullmatch(r"/api/package/([a-z0-9-]+)", path)
            if m:
                return self._json(package_detail(m.group(1)))
            m = re.fullmatch(r"/api/package/([a-z0-9-]+)/export", path)
            if m:
                out = library.get(m.group(1)).export()
                data = out.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{out.name}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/events", path)
            if m:
                return self._sse(m.group(1), int(query.get("since", ["0"])[0]))
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/live/(\w+)", path)
            if m:
                return self._mjpeg(m.group(1), m.group(2))
            return self._json({"error": "not found"}, 404)
        except KeyError as e:
            return self._json({"error": f"not found: {e}"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            return None

    def do_POST(self):  # noqa: N802
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        if not self._authorized(query):
            return self._json({"error": "unauthorized"}, 401)
        # A page on another site must not be able to start jobs on this machine.
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).netloc != self.headers.get("Host"):
            return self._json({"error": "cross-site request refused"}, 403)
        path = url.path
        try:
            if path == "/api/import":
                n = int(self.headers.get("Content-Length") or 0)
                tmp = Path(tempfile.mkstemp(suffix=".harness")[1])
                tmp.write_bytes(self.rfile.read(n))
                pkg = library.import_file(tmp)
                tmp.unlink()
                return self._json({"id": pkg.id})
            if path == "/api/upload":
                n = int(self.headers.get("Content-Length") or 0)
                if n > 40_000_000:
                    return self._json({"error": "file too large"}, 413)
                UPLOADS.mkdir(mode=0o700, exist_ok=True)
                name = re.sub(r"[^\w.-]", "_", query.get("name", ["upload"])[0])[-80:]
                dest = UPLOADS / f"{secrets.token_hex(6)}-{name}"
                dest.write_bytes(self.rfile.read(n))
                return self._json({"path": str(dest), "name": name})
            body = self._body()
            if path == "/api/teach":
                job = start_teach(str(body.get("target", "")), str(body.get("goal", "")), float(body.get("limit", 4)), body.get("params"))
                return self._json(job.brief())
            if path == "/api/run":
                job = start_run(str(body["id"]), bool(body.get("local_only")), body.get("params"), int(body.get("repeat", 1)), bool(body.get("change_app")))
                return self._json(job.brief())
            if path == "/api/race":
                return self._json(start_race(str(body["id"])).brief())
            if path == "/api/session":
                return self._json(start_session(str(body["id"])).brief())
            m = re.fullmatch(r"/mcp/([a-z0-9-]+)", path)
            if m:
                reply = mcp_reply(m.group(1), body)
                if reply is None:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                return self._json(reply)
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/ask", path)
            if m:
                job = JOBS[m.group(1)]
                if not job.session:
                    return self._json({"error": "the app is still opening"}, 409)
                request = str(body.get("request", "")).strip()
                if not request:
                    return self._json({"error": "say what you need"}, 400)

                def work():
                    try:
                        operate(job.session, request, job.emit)
                    except Exception as e:  # noqa: BLE001
                        job.emit({"type": "error", "text": str(e)})

                threading.Thread(target=work, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/delete":
                pkg = library.get(str(body["id"]))
                if any(j.package_id == pkg.id and j.status == "running" for j in JOBS.values()):
                    return self._json({"error": "it is running"}, 409)
                shutil.rmtree(pkg.path)
                return self._json({"ok": True})
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/stop", path)
            if m:
                job = JOBS[m.group(1)]
                job.stop.set()
                if job.pending_confirm:
                    job.pending_confirm["event"].set()
                return self._json({"ok": True})
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/confirm", path)
            if m:
                ticket = JOBS[m.group(1)].pending_confirm
                if not ticket:
                    return self._json({"error": "nothing is waiting"}, 409)
                ticket["answer"] = bool(body.get("ok"))
                ticket["event"].set()
                return self._json({"ok": True})
            m = re.fullmatch(r"/api/jobs/([0-9a-f]+)/input/(\w+)", path)
            if m:
                d = JOBS[m.group(1)].displays[m.group(2)]
                if body.get("kind") == "click":
                    d.click(int(body["x"]), int(body["y"]))
                elif body.get("kind") == "type":
                    d.type(str(body["text"]))
                elif body.get("kind") == "key":
                    d.press(str(body["combo"]))
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)
        except KeyError as e:
            return self._json({"error": f"not found: {e}"}, 404)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def _sse(self, job_id: str, since: int) -> None:
        job = JOBS[job_id]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        seq = since
        while True:
            with job.cond:
                if seq >= len(job.events):
                    job.cond.wait(10)
                batch = job.events[seq:]
            if batch:
                for e in batch:
                    self.wfile.write(f"id: {e['seq']}\ndata: {json.dumps(e, default=str)}\n\n".encode())
                seq += len(batch)
            else:
                self.wfile.write(b": alive\n\n")
            self.wfile.flush()
            if job.status != "running" and seq >= len(job.events):
                return

    def _mjpeg(self, job_id: str, lane: str) -> None:
        job = JOBS[job_id]
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        for _ in range(100):
            if lane in job.displays or job.status != "running":
                break
            time.sleep(0.1)
        display = job.displays.get(lane)
        if not display:
            return
        last, sent_at = None, 0.0
        while job.status == "running":
            try:
                f = display.shot()
            except Exception:  # noqa: BLE001 - the screen went away with the job
                return
            sig = f[::6, ::6].tobytes()
            # Browsers show a motion-JPEG frame only once the next one starts, so a still screen must keep sending.
            if sig != last or time.time() - sent_at > 0.8:
                last, sent_at = sig, time.time()
                self._send_frame(f)
            time.sleep(0.06)

    def _send_frame(self, f: np.ndarray) -> None:
        # A small window on a big black screen is hard to see: show the part in use, as the app really is.
        lit = np.argwhere(f[::4, ::4].max(axis=2) > 0)
        if len(lit):
            (y1, x1), (y2, x2) = lit.min(0) * 4, (lit.max(0) + 1) * 4
            if (x2 - x1) * (y2 - y1) < 0.8 * f.shape[0] * f.shape[1]:
                f = f[max(0, y1 - 12):y2 + 12, max(0, x1 - 12):x2 + 12]
        buf = io.BytesIO()
        Image.fromarray(f).save(buf, "JPEG", quality=82)
        data = buf.getvalue()
        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
        self.wfile.flush()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(host: str = "127.0.0.1", port: int = 4140) -> None:
    global TOKEN
    config.ensure_dirs()
    url = f"http://{host}:{port}"
    if host not in ("127.0.0.1", "localhost"):
        # This app controls a desktop and can spend money, so it is never open to a network by accident.
        TOKEN = os.environ.get("AUTOHARNESS_TOKEN") or secrets.token_urlsafe(16)
        url += f"/?token={TOKEN}"
    threading.Thread(target=_background_status, daemon=True).start()
    print(f"Autoharness {__version__} is running at {url}", flush=True)
    Server((host, port), Handler).serve_forever()
