"""The API a harness is written against. This file runs inside the sandbox, with no network, no display
connection and no access to the user's files. All it can do is ask the parent process to act.

A harness is harness.py. It holds the interface the model designed for itself: observe(app), the app's
state in as few tokens as possible, and @verb functions, whole meaningful operations with typed arguments.
run(app) reaches the goal end to end on top of them.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


VERBS: dict = {}


def verb(fn):
    """Marks a function in harness.py as an operation other models may call: def reveal(app, row: int, col: int)."""
    VERBS[fn.__name__] = fn
    return fn


def describe_verb(fn) -> dict:
    """A verb as a JSON-schema tool description, built from its signature and docstring."""
    types = {int: "integer", float: "number", str: "string", bool: "boolean", "int": "integer", "float": "number",
             "str": "string", "bool": "boolean", list: "array", dict: "object", "list": "array", "dict": "object"}
    sig = inspect.signature(fn)
    props, required = {}, []
    for name, p in list(sig.parameters.items())[1:]:
        props[name] = {"type": types.get(p.annotation, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(name)
        else:
            props[name]["default"] = p.default
    return {"name": fn.__name__, "description": (inspect.getdoc(fn) or "").strip(),
            "parameters": {"type": "object", "properties": props, "required": required}}


class Done(BaseException):
    """Raised by app.done(). Derives from BaseException so `except Exception` in a harness cannot eat it."""


class Stuck(Exception):
    """The harness cannot continue. The runtime tries local recovery, then asks the teacher to repair it."""


@dataclass
class Match:
    x: int
    y: int
    box: tuple[int, int, int, int]
    score: float
    text: str = ""

    @property
    def center(self) -> tuple[int, int]:
        return self.x, self.y


class App:
    """Everything a harness may do. See the docstrings: they are what the teacher model reads."""

    def __init__(self, rpc_in, rpc_out, workdir: Path, assets: Path, init: dict):
        self._in, self._out = rpc_in, rpc_out
        self._work = workdir
        self._assets = assets
        self.params: dict = init.get("params", {})
        self.state: dict = init.get("state", {})
        self.width: int = init["width"]
        self.height: int = init["height"]
        self._templates: dict = {}

    def _call(self, method: str, **kw):
        self._out.write(json.dumps({"m": method, **kw}) + "\n")
        self._out.flush()
        line = self._in.readline()
        if not line:
            raise SystemExit("runtime went away")
        reply = json.loads(line)
        if reply.get("error"):
            raise Stuck(reply["error"])
        return reply.get("value")

    # -- seeing ---------------------------------------------------------------------------------
    def screen(self, region=None) -> np.ndarray:
        """A fresh screenshot as an RGB numpy array (height, width, 3). region = (x1, y1, x2, y2)."""
        w, h = self._call("screen")
        frame = np.fromfile(self._work / "frame.bin", dtype=np.uint8, count=w * h * 3).reshape(h, w, 3)
        if region:
            x1, y1, x2, y2 = region
            return frame[y1:y2, x1:x2]
        return frame

    def _template(self, name: str) -> np.ndarray:
        if name not in self._templates:
            path = self._assets / (name if name.endswith(".png") else name + ".png")
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                raise Stuck(f"no such template: {name}")
            self._templates[name] = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return self._templates[name]

    def find_all(self, template: str, region=None, threshold: float = 0.92, frame=None) -> list[Match]:
        """Every place a saved template appears, best first. Overlapping hits are merged."""
        tpl = self._template(template)
        img = frame if frame is not None else self.screen()
        ox, oy = 0, 0
        if region:
            ox, oy, x2, y2 = region
            img = img[oy:y2, ox:x2]
        if img.shape[0] < tpl.shape[0] or img.shape[1] < tpl.shape[1]:
            return []
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
        th, tw = tpl.shape[:2]
        ys, xs = np.where(res >= threshold)
        hits = sorted(zip(res[ys, xs].tolist(), xs.tolist(), ys.tolist()), reverse=True)
        kept: list[Match] = []
        for score, x, y in hits[:5000]:
            if all(abs(x + ox - m.box[0]) >= tw / 2 or abs(y + oy - m.box[1]) >= th / 2 for m in kept):
                kept.append(Match(x + ox + tw // 2, y + oy + th // 2,
                                  (x + ox, y + oy, x + ox + tw, y + oy + th), float(score)))
        return kept

    def find(self, template: str, region=None, threshold: float = 0.92, frame=None) -> Match | None:
        """The best match of a saved template on screen, or None."""
        hits = self.find_all(template, region, threshold, frame)
        return hits[0] if hits else None

    def read_text(self, region=None) -> list[Match]:
        """Read text from the screen with local OCR. Each Match has .text, .box, .center and .score."""
        rows = self._call("ocr", region=region)
        return [Match((r[0] + r[2]) // 2, (r[1] + r[3]) // 2, tuple(r[:4]), r[5], r[4]) for r in rows]

    def find_text(self, text: str, region=None, exact: bool = False) -> Match | None:
        """Find text on screen, case-insensitive. A substring match unless exact=True."""
        want = text.lower().strip()
        best = None
        for m in self.read_text(region):
            got = m.text.lower().strip()
            if got == want or (not exact and want in got):
                if best is None or len(got) < len(best.text):
                    best = m
        return best

    # -- doing ----------------------------------------------------------------------------------
    def click(self, x, y=None, button: str = "left") -> None:
        """Click at (x, y), or at a Match: app.click(match)."""
        if y is None:
            x, y = x.x, x.y
        self._call("click", x=int(x), y=int(y), button=button)

    def right_click(self, x, y=None) -> None:
        self.click(x, y, button="right")

    def double_click(self, x, y=None) -> None:
        if y is None:
            x, y = x.x, x.y
        self._call("double_click", x=int(x), y=int(y))

    def click_text(self, text: str, region=None, exact: bool = False) -> None:
        """Click the on-screen text. Raises Stuck if it is not there."""
        m = self.find_text(text, region, exact)
        if m is None:
            raise Stuck(f"text not on screen: {text!r}")
        self.click(m)

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self._call("drag", path=[[int(x1), int(y1)], [int(x2), int(y2)]])

    def move(self, x: int, y: int) -> None:
        self._call("move", x=int(x), y=int(y))

    def scroll(self, x: int, y: int, dy: int = 0, dx: int = 0) -> None:
        """Scroll at a point. dy > 0 scrolls down, in wheel notches."""
        self._call("scroll", x=int(x), y=int(y), dx=int(dx), dy=int(dy))

    def type(self, text: str) -> None:
        """Type text into whatever has focus."""
        self._call("type", text=str(text))

    def key(self, combo: str) -> None:
        """Press a key or chord: 'Return', 'Tab', 'Escape', 'ctrl+a'."""
        self._call("key", combo=combo)

    def wait(self, seconds: float) -> None:
        self._call("wait", seconds=float(seconds))

    def wait_stable(self, timeout: float = 3.0, region=None) -> bool:
        """Wait until the screen stops changing. Use after any action, instead of fixed sleeps."""
        return bool(self._call("wait_stable", timeout=float(timeout), region=region))

    # -- thinking and people --------------------------------------------------------------------
    def ask(self, question: str, region=None, choices=None, schema=None, image=None):
        """Ask Muse Glimmer, the local model, about the screen (or `image`, a file named in app.params).

        It costs seconds, so use it only where code cannot decide: reading messy or unfamiliar content,
        or a real judgment call. choices=[...] returns one of them. schema={...} returns parsed JSON.
        Otherwise returns text.
        """
        return self._call("ask", question=question, region=region, choices=choices, schema=schema, image=image)

    def confirm(self, message: str) -> bool:
        """Pause for a person to approve an action that cannot be undone. Returns their answer."""
        return bool(self._call("confirm", message=message))

    def log(self, message) -> None:
        """Show a line in the run's activity feed. Say what the harness is doing, in plain words."""
        self._call("log", message=str(message)[:500])

    def done(self, summary: str = "", **result) -> None:
        """Finish successfully. Call only after checking on screen that the goal really was reached."""
        self._out.write(json.dumps({"m": "end", "status": "done", "summary": str(summary)[:1000],
                                    "result": result, "state": self.state}, default=str) + "\n")
        self._out.flush()
        raise Done()

    def fail(self, reason: str) -> None:
        """Say the harness cannot continue from here, so the runtime can try to recover."""
        raise Stuck(reason)
