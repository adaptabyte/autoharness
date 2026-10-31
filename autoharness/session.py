"""An app kept open and offered to models through the interface a model designed for it.

Instead of screenshots, a model gets a few dozen tokens of state and a list of typed verbs. Glimmer can
operate the app this way from a plain request, and any other agent can do the same over MCP.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Callable

import numpy as np

from .desktop import Display
from .library import Package
from .local import Glimmer, LocalModelError, extract_json
from .runtime import Runner, RunResult
from .targets import Target


class Session:
    def __init__(self, pkg: Package, display: Display, target: Target, emit: Callable[[dict], None] | None = None,
                 stop: threading.Event | None = None, approve=None, glimmer: Glimmer | None = None):
        self.pkg, self.display, self.target = pkg, display, target
        self.emit = emit or (lambda e: None)
        self.stop = stop or threading.Event()
        self.glimmer = glimmer or Glimmer()
        self.runner = Runner(pkg, display, self.emit, pkg.manifest.get("target", {}).get("sample_params"),
                             self.glimmer, approve, self.stop)
        self.lock = threading.Lock()
        self.interface = pkg.manifest.get("interface") or {}
        self.screenshot_tokens: int | None = None

    def tools(self) -> list[dict]:
        goal = self.pkg.manifest.get("goal", "")
        return [
            {"name": "observe", "description": "Read the app's current state as compact JSON. "
             + (self.interface.get("observe_doc") or ""), "parameters": {"type": "object", "properties": {}}},
            *self.interface.get("verbs", []),
            {"name": "run_goal", "description": f"Do the whole job end to end: {goal}", "parameters": {"type": "object", "properties": {}}},
        ]

    def observe(self):
        with self.lock:
            end = self.runner.interface("observe", seconds=60)
        if end.get("status") != "returned":
            raise RuntimeError(end.get("reason") or "observe failed")
        return end.get("value")

    def call(self, name: str, args: dict | None = None):
        if name == "observe":
            return self.observe()
        with self.lock:
            if name == "run_goal":
                r = self.runner.execute(local_only=True)
                self.runner.max_seconds = 600
                self.pkg.add_run(r.record("run"))
                if r.status != "done":
                    raise RuntimeError(r.reason or r.status)
                return r.summary
            end = self.runner.interface("call", verb=name, args=args, r=RunResult(), seconds=180)
        if end.get("status") != "returned":
            raise RuntimeError(end.get("reason") or "the verb failed")
        return end.get("value")

    def measure_screenshot(self) -> int | None:
        """What one screenshot really costs this model, in prompt tokens. Measured, not assumed."""
        if self.screenshot_tokens is None:
            try:
                self.glimmer.ask("Say OK.", self.display.shot(), max_tokens=64)
                self.screenshot_tokens = self.glimmer.last_prompt_tokens
            except LocalModelError:
                return None
        return self.screenshot_tokens


OPERATOR = """You operate an app through an interface built for models. You never see a screen.

The app: {name}
Its purpose here: {goal}

Verbs you can call:
{verbs}

The current state of the app, from observe():
{state}

What has happened so far:
{history}

The request: {request}

Decide the single next step. Reply with only JSON, one of:
{{"verb": "name", "args": {{...}}}}
{{"finished": "a short answer for the person"}}"""


def operate(session: Session, request: str, emit: Callable[[dict], None], stop: threading.Event | None = None,
            max_steps: int = 25) -> dict:
    """Glimmer carries out a plain-language request using only state and verbs."""
    stop = stop or session.stop
    glimmer = session.glimmer
    m = session.pkg.manifest
    verbs = json.dumps(session.interface.get("verbs", []), indent=0)
    history: list[str] = []
    total_prompt = steps = 0
    screenshot = session.measure_screenshot()
    t0 = time.time()
    answer = None
    for _ in range(max_steps):
        if stop.is_set():
            break
        try:
            state = session.observe()
        except RuntimeError as e:
            state = {"observe_failed": str(e)}
        state_text = json.dumps(state, separators=(",", ":"), default=str)
        emit({"type": "op_state", "state": state_text[:4000]})
        prompt = OPERATOR.format(name=m.get("name"), goal=m.get("goal"), verbs=verbs, state=state_text,
                                 history="\n".join(history[-12:]) or "(nothing yet)", request=request)
        emit({"type": "ask", "tier": "glimmer", "text": "Deciding the next step"})
        started = time.time()
        reply = glimmer.ask(prompt, schema={"verb": "name, or omit", "args": {}, "finished": "answer, or omit"}, max_tokens=2000)
        total_prompt += glimmer.last_prompt_tokens or 0
        steps += 1
        emit({"type": "op_tokens", "prompt_tokens": glimmer.last_prompt_tokens, "screenshot_tokens": screenshot,
              "state_tokens": max(1, len(state_text) // 4), "seconds": round(time.time() - started, 1), "steps": steps})
        if reply.get("finished"):
            answer = str(reply["finished"])
            break
        verb, args = reply.get("verb"), reply.get("args") or {}
        if not verb:
            history.append("You replied with neither a verb nor finished.")
            continue
        emit({"type": "op_call", "verb": verb, "args": args})
        try:
            result = session.call(verb, args)
            history.append(f"{verb}({json.dumps(args)}) -> {json.dumps(result, default=str)[:300]}")
            emit({"type": "op_result", "verb": verb, "result": json.dumps(result, default=str)[:600], "ok": True})
        except (RuntimeError, ValueError, TypeError) as e:
            history.append(f"{verb}({json.dumps(args)}) FAILED: {e}")
            emit({"type": "op_result", "verb": verb, "result": str(e)[:600], "ok": False})
    out = {"answer": answer or "It stopped before finishing.", "finished": answer is not None, "steps": steps,
           "seconds": round(time.time() - t0, 1), "prompt_tokens": total_prompt, "screenshot_tokens": screenshot,
           "state_tokens": None}
    emit({"type": "op_end", **out})
    return out
