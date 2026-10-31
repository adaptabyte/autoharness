"""Runs a harness and keeps it going. Work escalates only as far as it must:

    1. code     the harness itself, in the sandbox. No model, no network.
    2. Glimmer  the local model, when the harness asks a question, or to clear an unexpected screen.
    3. Wonder   the teacher, once, to repair the harness. Skipped entirely in local-only mode.
    4. a person when nothing else worked, or before anything the harness marks as irreversible.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from . import sandbox
from .desktop import Display, die_with_parent
from .library import Package
from .local import Glimmer, LocalModelError

Emit = Callable[[dict], None]
_ocr_lock = threading.Lock()
_ocr_proc: subprocess.Popen | None = None
_ocr_dir: Path | None = None


def _ocr_worker() -> subprocess.Popen:
    """The locked-down OCR process (see ocr_worker.py). Refuses to use it if the lockdown failed."""
    global _ocr_proc, _ocr_dir
    if _ocr_proc is not None and _ocr_proc.poll() is None:
        return _ocr_proc
    import tempfile
    _ocr_dir = Path(tempfile.mkdtemp(prefix="autoharness-ocr-"))
    here = Path(__file__).resolve().parent
    env = {"PATH": "/usr/bin", "HOME": "/nonexistent", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
           "PYTHONPATH": os.pathsep.join(p for p in sys.path if p.endswith("site-packages"))}
    _ocr_proc = subprocess.Popen([sys.executable, str(here / "ocr_worker.py"), str(_ocr_dir)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, env=env, text=True, bufsize=1, start_new_session=True, preexec_fn=die_with_parent)
    hello = json.loads(_ocr_proc.stdout.readline() or "{}")
    if not hello.get("locked"):
        _ocr_proc.kill()
        _ocr_proc = None
        raise OSError("OCR was not started because this system could not lock it down")
    return _ocr_proc


def ocr(frame: np.ndarray) -> list[list]:
    """Local OCR. Returns [x1, y1, x2, y2, text, score] rows, with text in reading order."""
    with _ocr_lock:
        worker = _ocr_worker()
        # Small UI text reads far better at double size.
        scale = 2 if frame.shape[0] < 400 and frame.shape[1] < 1000 else 1
        img = np.asarray(Image.fromarray(frame).resize((frame.shape[1] * scale, frame.shape[0] * scale))) if scale > 1 else frame
        tmp = _ocr_dir / "frame.tmp"
        img.tofile(tmp)
        tmp.replace(_ocr_dir / "frame.bin")
        worker.stdin.write(json.dumps({"shape": list(img.shape[:2])}) + "\n")
        worker.stdin.flush()
        reply = json.loads(worker.stdout.readline() or "{}")
    if "rows" not in reply:
        raise OSError("the OCR process stopped")
    rows = [[int(r[0] / scale), int(r[1] / scale), int(r[2] / scale), int(r[3] / scale), r[4], r[5]] for r in reply["rows"]]
    rows.sort(key=lambda r: (r[1] // 12, r[0]))
    return rows


def ocr_can_open_sockets() -> bool:
    """For the test suite: asks the OCR process to try to open a socket."""
    with _ocr_lock:
        worker = _ocr_worker()
        worker.stdin.write('{"probe": true}\n')
        worker.stdin.flush()
        return json.loads(worker.stdout.readline())["socket"] == "ALLOWED"


@dataclass
class RunResult:
    status: str = "failed"          # done | failed | needs_help | stopped
    summary: str = ""
    result: dict = field(default_factory=dict)
    seconds: float = 0.0
    actions: int = 0
    glimmer_calls: int = 0
    glimmer_seconds: float = 0.0
    cloud_usd: float = 0.0
    cloud_calls: int = 0
    cloud_bytes: int = 0
    attempts: int = 0
    recoveries: int = 0
    repairs: int = 0
    reason: str = ""
    traceback: str = ""
    log: list = field(default_factory=list)
    local_only: bool = True
    sandboxed: bool = False

    def record(self, kind: str) -> dict:
        d = asdict(self)
        d.pop("log")
        d.pop("traceback")
        d.update(kind=kind, at=time.time())
        return d


class Runner:
    def __init__(self, pkg: Package, display: Display, emit: Emit | None = None, params: dict | None = None,
                 glimmer: Glimmer | None = None, approve: Callable[[str], bool] | None = None,
                 stop: threading.Event | None = None, max_seconds: float = 600, max_actions: int = 5000,
                 idle_limit: int = 60, code_dir: Path | None = None):
        self.pkg = pkg
        self.display = display
        self.emit = emit or (lambda e: None)
        self.params = params or {}
        self.glimmer = glimmer or Glimmer()
        self.approve = approve
        self.stop = stop or threading.Event()
        self.max_seconds = max_seconds
        self.max_actions = max_actions
        self.idle_limit = idle_limit
        self.code_dir = Path(code_dir) if code_dir else pkg.path
        self.state: dict = {}
        self._frame_sig = None
        self._idle = 0
        self._t_end = 0.0
        self._last_activity = 0.0
        self.stall_seconds = 45.0

    # -- one launch of the sandboxed child ----------------------------------------------------

    def _serve(self, m: dict, work: Path, r: RunResult):
        """Carry out one request from the harness. Runs in the parent, which owns the display."""
        d = self.display
        method = m["m"]
        if method not in ("screen", "ocr", "log", "wait_stable"):
            self._last_activity = time.time()  # looking is not progress, and a harness can look forever
        if method == "screen":
            f = d.shot()
            tmp = work / "frame.tmp"
            f.tofile(tmp)
            tmp.replace(work / "frame.bin")
            return [f.shape[1], f.shape[0]]
        if method == "log":
            r.log.append(m["message"])
            self.emit({"type": "log", "tier": "code", "text": m["message"]})
            return None
        if method == "wait":
            end = time.time() + min(float(m["seconds"]), 60)
            while time.time() < end and not self.stop.is_set():
                time.sleep(min(0.05, max(0, end - time.time())))
            return None
        if method == "wait_stable":
            region = m.get("region")
            return d.wait_stable(min(float(m.get("timeout", 3)), 60), region=tuple(region) if region else None)
        if method == "ocr":
            frame = d.shot()
            region = m.get("region")
            if region:
                x1, y1, x2, y2 = region
                rows = ocr(frame[y1:y2, x1:x2])
                return [[a + x1, b + y1, c + x1, e + y1, t, s] for a, b, c, e, t, s in rows]
            return ocr(frame)
        if method == "ask":
            return self._serve_ask(m, r)
        if method == "confirm":
            self.emit({"type": "confirm", "message": m["message"]})
            ok = self.approve(m["message"]) if self.approve else False
            self.emit({"type": "log", "tier": "person", "text": ("Approved: " if ok else "Declined: ") + m["message"]})
            return ok
        # Everything left is an action on the app.
        if method == "click":
            d.click(m["x"], m["y"], m.get("button", "left"))
        elif method == "double_click":
            d.click(m["x"], m["y"], "left", 2)
        elif method == "drag":
            d.drag([tuple(p) for p in m["path"]])
        elif method == "move":
            d.move(m["x"], m["y"])
        elif method == "scroll":
            d.scroll(m["x"], m["y"], m.get("dx", 0), m.get("dy", 0))
        elif method == "type":
            d.type(m["text"])
        elif method == "key":
            d.press(m["combo"])
        else:
            raise ValueError(f"unknown request: {method}")
        r.actions += 1
        self.emit({"type": "action", "tier": "code", "what": method, "x": m.get("x"), "y": m.get("y"), "n": r.actions})
        self._check_progress(r)
        return None

    def _serve_ask(self, m: dict, r: RunResult):
        region = m.get("region")
        image = None
        if m.get("image"):
            path = self.params.get("_files", {}).get(m["image"])
            if not path:
                raise ValueError(f"no such input file: {m['image']}")
            image = np.asarray(Image.open(path).convert("RGB"))
        else:
            image = self.display.shot()
            if region:
                x1, y1, x2, y2 = region
                image = image[y1:y2, x1:x2]
        self.emit({"type": "ask", "tier": "glimmer", "text": m["question"][:200]})
        t0 = time.time()
        answer = self.glimmer.ask(m["question"], image, m.get("choices"), m.get("schema"))
        took = time.time() - t0
        r.glimmer_calls += 1
        r.glimmer_seconds += took
        self.emit({"type": "answer", "tier": "glimmer", "text": json.dumps(answer)[:300], "seconds": round(took, 1),
                   "n": r.glimmer_calls})
        return answer

    def _check_progress(self, r: RunResult) -> None:
        """A harness clicking away at a screen that never changes is stuck, whatever it believes."""
        f = self.display.shot()
        sig = f[::8, ::8].tobytes()
        self._idle = self._idle + 1 if sig == self._frame_sig else 0
        self._frame_sig = sig
        if self._idle >= self.idle_limit:
            self._idle = 0
            raise ValueError(f"{self.idle_limit} actions in a row changed nothing on screen")
        if r.actions >= self.max_actions:
            raise ValueError(f"reached the limit of {self.max_actions} actions")

    def interface(self, mode: str, work: Path | None = None, verb: str | None = None, args: dict | None = None,
                  r: RunResult | None = None, seconds: float = 120) -> dict:
        """One observe() or verb call, or a description of the interface. Returns the child's final message."""
        import tempfile
        r = r if r is not None else RunResult()
        self._t_end = time.time() + seconds
        self.max_seconds = seconds
        work = work or Path(tempfile.mkdtemp(prefix="autoharness-if-"))
        end = self._launch(work, r, {"mode": mode, "verb": verb, "args": args or {}})
        self.state = end.get("state") or self.state
        return end

    def _launch(self, work: Path, r: RunResult, extra: dict | None = None) -> dict:
        """Run the child until it ends. Returns its final message, or a synthetic one if it died."""
        init = {"width": self.display.width, "height": self.display.height, "params": self.params, "state": self.state, **(extra or {})}
        proc = sandbox.spawn(self.code_dir, work)
        stderr: list[str] = []
        threading.Thread(target=lambda: stderr.extend(proc.stderr.readlines()[-30:]), daemon=True).start()
        killer_fired = threading.Event()
        stalled = threading.Event()
        self._last_activity = time.time()

        def watchdog():
            while proc.poll() is None:
                if time.time() - self._last_activity > self.stall_seconds and not self.stop.is_set():
                    # Find out where it is before ending it. That is the evidence a repair needs.
                    stalled.set()
                    try:
                        os.kill(proc.pid, signal.SIGUSR1)
                        time.sleep(0.5)
                    except OSError:
                        pass
                if stalled.is_set() or self.stop.is_set() or time.time() > self._t_end:
                    killer_fired.set()
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    return
                time.sleep(0.1)

        threading.Thread(target=watchdog, daemon=True).start()
        try:
            proc.stdin.write(json.dumps(init) + "\n")
            proc.stdin.flush()
            for line in proc.stdout:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if m["m"] == "ready":
                    r.sandboxed = bool(m.get("locked"))
                    if not r.sandboxed:
                        return {"m": "end", "status": "exception",
                                "reason": "this system cannot sandbox generated code, so it was not run"}
                    continue
                if m["m"] == "end":
                    return m
                try:
                    reply = {"value": self._serve(m, work, r)}
                except (ValueError, LocalModelError, OSError) as e:
                    reply = {"error": str(e)[:600]}
                proc.stdin.write(json.dumps(reply, default=str) + "\n")
                proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
            proc.wait()
        if self.stop.is_set():
            return {"m": "end", "status": "stopped", "reason": "stopped by the user"}
        if stalled.is_set():
            time.sleep(0.1)
            return {"m": "end", "status": "stalled", "reason": f"no action for {self.stall_seconds:.0f} s",
                    "traceback": "".join(stderr)[-2500:]}
        if killer_fired.is_set():
            return {"m": "end", "status": "stuck", "reason": f"ran out of time ({self.max_seconds:.0f} s)"}
        return {"m": "end", "status": "exception", "reason": "the harness crashed",
                "traceback": "".join(stderr)[-2000:]}

    # -- the escalation ladder ----------------------------------------------------------------

    def _recover_locally(self, reason: str, r: RunResult) -> bool:
        """Ask Glimmer whether something unexpected is in the way, and clear it if so. Free and private."""
        if not self.glimmer.available():
            return False
        frame = self.display.shot()
        labels = []
        for row in ocr(frame):
            if len(row[4]) <= 24 and row[5] > 0.6:
                labels.append(row)
        options = [f"click: {row[4]}" for row in labels[:30]]
        options += ["press Escape", "press Enter", "nothing to clear"]
        goal = self.pkg.manifest.get("goal", "")
        self.emit({"type": "ask", "tier": "glimmer", "text": "Something went wrong. Is a dialog or popup in the way?"})
        t0 = time.time()
        try:
            choice = self.glimmer.ask(
                f"An automation of this app is trying to: {goal}\nIt stopped with this problem: {reason}\n"
                "Look at the screen. If a dialog, popup or message is blocking the app, pick the one action that "
                "safely clears it and returns to normal use. Never pick something that deletes, submits or "
                "confirms anything. If nothing is in the way, pick 'nothing to clear'.", frame, options)
        except LocalModelError as e:
            self.emit({"type": "log", "tier": "glimmer", "text": f"Glimmer could not help: {e}"})
            return False
        r.glimmer_calls += 1
        r.glimmer_seconds += time.time() - t0
        self.emit({"type": "answer", "tier": "glimmer", "text": choice, "seconds": round(time.time() - t0, 1),
                   "n": r.glimmer_calls})
        if choice == "nothing to clear":
            return False
        if choice == "press Escape":
            self.display.press("Escape")
        elif choice == "press Enter":
            self.display.press("Return")
        else:
            row = labels[options.index(choice)]
            self.display.click((row[0] + row[2]) // 2, (row[1] + row[3]) // 2)
        self.display.wait_stable(2)
        return True

    def execute(self, repair: Callable | None = None, local_only: bool = False, work: Path | None = None) -> RunResult:
        """Run until the goal is reached or the ladder is exhausted."""
        r = RunResult(local_only=local_only)
        t0 = time.time()
        self._t_end = t0 + self.max_seconds
        import tempfile
        work = work or Path(tempfile.mkdtemp(prefix="autoharness-run-"))
        recoveries_left, repairs_left, restarts_left = 2, 1, 2
        repair_tried = False
        try:
            while True:
                if self.stop.is_set():
                    r.status, r.reason = "stopped", "stopped by the user"
                    break
                r.attempts += 1
                end = self._launch(work, r)
                self.state = end.get("state") or self.state
                status = end.get("status")
                if status == "done":
                    r.status, r.summary, r.result = "done", end.get("summary", ""), end.get("result") or {}
                    break
                if status == "stopped":
                    r.status, r.reason = "stopped", end.get("reason", "")
                    break
                r.reason, r.traceback = end.get("reason", status or "unknown"), end.get("traceback", "")
                if time.time() >= self._t_end:
                    r.status = "failed"
                    break
                self.emit({"type": "problem", "text": r.reason})
                if status == "stalled" and restarts_left:
                    # Harnesses can restart from any screen, so a stall costs seconds rather than the whole run.
                    restarts_left -= 1
                    self.emit({"type": "log", "tier": "code", "text": "It stalled, so it was restarted from the current screen."})
                    continue
                if recoveries_left and self._recover_locally(r.reason, r):
                    recoveries_left -= 1
                    r.recoveries += 1
                    self.emit({"type": "log", "tier": "glimmer", "text": "Cleared it. Picking the job back up."})
                    continue
                if repair and not local_only and repairs_left:
                    repairs_left -= 1
                    repair_tried = True
                    self.emit({"type": "escalate", "tier": "cloud", "text": "Calling the teacher back to repair the harness."})
                    outcome = repair(self.display.shot(), r.reason, r.traceback, r.log[-30:])
                    r.cloud_usd += outcome.get("usd", 0)
                    r.cloud_calls += outcome.get("calls", 0)
                    r.cloud_bytes += outcome.get("bytes", 0)
                    if outcome.get("fixed"):
                        r.repairs += 1
                        self.emit({"type": "repaired", "tier": "cloud", "text": outcome.get("summary", "Repaired."),
                                   "usd": outcome.get("usd", 0)})
                        continue
                r.status = "needs_help"
                self.emit({"type": "needs_help", "text": r.reason})
                break
        except Exception as e:  # noqa: BLE001 - a run must always end with a result the UI can show
            r.status, r.reason, r.traceback = "failed", f"{type(e).__name__}: {e}", traceback.format_exc()[-2000:]
        if repair_tried and r.status != "done" and self.pkg.restore_proven():
            # A repair only counts once it has finished the job. Otherwise the next run gets the proven code back.
            self.emit({"type": "log", "tier": "code", "text": "The repair didn't work, so the last proven version was restored."})
        r.seconds = round(time.time() - t0, 2)
        return r
