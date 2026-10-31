"""The teacher: Muse Spark learns an app by using it, then writes the program that replaces it.

    Explore   Spark drives the live app through computer use and works out how it behaves.
    Compile   Spark writes harness.py and tests it on recorded frames and on the live app.
    Verify    The harness runs alone on fresh instances, with no cloud. A separate Spark call that
              never saw the code judges each final screen. Failures go back to the teacher.

The teacher can only finish after trials pass, and only verified results reach the user.
"""
from __future__ import annotations

import base64
import inspect
import io
import json
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from . import config, sdk
from .cloud import BudgetExceeded, Cloud, CloudError, Meter, image_url, response_text
from .desktop import Display
from .library import Package
from .local import Glimmer, extract_json
from .runtime import Runner, RunResult
from .targets import Target

Emit = Callable[[dict], None]


def sdk_reference() -> str:
    """The harness API exactly as written in sdk.py, so the prompt cannot drift from the code."""
    lines = []
    for name, fn in inspect.getmembers(sdk.App, inspect.isfunction):
        if name.startswith("_"):
            continue
        doc = (inspect.getdoc(fn) or "").replace("\n", " ")
        sig = str(inspect.signature(fn)).replace("self, ", "").replace("(self)", "()")
        lines.append(f"app.{name}{sig}\n    {doc}" if doc else f"app.{name}{sig}")
    return "\n".join(lines)


EXPLORE_RULES = """You are teaching yourself to use a piece of software you have never seen, so that you can then \
write a program that does the job without you. A program that runs on this computer and never calls a large \
model again is the whole point: every step that still needs you afterwards is a failure of teaching.

Phase 1: EXPLORE. Use the computer tool. Learn how this app really behaves:
- what each screen is, what the controls do, and how the app shows state, progress, success and failure
- which things are the same every time, and which change from run to run
- try to reach the goal at least once. Deliberately look at what failure looks like too.
Use segment(phrase) if you need exact pixel positions of things you can see, such as "grid cell" or "button".
All coordinates, in every tool, are screenshot pixels with (0, 0) at the top left. There is no 0-1000 grid. If a click \
seems to miss, look at the pixels again rather than inventing a conversion.
Be economical: you have about {max_turns} turns. Do not narrate at length.
Call finish_explore when you understand the app well enough to write the program."""

COMPILE_RULES = """Phase 2: COMPILE. This app's interface was designed for human eyes and hands. You are now designing the \
interface it should have had for a model, and writing the program that provides it. Write harness.py using only this \
API, numpy (np), cv2 and the Python standard library:

{sdk}

harness.py must define all three of these:

from sdk import verb

def observe(app) -> dict:
    \"\"\"The app's state as compact JSON: the fewest tokens from which a model could decide what to do next.\"\"\"

@verb
def some_operation(app, thing: str, count: int = 1):
    \"\"\"One line saying what this does. A verb is a whole meaningful operation, like add_patient or reveal_cell, not a click.\"\"\"

def run(app):
    \"\"\"Reach the goal end to end, built on the verbs.\"\"\"

Design it as the interface you would want if you could never see a screen again. Choose names, arguments and state \
shapes so that a small model can use them correctly from their descriptions alone. Offer the app's whole useful surface, \
from the small steps (open this, set that, act on this item) to the big ones, so a model can do things other than the \
one goal. Verbs should return a short result \
and raise via app.fail when they cannot do what they say. Each verb starts as a separate process, so it must find what \
it needs from the screen or from app.state each time.

What makes a good harness:
- Coordinates everywhere are screenshot pixels with (0, 0) at the top left, the same numbers you see in frames and \
segment boxes. There is no 0-1000 grid and no conversion of any kind.
- Fast. A person should be impressed by how quickly it finishes. Numpy and templates take milliseconds, app.read_text \
about half a second, so never OCR in a per-item loop: read the whole region once or save templates. Do not wait \
longer than needed: app.wait_stable returns as soon as the screen settles.
- Deterministic first. Read state from pixels with templates (save_template, then app.find), color and geometry \
with numpy/cv2, and app.read_text (local OCR, runs on this machine). Work out the logic in code: real rules, real \
solvers, real search.
- Use app.ask (Muse Glimmer, the small local model, a few seconds per call) only where code truly cannot decide: \
messy or unfamiliar content, or judgment. Never for things code can read, and never in a tight loop.
- It must never rely on anything that varied during exploration. Find things on screen, do not assume where they \
are if they can move. Never hard-code a game's contents.
- It must work from any starting state: it can be restarted midway and should look at the screen and carry on. \
Keep anything worth remembering in app.state, a JSON-safe dict that survives restarts.
- After every action, app.wait_stable(), then look again. Never trust that an action worked. Check.
- Call app.done(summary) in run only after confirming on screen that the goal was reached. If you cannot go on, call \
app.fail(reason): that is what triggers recovery, so do not swallow errors or loop forever.
- Before anything irreversible in the real world (submit, send, delete, pay), call app.confirm(message).
- Things the user provides each run (a name, a file) are inputs: declare them in write_harness and read app.params.
- Log what it is doing in plain words with app.log, sparingly. A person reads this.
- There is no network, no display access and no filesystem outside its own folder. Don't try.

Your tools: view_frame, experiment (run code against a recorded frame to develop perception before risking the \
live app), segment, save_template, write_harness, trial (runs run(app) on a fresh copy of the app and tells you \
what happened), try_interface (calls observe or one verb on the live app), and look and act for checking the live app \
by hand. Develop perception on recorded frames first, then trial. When a trial fails, find out why from the evidence \
and fix the cause. Don't guess, and do not weaken the goal.
Call finish only when your latest code has passed two trials in a row."""

EXPLORE_TOOLS = [
    {"type": "function", "name": "note", "description": "Record a fact you learned about the app. These notes are kept for later repairs.",
     "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}},
    {"type": "function", "name": "segment", "description": "Find every instance of a noun phrase in a frame using SAM 3.1. Returns exact pixel boxes. frame defaults to the latest.",
     "parameters": {"type": "object", "properties": {"phrase": {"type": "string"}, "frame": {"type": "integer"}}, "required": ["phrase"]}},
    {"type": "function", "name": "finish_explore", "description": "End exploration. You will lose this conversation and keep only what you write here, so be complete: screens, controls with exact positions, how state, success and failure appear, what varies from run to run, and what surprised you. key_frames lists the recorded frames worth looking at again.",
     "parameters": {"type": "object", "properties": {"understanding": {"type": "string"}, "key_frames": {"type": "array", "items": {"type": "object", "properties": {"frame": {"type": "integer"}, "shows": {"type": "string"}}, "required": ["frame", "shows"]}}}, "required": ["understanding", "key_frames"]}},
]
COMPILE_TOOLS = [
    EXPLORE_TOOLS[0], EXPLORE_TOOLS[1],
    {"type": "function", "name": "view_frame", "description": "See a recorded frame, optionally a zoomed crop, to inspect exact pixels.",
     "parameters": {"type": "object", "properties": {"frame": {"type": "integer"}, "x1": {"type": "integer"}, "y1": {"type": "integer"}, "x2": {"type": "integer"}, "y2": {"type": "integer"}, "zoom": {"type": "integer"}}, "required": ["frame"]}},
    {"type": "function", "name": "experiment", "description": "Run Python in the sandbox against a recorded frame. Available: frame (RGB numpy array), np, cv2, app (app.find, app.find_all and app.read_text see this frame; actions are refused), and show(img) to see an image. print() output comes back to you.",
     "parameters": {"type": "object", "properties": {"code": {"type": "string"}, "frame": {"type": "integer"}}, "required": ["code", "frame"]}},
    {"type": "function", "name": "save_template", "description": "Save a crop of a recorded frame as a picture app.find can look for. Crop tightly around what stays constant.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "frame": {"type": "integer"}, "x1": {"type": "integer"}, "y1": {"type": "integer"}, "x2": {"type": "integer"}, "y2": {"type": "integer"}}, "required": ["name", "frame", "x1", "y1", "x2", "y2"]}},
    {"type": "function", "name": "write_harness", "description": "Save the whole of harness.py. inputs lists what the user supplies each run.",
     "parameters": {"type": "object", "properties": {"code": {"type": "string"}, "inputs": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "label": {"type": "string"}, "type": {"type": "string", "enum": ["text", "file"]}}, "required": ["name", "label", "type"]}}}, "required": ["code"]}},
    {"type": "function", "name": "trial", "description": "Run the harness on a fresh copy of the app, with no recovery help. Returns what happened and the final screen.",
     "parameters": {"type": "object", "properties": {"seconds": {"type": "integer", "description": "time limit, default 90, up to 300. Keep it short while debugging."}, "params": {"type": "object"}}}},
    {"type": "function", "name": "look", "description": "See the live app as it is right now. The screenshot is recorded as a new frame.",
     "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "act", "description": "Do one thing to the live app by hand and see the result, to check how something behaves. kind is click, right_click, double_click, drag, key, type or restart (a fresh copy of the app).",
     "parameters": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["click", "right_click", "double_click", "drag", "key", "type", "restart"]}, "x": {"type": "integer"}, "y": {"type": "integer"}, "x2": {"type": "integer"}, "y2": {"type": "integer"}, "text": {"type": "string", "description": "the text for type, or a key such as Return or ctrl+a for key"}}, "required": ["kind"]}},
    {"type": "function", "name": "try_interface", "description": "Call observe (name='observe') or one verb on the live app, as it is on screen now. Returns its result and the screen after.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "object"}}, "required": ["name"]}},
    {"type": "function", "name": "finish", "description": "Teaching is complete. Only accepted once the latest code has passed two trials in a row.",
     "parameters": {"type": "object", "properties": {"summary": {"type": "string", "description": "One or two plain sentences on how the harness works."}}, "required": ["summary"]}},
]
REPAIR_TOOLS = [t for t in COMPILE_TOOLS if t["name"] not in ("trial", "try_interface", "act")]


def judge_final_screen(cloud: Cloud, goal: str, frame: np.ndarray, summary: str = "", app_notes: str = "") -> dict:
    """An independent check. This call has never seen the harness or the teaching session.

    app_notes is what the teacher wrote about how the app shows state, before any code existed. Without it a judge
    misreads apps it has never seen: a solved game with no victory banner, say, looks unfinished.
    """
    notes = f"How this app shows its state, from someone who explored it:\n{app_notes[:5000]}\n\n" if app_notes else ""
    out = cloud.respond(
        model=config.TEACHER_MODEL, reasoning={"effort": "high"}, input=[{"role": "user", "content": [
            {"type": "input_text", "text": f"A program claims it achieved this goal in an app:\n\n{goal}\n\nIts claim: {summary or 'none'}\n\n{notes}"
             "Judge from this final screenshot alone. Look closely at the actual state on screen and do not take the claim on trust. "
             'If the screen does not show the goal was reached, say no. Reply with only JSON: {"achieved": true or false, "why": "one short sentence"}'},
            {"type": "input_image", "image_url": image_url(frame)}]}])
    try:
        verdict = extract_json(response_text(out))
        return {"achieved": bool(verdict.get("achieved")), "why": str(verdict.get("why", ""))[:300]}
    except ValueError:
        return {"achieved": False, "why": "the judge gave an unreadable answer"}


def app_notes(pkg: Package) -> str:
    p = pkg.path / "teach" / "understanding.md"
    return p.read_text() if p.exists() else ""


def verify_only(pkg: Package, display: Display, target: Target, emit: Emit | None = None, runs: int = 5, sample_params: dict | None = None,
                stop: threading.Event | None = None) -> dict:
    """Re-run proof runs on an existing program, with no teaching. Does not change the program."""
    teacher = Teacher(pkg, display, target, emit, stop, limit_usd=1.0, verify_runs=runs, sample_params=sample_params)
    teacher.frame_n = len(list(teacher.frames_dir.glob("*.png")))
    passed, _rows = teacher._verify()
    needed = max(1, int(np.ceil(runs * 0.8)))
    status = "ready" if passed >= needed else "failed"
    fields = {"status": status, "verified": f"{passed}/{runs}"}
    if status == "ready":
        fields["failure"] = None
    else:
        fields["failure"] = f"passed only {passed} of {runs} verification runs"
    pkg.update(**fields)
    return {"passed": passed, "runs": runs, "status": status, "usd": round(teacher.meter.usd, 4)}


class Teacher:
    def __init__(self, pkg: Package, display: Display, target: Target, emit: Emit | None = None,
                 stop: threading.Event | None = None, limit_usd: float = 4.0, max_explore_turns: int = 40,
                 max_compile_turns: int = 90, verify_runs: int = 5, sample_params: dict | None = None,
                 glimmer: Glimmer | None = None, effort: str = "high", approve=None):
        self.pkg, self.display, self.target = pkg, display, target
        self.emit = emit or (lambda e: None)
        self.stop = stop or threading.Event()
        self.meter = Meter()
        self.cloud = Cloud(self.meter, limit_usd=limit_usd)
        self.max_explore_turns, self.max_compile_turns = max_explore_turns, max_compile_turns
        self.verify_runs = verify_runs
        self.sample_params = sample_params or {}
        self.glimmer = glimmer or Glimmer()
        self.effort = effort
        self.approve = approve
        self.frames_dir = pkg.path / "teach" / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.frame_n = 0
        self.notes: list[str] = []
        self.prev_id: str | None = None
        self.passes_in_a_row = 0
        self.code_written = False
        self.finished_summary: str | None = None
        self.understanding: str | None = None
        self._t0 = time.time()

    # -- plumbing -----------------------------------------------------------------------------

    def _cost(self) -> None:
        self.emit({"type": "cost", **self.meter.snapshot()})

    def _record(self, frame: np.ndarray) -> int:
        self.frame_n += 1
        Image.fromarray(frame).save(self.frames_dir / f"{self.frame_n:05d}.png")
        return self.frame_n

    def _frame(self, n: int | None) -> np.ndarray:
        n = n or self.frame_n
        return np.asarray(Image.open(self.frames_dir / f"{n:05d}.png").convert("RGB"))

    def _turn(self, items: list, tools: list, instructions: str) -> dict:
        def send(chain_id, payload):
            body = dict(model=config.TEACHER_MODEL, tools=tools, input=payload, instructions=instructions,
                        reasoning={"effort": "medium" if any(t.get("type") == "computer" for t in tools) else self.effort},
                        truncation="disabled", store=True)
            if chain_id:
                body["previous_response_id"] = chain_id
            return self.cloud.respond(**body)

        recoverable = ("referenced response not found", "invalid parameters", "No tool output found")
        try:
            out = send(self.prev_id, items)
        except CloudError as e:
            if not any(x in str(e) for x in recoverable) or not self.prev_id:
                raise
            self._dump_request(items, e)
            # Meta's API can lose a stored response or refuse a long conversation. Retry, then rebuild from what is on disk.
            time.sleep(5)
            try:
                out = send(self.prev_id, items)
            except CloudError as e2:
                if not any(x in str(e2) for x in recoverable):
                    raise
                self.emit({"type": "log", "tier": "cloud", "text": "Meta's API lost the conversation, so it was rebuilt from saved work."})
                out = send(None, self._rebuilt_items(items))
        self.prev_id = out["id"]
        self._cost()
        return out

    def _dump_request(self, items: list, error: Exception) -> None:
        """Keep the shape of a refused request, without images, so the cause can be found afterwards."""
        def strip(v):
            if isinstance(v, dict):
                return {k: ("<image>" if k == "image_url" else strip(x)) for k, x in v.items()}
            if isinstance(v, list):
                return [strip(x) for x in v]
            return v
        with (self.pkg.path / "teach" / "refused.jsonl").open("a") as f:
            f.write(json.dumps({"error": str(error), "items": strip(items)}, default=str)[:20000] + "\n")

    def _rebuilt_items(self, items: list) -> list:
        """A fresh start for a lost conversation: the saved understanding and code, plus the unanswered tool results."""
        m = self.pkg.manifest
        results = [str(i.get("output"))[:4000] for i in items if i.get("type") == "function_call_output"]
        content = [{"type": "input_text", "text":
                    f"Your conversation history was lost, but all your work is saved.\nApp: {self.target.name}\nGoal: {m.get('goal')}\n"
                    f"What you learned:\n{self.understanding}\nNotes: {json.dumps(self.notes)}\n"
                    f"Saved templates: {[f.name for f in self.pkg.assets.glob('*.png')]}\nLatest frame number: {self.frame_n}\n"
                    f"Current harness.py (version {m.get('version', 0)}):\n```python\n{self.pkg.code}\n```\n"
                    f"The results of your last tool calls: {json.dumps(results)}\nCarry on from here."}]
        for i in items:
            if i.get("role") == "user":
                content.extend(c for c in i.get("content", []))
        # A first request may carry an image, even in a computer-use conversation.
        content.append({"type": "input_text", "text": "The screen right now:"})
        content.append({"type": "input_image", "image_url": image_url(self.display.shot())})
        return [{"role": "user", "content": content}]

    def _do_actions(self, actions: list[dict]) -> None:
        d = self.display
        for a in actions:
            kind = a.get("type")
            if kind == "click":
                d.click(a["x"], a["y"], a.get("button", "left"))
            elif kind == "double_click":
                d.click(a["x"], a["y"], "left", 2)
            elif kind == "drag":
                d.drag([(p["x"], p["y"]) for p in a["path"]])
            elif kind == "move":
                d.move(a["x"], a["y"])
            elif kind == "scroll":
                notch = lambda v: 0 if not v else int(np.sign(v) * (abs(v) if abs(v) <= 20 else max(1, abs(v) // 100)))
                d.scroll(a["x"], a["y"], notch(a.get("scroll_x")), notch(a.get("scroll_y")))
            elif kind == "keypress":
                keys = a.get("keys", [])
                d.press("+".join(keys))
            elif kind == "type":
                d.type(a.get("text", ""))
            elif kind == "wait":
                time.sleep(1.0)
            if kind not in ("screenshot", "wait"):
                self.emit({"type": "action", "tier": "cloud", "what": kind, "x": a.get("x"), "y": a.get("y")})
                time.sleep(0.04)

    def _computer_output(self, item: dict) -> dict:
        checks = item.get("pending_safety_checks") or []
        ack = []
        for c in checks:
            self.emit({"type": "safety", "text": c.get("message", "")})
            # Teaching happens on a throwaway virtual screen, so checks are logged and accepted there.
            # Anything attached to a real environment has to pass a person first.
            if self.target.spec.get("kind") == "attach" and not (self.approve and self.approve(c.get("message", ""))):
                raise CloudError(f"safety check declined: {c.get('message', '')}")
            ack.append({"id": c.get("id"), "code": c.get("code"), "message": c.get("message")})
        self._do_actions(item.get("actions", []))
        self.display.wait_stable(1.5)
        if not self.target.alive():
            # An app that died draws nothing, and a black screen would mislead the model. Say so and restart it.
            self.emit({"type": "log", "tier": "cloud", "text": "The app closed or crashed, so it was restarted."})
            self.target.reset()
            self.app_restarted = True
        frame = self.display.shot()
        n = self._record(frame)
        self.emit({"type": "frame", "n": n})
        return {"type": "computer_call_output", "call_id": item["call_id"], "acknowledged_safety_checks": ack,
                "output": {"type": "computer_screenshot", "image_url": image_url(frame)}}

    def _image_item(self, frame: np.ndarray, caption: str) -> dict:
        return {"role": "user", "content": [{"type": "input_text", "text": caption},
                                            {"type": "input_image", "image_url": image_url(frame)}]}

    # -- tools --------------------------------------------------------------------------------

    def _tool(self, name: str, args: dict) -> tuple[str, list]:
        """Returns (text result, extra input items such as images)."""
        if name == "note":
            self.notes.append(args["fact"])
            self.emit({"type": "note", "text": args["fact"]})
            return "noted", []
        if name == "segment":
            frame = self._frame(args.get("frame"))
            boxes = self.cloud.segment(frame, args["phrase"])
            self._cost()
            self.emit({"type": "segment", "phrase": args["phrase"], "count": len(boxes), "frame": args.get("frame") or self.frame_n,
                       "boxes": boxes[:200]})
            return json.dumps({"count": len(boxes), "boxes": boxes[:200]}), []
        if name == "view_frame":
            frame = self._frame(args.get("frame"))
            if "x1" in args:
                frame = frame[args.get("y1", 0):args.get("y2", frame.shape[0]), args.get("x1", 0):args.get("x2", frame.shape[1])]
            zoom = max(1, min(int(args.get("zoom", 1)), 8))
            if zoom > 1:
                frame = np.asarray(Image.fromarray(frame).resize((frame.shape[1] * zoom, frame.shape[0] * zoom), Image.NEAREST))
            return "image follows", [self._image_item(frame, f"frame {args.get('frame')}" + (f" zoom {zoom}x" if zoom > 1 else ""))]
        if name == "save_template":
            frame = self._frame(args["frame"])
            crop = frame[args["y1"]:args["y2"], args["x1"]:args["x2"]]
            if crop.size == 0:
                return "error: empty crop", []
            safe = "".join(c for c in args["name"] if c.isalnum() or c in "-_") or "template"
            Image.fromarray(crop).save(self.pkg.assets / f"{safe}.png")
            self.emit({"type": "template", "name": safe})
            return f"saved {safe} ({crop.shape[1]}x{crop.shape[0]}). Use app.find('{safe}')", []
        if name == "experiment":
            return self._experiment(args["code"], self._frame(args["frame"]))
        if name == "write_harness":
            return self._write_harness(args["code"], args.get("inputs")), []
        if name == "trial":
            return self._trial(int(args.get("seconds", 90)), args.get("params"))
        if name == "try_interface":
            return self._try_interface(args["name"], args.get("args"))
        if name == "look":
            frame = self.display.shot()
            n = self._record(frame)
            return f"frame {n}", [self._image_item(frame, f"The live app now (frame {n})")]
        if name == "act":
            return self._act(args)
        raise ValueError(f"unknown tool {name}")

    def _experiment(self, code: str, frame: np.ndarray) -> tuple[str, list]:
        """Run a snippet in the same sandbox as a real harness, against a recorded frame."""
        import tempfile

        from . import sandbox
        from .runtime import ocr
        work = Path(tempfile.mkdtemp(prefix="autoharness-exp-"))
        frame.tofile(work / "frame.bin")
        pre = ("def show(img):\n    import cv2 as _c\n    _c.imwrite('%s/show.png', img[:, :, ::-1] if img.ndim == 3 else img)\n" % work)
        proc = sandbox.spawn(self.pkg.path, work)
        output: list[str] = []
        status = {"status": "timeout"}
        killer = threading.Timer(60, proc.kill)
        killer.start()
        try:
            proc.stdin.write(json.dumps({"width": frame.shape[1], "height": frame.shape[0], "params": self.sample_params,
                                         "snippet": pre + code, "frame_shape": list(frame.shape[:2])}) + "\n")
            proc.stdin.flush()
            for line in proc.stdout:
                m = json.loads(line)
                if m["m"] == "ready":
                    continue
                if m["m"] == "end":
                    status = m
                    break
                reply: dict = {"value": None}
                if m["m"] == "log":
                    output.append(m["message"])
                elif m["m"] == "screen":
                    reply = {"value": [frame.shape[1], frame.shape[0]]}
                elif m["m"] == "ocr":
                    r = m.get("region")
                    crop = frame[r[1]:r[3], r[0]:r[2]] if r else frame
                    rows = ocr(crop)
                    reply = {"value": [[a + (r[0] if r else 0), b + (r[1] if r else 0), c + (r[0] if r else 0), d + (r[1] if r else 0), t, s] for a, b, c, d, t, s in rows]}
                else:
                    reply = {"error": "actions are not available in an experiment"}
                proc.stdin.write(json.dumps(reply) + "\n")
                proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            killer.cancel()
            proc.kill()
            proc.wait()
        text = "\n".join(output)[-6000:]
        if status.get("status") not in ("returned", "done"):
            text += f"\n[{status.get('status')}] {status.get('reason', '')}\n{status.get('traceback', '')}"
        extra = []
        shown = work / "show.png"
        if shown.exists():
            extra.append(self._image_item(np.asarray(Image.open(shown).convert("RGB")), "show() output"))
        return text or "(no output)", extra

    def _write_harness(self, code: str, inputs: list | None) -> str:
        try:
            compile(code, "harness.py", "exec")
        except SyntaxError as e:
            return f"syntax error, not saved: {e}"
        if "def run(" not in code or "def observe(" not in code:
            return "not saved: harness.py must define observe(app), at least one @verb and run(app)"
        version = self.pkg.write_code(code)
        if inputs is not None:
            self.pkg.update(inputs=inputs)
        desc = self._describe()
        value = desc.get("value") or {}
        if desc.get("status") != "returned" or not value.get("verbs"):
            self.passes_in_a_row = 0
            return (f"saved version {version}, but it does not import cleanly or has no @verb functions: "
                    f"{desc.get('reason') or 'no verbs found'}\n{desc.get('traceback', '')}")
        self.pkg.update(interface=value)
        self.passes_in_a_row = 0
        self.code_written = True
        self.emit({"type": "code", "version": version, "code": code, "lines": code.count("\n") + 1, "interface": value})
        return f"saved version {version}. Verbs: {[v['name'] for v in value['verbs']]}"

    def _act(self, args: dict) -> tuple[str, list]:
        d, kind = self.display, args["kind"]
        if kind == "restart":
            self.target.reset()
        elif kind in ("click", "right_click", "double_click"):
            d.click(args["x"], args["y"], "right" if kind == "right_click" else "left", 2 if kind == "double_click" else 1)
        elif kind == "drag":
            d.drag([(args["x"], args["y"]), (args["x2"], args["y2"])])
        elif kind == "key":
            d.press(args["text"])
        elif kind == "type":
            d.type(args["text"])
        d.wait_stable(1.5)
        frame = d.shot()
        n = self._record(frame)
        self.emit({"type": "action", "tier": "cloud", "what": kind, "x": args.get("x"), "y": args.get("y")})
        return f"frame {n}", [self._image_item(frame, f"After {kind} (frame {n})")]

    def _describe(self) -> dict:
        """What the saved harness offers to other models, read by importing it in the sandbox."""
        runner = Runner(self.pkg, self.display, None, self.sample_params, self.glimmer, stop=self.stop)
        end = runner.interface("describe", seconds=30)
        return end

    def _try_interface(self, name: str, args: dict | None) -> tuple[str, list]:
        if not self.code_written:
            return "write the harness first", []
        runner = Runner(self.pkg, self.display, self.emit, self.sample_params, self.glimmer, stop=self.stop)
        r = RunResult()
        end = runner.interface("observe" if name == "observe" else "call", verb=name, args=args, r=r, seconds=60)
        frame = self.display.shot()
        n = self._record(frame)
        out = {"status": end.get("status"), "value": end.get("value"), "reason": end.get("reason"),
               "traceback": end.get("traceback"), "log": r.log[-10:], "frame": n}
        return json.dumps(out, default=str)[:6000], [self._image_item(frame, f"Screen after {name} (frame {n})")]

    def _trial(self, seconds: int, params: dict | None) -> tuple[str, list]:
        if not self.code_written:
            return "write the harness first", []
        self.target.reset()
        seconds = max(10, min(seconds, 300))
        params = {**self.sample_params, **(params or {})}
        self.emit({"type": "trial_start", "seconds": seconds})
        runner = Runner(self.pkg, self.display, self.emit, params, self.glimmer, stop=self.stop, max_seconds=seconds, idle_limit=25)
        import tempfile
        r = RunResult(local_only=True)
        t0 = time.time()
        runner._t_end = t0 + seconds
        end = runner._launch(Path(tempfile.mkdtemp(prefix="autoharness-trial-")), r)
        r.seconds = round(time.time() - t0, 2)
        status = end.get("status", "unknown")
        self.passes_in_a_row = self.passes_in_a_row + 1 if status == "done" else 0
        frame = self.display.shot()
        n = self._record(frame)
        self.emit({"type": "trial_end", "status": status, "seconds": r.seconds, "actions": r.actions, "glimmer": r.glimmer_calls,
                   "reason": end.get("reason", "")})
        self.pkg.add_run({**r.record("trial"), "status": status})
        result = {"status": status, "seconds": r.seconds, "actions": r.actions, "glimmer_calls": r.glimmer_calls,
                  "summary": end.get("summary"), "reason": end.get("reason"), "traceback": end.get("traceback"),
                  "last_log_lines": r.log[-25:], "final_frame": n, "passes_in_a_row": self.passes_in_a_row}
        return json.dumps(result, default=str), [self._image_item(frame, f"Final screen after the trial (frame {n})")]

    # -- the loop -----------------------------------------------------------------------------

    def _loop(self, first_items: list, tools: list, instructions: str, phase: str, max_turns: int, repairing: bool = False) -> None:
        items = first_items
        for turn in range(max_turns):
            if self.stop.is_set():
                raise InterruptedError("stopped")
            left = max_turns - turn
            if left == 8:
                items = items + [{"role": "user", "content": [{"type": "input_text", "text": "Only 8 turns remain in this phase. Wrap up."}]}]
            out = self._turn(items, tools, instructions)
            next_items: list = []
            follow: list = []
            finished = False
            for item in out.get("output", []):
                kind = item.get("type")
                if kind == "message":
                    text = "\n".join(c.get("text", "") for c in item.get("content", []) if c.get("type") in ("output_text", "text")).strip()
                    if text:
                        self.emit({"type": "say", "phase": phase, "text": text[:1200]})
                elif kind == "computer_call":
                    next_items.append(self._computer_output(item))
                elif kind == "function_call":
                    name = item["name"]
                    try:
                        args = json.loads(item.get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    if name == "finish_explore":
                        self.understanding = args.get("understanding", "")
                        self.key_frames = args.get("key_frames") or []
                        (self.pkg.path / "teach" / "understanding.md").write_text(self.understanding)
                        self.emit({"type": "understanding", "text": self.understanding})
                        finished = True
                    elif name == "finish":
                        if repairing or self.passes_in_a_row >= 2:
                            self.finished_summary = args.get("summary", "")
                            next_items.append({"type": "function_call_output", "call_id": item["call_id"], "output": "accepted"})
                            finished = True
                        else:
                            next_items.append({"type": "function_call_output", "call_id": item["call_id"],
                                               "output": f"refused: the latest code has passed {self.passes_in_a_row} trials in a row, and 2 are needed"})
                    else:
                        try:
                            self.emit({"type": "tool", "name": name, "args": {k: v for k, v in args.items() if k != "code"}})
                            text, extra = self._tool(name, args)
                        except (BudgetExceeded, InterruptedError):
                            raise
                        except Exception as e:  # noqa: BLE001 - a tool error goes back to the model, which can act on it
                            text, extra = f"error: {type(e).__name__}: {e}", []
                        next_items.append({"type": "function_call_output", "call_id": item["call_id"], "output": text})
                        follow.extend(extra)
            next_items.extend(follow)
            if getattr(self, "app_restarted", False):
                self.app_restarted = False
                next_items.append({"role": "user", "content": [{"type": "input_text", "text":
                                   "Note: the app closed or crashed after your last action, so it was restarted fresh. What you see now is a new instance."}]})
            if finished:
                self.pending_items = next_items
                return
            if not next_items:
                next_items = [{"role": "user", "content": [{"type": "input_text", "text": "Keep going with your tools. Call "
                               + ("finish_explore" if phase == "explore" else "finish") + " when this phase is complete."}]}]
            items = next_items
        raise TimeoutError(f"{phase} used all {max_turns} turns")

    def _explore(self) -> None:
        frame = self.target.reset()
        n = self._record(frame)
        self.emit({"type": "phase", "phase": "explore"})
        goal = self.pkg.manifest["goal"]
        extra = ""
        if self.sample_params:
            extra = f"\n\nSample inputs the user will supply each run: {json.dumps({k: v for k, v in self.sample_params.items() if k != '_files'})}"
        first = [{"role": "user", "content": [
            {"type": "input_text", "text": f"App: {self.target.name} ({self.target.describe()})\nGoal: {goal}{extra}\n\nScreen size: {self.display.width}x{self.display.height}. Frame {n}:"},
            {"type": "input_image", "image_url": image_url(frame)}]}]
        rules = EXPLORE_RULES.format(max_turns=self.max_explore_turns)
        try:
            self._loop(first, [{"type": "computer"}, *EXPLORE_TOOLS], rules, "explore", self.max_explore_turns)
        except TimeoutError:
            self.understanding = self.understanding or "Exploration ran out of turns before a summary was written."
            self.key_frames = []

    def _compile(self, extra_message: str = "") -> None:
        """A new conversation, without the computer tool. Meta's API accepts images only in the first request of a
        computer-use conversation, and writing code needs to look at frames. This also keeps the context focused."""
        self.emit({"type": "phase", "phase": "compile"})
        rules = COMPILE_RULES.format(sdk=sdk_reference())
        if extra_message:
            items = list(getattr(self, "pending_items", []))
            self.pending_items = []
            items.append({"role": "user", "content": [{"type": "input_text", "text": extra_message + f"\nThe latest frame number is {self.frame_n}."}]})
            self._loop(items, COMPILE_TOOLS, rules, "compile", self.max_compile_turns)
            return
        self.prev_id = None
        m = self.pkg.manifest
        params = {k: v for k, v in self.sample_params.items() if k != "_files"}
        content: list = [{"type": "input_text", "text":
                          f"App: {self.target.name}\nGoal: {m['goal']}\nSample inputs each run: {json.dumps(params)}\n"
                          f"Screen size: {self.display.width}x{self.display.height}. Recorded frames 1 to {self.frame_n}; view any with view_frame.\n\n"
                          f"What you learned by exploring the app:\n{self.understanding}\n\nNotes: {json.dumps(self.notes)}\n\nKey frames:"}]
        for kf in (getattr(self, "key_frames", []) or [])[:8]:
            try:
                content.append({"type": "input_text", "text": f"Frame {kf['frame']}: {kf.get('shows', '')}"})
                content.append({"type": "input_image", "image_url": image_url(self._frame(int(kf["frame"])))})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        content.append({"type": "input_text", "text": "Now write the program."})
        self._loop([{"role": "user", "content": content}], COMPILE_TOOLS, rules, "compile", self.max_compile_turns)

    def _verify(self) -> tuple[int, list[dict]]:
        """Fresh instance, no cloud, no recovery from the teacher. Then an independent judge."""
        self.emit({"type": "phase", "phase": "verify"})
        goal = self.pkg.manifest["goal"]
        passed = 0
        rows = []
        for i in range(self.verify_runs):
            if self.stop.is_set():
                raise InterruptedError("stopped")
            self.target.reset()
            self.emit({"type": "verify_start", "n": i + 1, "of": self.verify_runs})
            runner = Runner(self.pkg, self.display, self.emit, self.sample_params, self.glimmer, stop=self.stop, max_seconds=300)
            r = runner.execute(local_only=True)
            frame = self.display.shot()
            n = self._record(frame)
            verdict = {"achieved": False, "why": r.reason}
            if r.status == "done":
                verdict = judge_final_screen(self.cloud, goal, frame, r.summary, app_notes(self.pkg))
                self._cost()
            ok = r.status == "done" and verdict["achieved"]
            passed += ok
            rec = r.record("verify")
            rec.update(status="done" if ok else "failed", judge=verdict, frame=n)
            self.pkg.add_run(rec)
            rows.append({"status": rec["status"], "seconds": r.seconds, "actions": r.actions, "glimmer_calls": r.glimmer_calls,
                         "reason": r.reason, "judge": verdict["why"], "frame": n, "last_log_lines": r.log[-15:], "traceback": r.traceback})
            self.emit({"type": "verify_end", "n": i + 1, "of": self.verify_runs, "ok": ok, "seconds": r.seconds, "actions": r.actions,
                       "glimmer": r.glimmer_calls, "why": verdict["why"]})
        return passed, rows

    def teach(self) -> dict:
        """The whole lesson. Always leaves the package in a state the UI can explain."""
        pkg = self.pkg
        try:
            self._explore()
            try:
                self._compile()
            except TimeoutError as e:
                # Out of turns isn't failure if the program works. Verification decides, not the turn counter.
                if not self.code_written:
                    raise
                self.emit({"type": "log", "tier": "cloud", "text": f"{e}. Testing the latest program as it stands."})
            needed = max(1, int(np.ceil(self.verify_runs * 0.8)))
            for round_n in range(3):
                passed, rows = self._verify()
                if passed >= needed:
                    break
                if round_n == 2:
                    pkg.update(status="failed", failure=f"passed only {passed} of {self.verify_runs} verification runs")
                    break
                self.passes_in_a_row = 0
                self.emit({"type": "phase", "phase": "compile"})
                report = json.dumps([{k: v for k, v in row.items()} for row in rows if row["status"] != "done"], default=str)[:8000]
                try:
                    self._compile(f"Verification on fresh copies passed {passed} of {self.verify_runs}, and {needed} are needed. "
                                  f"Failures: {report}\nView the listed frames if you need to, fix the cause, and pass two trials again.")
                except TimeoutError as e:
                    self.emit({"type": "log", "tier": "cloud", "text": f"{e}. Testing the latest program as it stands."})
            else:
                passed = 0
            if pkg.manifest.get("status") != "failed":
                pkg.update(status="ready", verified=f"{passed}/{self.verify_runs}", how=self.finished_summary or "", notes=self.notes)
        except BudgetExceeded as e:
            pkg.update(status="failed", failure=str(e))
        except InterruptedError:
            pkg.update(status="stopped", failure="stopped by the user")
        except TimeoutError as e:
            pkg.update(status="failed", failure=str(e))
        except CloudError as e:
            pkg.update(status="failed", failure=str(e))
        except Exception as e:  # noqa: BLE001 - never leave a job silently dead
            pkg.update(status="failed", failure=f"{type(e).__name__}: {e}")
            self.emit({"type": "error", "text": traceback.format_exc()[-1500:]})
        pkg.update(teach_usd=round(self.meter.usd, 4), teach_seconds=round(time.time() - self._t0), teach_calls=self.meter.calls,
                   teach_tokens=self.meter.input_tokens + self.meter.output_tokens, frames=self.frame_n)
        self._cost()
        self.emit({"type": "taught", **{k: pkg.manifest.get(k) for k in ("status", "failure", "verified", "teach_usd", "teach_seconds")}})
        return pkg.manifest


class Repairer(Teacher):
    """Called back during a real run, once. Fixes the program from evidence, then the run picks up from the current screen."""

    def __init__(self, pkg: Package, display: Display, target: Target | None, emit: Emit | None = None, stop=None, limit_usd: float = 1.0):
        super().__init__(pkg, display, target, emit, stop, limit_usd=limit_usd, max_compile_turns=30, verify_runs=0)
        self.frame_n = len(list(self.frames_dir.glob("*.png")))
        self.code_written = True

    def __call__(self, frame: np.ndarray, reason: str, tb: str, log: list) -> dict:
        before = self.meter.snapshot()
        self.prev_id = None
        self.finished_summary = None
        n = self._record(frame)
        m = self.pkg.manifest
        understanding = ""
        p = self.pkg.path / "teach" / "understanding.md"
        if p.exists():
            understanding = p.read_text()[:6000]
        msg = (f"You taught this harness earlier, and it just failed during a real run. Repair it.\n\nGoal: {m.get('goal')}\n\n"
               f"How the app works, in your earlier words:\n{understanding}\n\nNotes: {m.get('notes', [])}\n\nThe failure: {reason}\n{tb}\n\nLast log lines: {log}\n\n"
               f"The current harness.py:\n```python\n{self.pkg.code}\n```\n\nSaved templates: {[f.name for f in self.pkg.assets.glob('*.png')]}\n\n"
               f"This is the screen right now (frame {n}). Find the cause and write the corrected whole harness with write_harness. It will restart from this exact screen, so it must cope with that. "
               "Do not touch anything outside the harness. Call finish when done.")
        rules = REPAIR_INSTRUCTIONS.format(sdk=sdk_reference())
        items = [{"role": "user", "content": [{"type": "input_text", "text": msg}, {"type": "input_image", "image_url": image_url(frame)}]}]
        fixed = False
        try:
            self._loop(items, REPAIR_TOOLS, rules, "repair", self.max_compile_turns, repairing=True)
            fixed = self.finished_summary is not None
        except (CloudError, TimeoutError) as e:
            self.emit({"type": "log", "tier": "cloud", "text": f"Repair failed: {e}"})
        after = self.meter.snapshot()
        return {"fixed": fixed, "summary": self.finished_summary or "", "usd": round(after["usd"] - before["usd"], 5),
                "calls": after["calls"] - before["calls"], "bytes": after["bytes_sent"] - before["bytes_sent"]}


REPAIR_INSTRUCTIONS = """You repair a harness: one function `run(app)` that automates an app without any large model. Use only this API, numpy (np), \
cv2 and the standard library:

{sdk}

It also offers observe(app) and @verb functions (from sdk import verb), the interface other models use: keep those working. Keep what works. \
Make it deterministic, keep it restartable from any screen, verify after each action, and call app.fail when it truly cannot continue. \
Tools: view_frame, experiment, segment, save_template, write_harness, finish."""


def baseline(display: Display, target: Target, goal: str, emit: Emit | None = None, stop: threading.Event | None = None,
             limit_usd: float = 2.0, max_turns: int = 150, effort: str = "low", notes: str = "") -> dict:
    """The comparison: Spark doing the job itself through computer use, every step, the way agents work today."""
    emit = emit or (lambda e: None)
    stop = stop or threading.Event()
    meter = Meter()
    cloud = Cloud(meter, limit_usd=limit_usd)
    frame = target.reset()
    t0 = time.time()
    helper = Teacher.__new__(Teacher)
    helper.display, helper.target, helper.emit, helper.meter, helper.approve = display, target, emit, meter, None
    prev, turns, actions = None, 0, 0
    items = [{"role": "user", "content": [{"type": "input_text", "text": f"Goal: {goal}\nScreen size: {display.width}x{display.height}."},
                                          {"type": "input_image", "image_url": image_url(frame)}]}]
    status = "ran out of turns"
    while turns < max_turns and not stop.is_set():
        body = dict(model=config.TEACHER_MODEL, tools=[{"type": "computer"}], input=items, reasoning={"effort": effort},
                    instructions="Use the computer tool to reach the goal. Stop when it is reached.")
        if prev:
            body["previous_response_id"] = prev
        try:
            out = cloud.respond(**body)
        except BudgetExceeded as e:
            status = str(e)
            break
        prev = out["id"]
        turns += 1
        emit({"type": "cost", **meter.snapshot()})
        calls = [i for i in out.get("output", []) if i.get("type") == "computer_call"]
        for i in out.get("output", []):
            if i.get("type") == "message":
                text = "".join(c.get("text", "") for c in i.get("content", []))
                if text:
                    emit({"type": "say", "phase": "baseline", "text": text[:400]})
        if not calls:
            status = "finished"
            break
        items = []
        for call in calls:
            actions += len([a for a in call.get("actions", []) if a.get("type") not in ("screenshot", "wait")])
            helper._do_actions(call.get("actions", []))
            display.wait_stable(1.5)
            shot = display.shot()
            items.append({"type": "computer_call_output", "call_id": call["call_id"], "acknowledged_safety_checks":
                          [{"id": c.get("id"), "code": c.get("code"), "message": c.get("message")} for c in call.get("pending_safety_checks") or []],
                          "output": {"type": "computer_screenshot", "image_url": image_url(shot)}})
    seconds = time.time() - t0
    verdict = judge_final_screen(cloud, goal, display.shot(), app_notes=notes) if status == "finished" else {"achieved": False, "why": status}
    return {"achieved": verdict["achieved"], "why": verdict["why"], "status": status, "seconds": round(seconds, 1), "turns": turns,
            "actions": actions, **{k: v for k, v in meter.snapshot().items() if k in ("usd", "bytes_sent", "input_tokens", "output_tokens")}, "at": time.time()}
