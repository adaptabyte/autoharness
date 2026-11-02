"""Any interface, compiled into a team a small model can run.

explore():  a capable model uses the interface through computer use, and everything it sees and does is recorded.
compile_plan(): the strongest model turns that record into a plan. A plan is data, never code: general skills made of small steps.
PlanRunner: code walks the plan and holds all the memory. The small model is only ever asked one narrow question about one
screen: where is this, is this true, what does this say. Every write is read back. Anything that doesn't check out stops the
run and hands off, so a run ends either verified or asking for help, and never quietly wrong.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Callable

import numpy as np

from . import config, team
from .cloud import BudgetExceeded, Cloud, CloudError, Meter, image_url, response_text
from .desktop import Display
from .local import Glimmer, LocalModelError, extract_json

Emit = Callable[[dict], None]
STEP_KINDS = {"click", "double_click", "type", "choose", "key", "wait", "scroll", "ensure", "dismiss", "read", "read_list", "compare", "if", "for_each", "call", "stop_for_person"}


class NeedsHelp(Exception):
    """The run can't honestly continue. Nothing after this point happens without someone looking."""


# ---- The record of a capable model using the interface ------------------------------------------------------------------

def explore(display: Display, target, goal: str, meter: Meter, frames: list | None = None, limit_usd: float = 0.6, max_turns: int = 45, emit: Emit | None = None, stop: threading.Event | None = None) -> dict:
    """Muse Spark does the job once through computer use. The record is what the compiler learns from."""
    from .teacher import Teacher

    emit = emit or (lambda e: None)
    stop = stop or threading.Event()
    cloud = Cloud(meter=meter, limit_usd=limit_usd)
    helper = Teacher.__new__(Teacher)
    helper.display, helper.target, helper.emit, helper.meter, helper.approve = display, target, emit, meter, None
    target.reset()
    frame = display.shot()
    record: list[dict] = [{"i": 0, "image": frame, "said": "", "did": "the app as it first appears"}]
    items = [{"role": "user", "content": [{"type": "input_text", "text": f"Goal: {goal}\nScreen size: {display.width}x{display.height}."}, {"type": "input_image", "image_url": image_url(frame)}]}]
    prev, turns, status = None, 0, "ran out of turns"
    instructions = "Use the computer tool to reach the goal. Before each action, say in one short sentence what you see and why you're doing it. Stop when the goal is reached and state what you found. Coordinates are real pixels."
    while turns < max_turns and not stop.is_set():
        body = dict(model=config.SPARK_MODEL, tools=[{"type": "computer"}], input=items, reasoning={"effort": "low"}, instructions=instructions)
        if prev:
            body["previous_response_id"] = prev
        try:
            out = cloud.respond(**body)
        except BudgetExceeded as e:
            status = str(e)
            break
        except CloudError as e:
            if "invalid parameters" not in str(e) or not prev:
                status = str(e)[:200]
                break
            prev = None
            items = [{"role": "user", "content": [{"type": "input_text", "text": f"Goal: {goal}\nScreen size: {display.width}x{display.height}. You were already working on this and the earlier conversation had to end. Carry on from the screen as it is now."}, {"type": "input_image", "image_url": image_url(display.shot())}]}]
            continue
        prev = out["id"]
        turns += 1
        said = " ".join(c.get("text", "") for i in out.get("output", []) if i.get("type") == "message" for c in i.get("content", [])).strip()
        calls = [i for i in out.get("output", []) if i.get("type") == "computer_call"]
        emit({"type": "explore", "turn": turns, "said": said[:300], "usd": round(meter.usd, 4)})
        if not calls:
            record.append({"i": turns, "image": display.shot(), "said": said, "did": "finished"})
            status = "finished"
            break
        items = []
        for call in calls:
            actions = call.get("actions", [])
            helper._do_actions(actions)
            display.wait_stable(1.5)
            shot = display.shot()
            done = [{k: v for k, v in a.items() if k in ("type", "x", "y", "text", "keys", "scroll_y", "button")} for a in actions if a.get("type") not in ("screenshot", "wait")]
            record.append({"i": turns, "image": shot, "said": said, "did": json.dumps(done)[:400]})
            items.append({"type": "computer_call_output", "call_id": call["call_id"], "acknowledged_safety_checks": [{"id": c.get("id"), "code": c.get("code"), "message": c.get("message")} for c in call.get("pending_safety_checks") or []],
                          "output": {"type": "computer_screenshot", "image_url": image_url(shot)}})
    return {"goal": goal, "status": status, "record": record, "turns": turns, "usd": round(meter.usd, 4)}


# ---- Compiling ------------------------------------------------------------------------------------------------------------

STEP_DOCS = """Each step is one JSON object. Text may use {name} for an input or a value read earlier, including {row.field} inside for_each.
{"do":"click","target":"the blue Login button, bottom of the form"}  also "double_click". Describe the thing so someone could find it on a single screenshot, with its label and where it is.
{"do":"type","target":"the Username box","text":"{username}"}  clicks it, replaces its contents, types, then reads it back and compares. Add "secret":true for passwords (can't be read back), "enter":true to press Enter after, "no_check":true only if the box empties itself after entering.
{"do":"choose","target":"the Outcome dropdown","option":"{row.outcome}"}  picks from a native dropdown and reads it back.
{"do":"key","keys":"Return"}  or "ctrl+a", "Tab" and so on.
{"do":"wait","seconds":2}
{"do":"scroll","dy":5}  wheel notches at the middle of the screen, negative is up. Add "target" to scroll over a specific pane.
{"do":"ensure","question":"Is the Patient Finder table showing, with a row for {last}?","why":"..."}  a yes/no about the current screen. A no stops and asks for help, so use these after anything that changes the screen, before you rely on it.
{"do":"dismiss","question":"Is a popup asking about product registration open?","target":"the Ask Again Later button"}  clicks only if the question is yes. Use it for things that appear only sometimes.
{"do":"read","into":"facts","fields":{"dob":"the date of birth","member_id":"the External ID in parentheses after the name"},"types":{"dob":"date","member_id":"id"}}  reads values off the current screen twice, independently. Types: id, date, number, money, name, code, text. If the two reads disagree it stops.
{"do":"read_list","into":"rows","item":{"drug":"...","start":"..."},"where":"which rows count and which don't","scroll":3,"max_pages":6}  reads a list that may scroll, page by page, merging rows in code, until a page adds nothing new. Set "scroll":0 if it fits on one screen.
{"do":"compare","a":"{facts.name}","b":"{first} {last}","kind":"name"}  plain code; a mismatch stops the run. Use it to confirm you're on the right record.
{"do":"if","question":"...yes/no...","then":[steps],"else":[steps]}
{"do":"for_each","list":"{trials}","as":"row","steps":[steps]}
{"do":"call","skill":"log_in","with":{"username":"{username}"}}  another skill in this plan.
{"do":"stop_for_person","message":"..."}  stop on purpose, for something only a person may do, such as signing or submitting.
"""
COMPILE_RULES = """You're compiling a human interface into a plan that a very small, very forgetful vision model can run, by the thousand, with no help from you.

The small model never sees the plan and has no memory. Code walks the plan. For each step the model sees one screenshot and answers one narrow question: where is this thing, is this true, what does this say. It's good at that and bad at deciding what to do. So all the deciding must be done by you, now, in the plan.

Below is a record of a capable model using the interface. Learn how the interface really behaves, including what went wrong and what appeared unexpectedly. Don't copy its mistakes, wrong turns or retries. Then write the plan.

Rules for a good plan:
- Make skills general, with inputs. No value from the record may be baked in: patient names, dates and numbers must be inputs. Prefer several small reusable skills (log_in, open_record, read_record, edit_field) that one skill per job composes with "call".
- Add a "dismiss" for every popup or interruption seen in the record, wherever it can appear.
- After anything that changes the screen, add an "ensure" that would catch going to the wrong place. Before reading or changing a record, confirm with "read" and "compare" that it's the right one.
- Keep each target description unmistakable on a single screenshot: its label, its kind and where it is, and how to tell it from look-alikes.
- Each read names only what's visible on that one screen; scroll first if needed. Say how to tell a value from look-alikes beside it.
- Where a job could be wrong without an error showing, read the result back at the end and compare.
- Anything irreversible that a person must do, such as signing or submitting, gets stop_for_person. Never go past it.

Steps available, and no others:
{steps}
Reply with only one JSON object, no other text:
{{"app":"name","how_it_behaves":"a few sentences a repairer would need","skills":[{{"name":"snake_case","does":"one plain sentence","inputs":{{"name":"what it is"}},"outputs":["keys of values it reads, to report at the end"],"steps":[...]}}],"jobs":{{"job_name":"skill to run for this kind of request"}}}}"""
REPAIR_RULES = """You wrote this plan for a small model that answers one narrow question per screenshot, and code walks the plan. A proof run went wrong. Fix the plan so this can't happen again, without baking in any values from this run. The trace shows each step that ran and how it went; the images are the screen just before the failure and at the failure. Often the fix is a clearer target description, a dismiss for something unexpected, a wait, a different route, or a looser question for an ensure that was asking too much of a single screenshot.

Steps available, and no others:
{steps}
Reply with only the complete corrected plan as one JSON object in the same shape."""


def check_steps(steps: list, skills: set, path: str = "") -> None:
    if not isinstance(steps, list):
        raise ValueError(f"{path}: steps must be a list")
    for n, s in enumerate(steps):
        where = f"{path}[{n}]"
        if not isinstance(s, dict) or s.get("do") not in STEP_KINDS:
            raise ValueError(f"{where}: unknown step {s!r}"[:200])
        kind = s["do"]
        needs = {"click": ["target"], "double_click": ["target"], "type": ["target", "text"], "choose": ["target", "option"], "key": ["keys"], "ensure": ["question"], "dismiss": ["question", "target"], "read": ["into", "fields"], "read_list": ["into", "item"],
                 "compare": ["a", "b"], "if": ["question"], "for_each": ["list", "as", "steps"], "call": ["skill"], "stop_for_person": ["message"]}.get(kind, [])
        for k in needs:
            if k not in s:
                raise ValueError(f"{where}: {kind} needs {k}")
        if kind == "call" and s["skill"] not in skills:
            raise ValueError(f"{where}: no skill called {s['skill']}")
        for k in ("then", "else", "steps"):
            if k in s:
                check_steps(s[k], skills, f"{where}.{k}")


def check_plan(plan: dict) -> dict:
    """A plan comes from a model, so it's validated like any other outside input. Code runs it as data; nothing in it is executed."""
    if not isinstance(plan, dict) or not plan.get("skills"):
        raise ValueError("the plan has no skills")
    names = {s.get("name") for s in plan["skills"]}
    for s in plan["skills"]:
        check_steps(s.get("steps"), names, s.get("name", "?"))
    return plan


def _strip_images(record: list[dict], max_images: int) -> tuple[list, list]:
    """The record as text, plus the screens most worth seeing: those where the picture changed the most, always keeping first and last."""
    lines = [f"{r['i']}. said: {r['said'][:220]} | did: {r['did']}" for r in record]
    if len(record) <= max_images:
        chosen = list(range(len(record)))
    else:
        diffs = [(float(np.abs(record[i]["image"][::8, ::8].astype(np.int16) - record[i - 1]["image"][::8, ::8].astype(np.int16)).mean()), i) for i in range(1, len(record))]
        chosen = sorted({0, len(record) - 1} | {i for _, i in sorted(diffs, reverse=True)[:max_images - 2]})
    return lines, chosen


def compile_plan(records: list[dict], note: str = "", meter: Meter | None = None, limit_usd: float = 1.5, effort: str = "medium", max_images: int = 14) -> dict:
    """The strongest model writes the plan. Wonder can't use the computer tool, which is why Spark gathers the record."""
    meter = meter or Meter()
    cloud = Cloud(meter=meter, limit_usd=limit_usd)
    content: list = [{"type": "input_text", "text": COMPILE_RULES.format(steps=STEP_DOCS) + (f"\n\nWhat the person wants: {note}" if note else "")}]
    for rec in records:
        lines, chosen = _strip_images(rec["record"], max_images)
        content.append({"type": "input_text", "text": f"\n\nJOB: {rec['goal']}\nHow it ended: {rec['status']}\nWhat happened:\n" + "\n".join(lines) + "\n\nScreens, labelled by step number:"})
        for i in chosen:
            content.append({"type": "input_text", "text": f"step {rec['record'][i]['i']}:"})
            content.append({"type": "input_image", "image_url": image_url(rec["record"][i]["image"], 78)})
    out = cloud.respond(model=config.TEACHER_MODEL, reasoning={"effort": effort}, input=[{"role": "user", "content": content}])
    return check_plan(extract_json(response_text(out)))


def repair_plan(plan: dict, failure: dict, frames: list[np.ndarray], meter: Meter | None = None, limit_usd: float = 0.6) -> dict:
    meter = meter or Meter()
    cloud = Cloud(meter=meter, limit_usd=limit_usd)
    content: list = [{"type": "input_text", "text": REPAIR_RULES.format(steps=STEP_DOCS) + "\n\nTHE PLAN:\n" + json.dumps(plan) + "\n\nTHE RUN:\n" + json.dumps({k: v for k, v in failure.items() if k != "frames"})[:9000]}]
    for f in frames[-2:]:
        content.append({"type": "input_image", "image_url": image_url(f, 80)})
    out = cloud.respond(model=config.TEACHER_MODEL, reasoning={"effort": "low"}, input=[{"role": "user", "content": content}])
    return check_plan(extract_json(response_text(out)))


# ---- Running: code holds the memory, the small model answers one question at a time ---------------------------------------

class Eyes:
    """Every question the small model is ever asked. Two looks at a different view of the screen must agree before a read counts."""

    def __init__(self, display: Display):
        self.display = display
        self.glimmer = Glimmer()
        self.questions = 0

    def _ask(self, prompt: str, frame: np.ndarray, shape: dict, tokens: int = 400) -> dict:
        self.questions += 1
        try:
            return self.glimmer.read_json(prompt, frame, shape, max_tokens=tokens)
        except LocalModelError as e:
            raise NeedsHelp(f"the local model gave no usable answer: {e}") from e

    def locate(self, target: str) -> tuple[int, int] | None:
        frame = self.display.shot()
        a = self._ask(f"This is a screenshot. Find exactly this on it: {target}\nGive the middle of it, on a grid from 0 to 1000 across and 0 to 1000 down. If it isn't visible, say found is false.", frame, {"found": "true or false", "x": "0-1000", "y": "0-1000"}, 60)
        if not a.get("found") or a.get("x") is None or a.get("y") is None or str(a.get("found")).lower() == "false":
            return None
        return round(float(a["x"]) * self.display.width / 1000), round(float(a["y"]) * self.display.height / 1000)

    def yes(self, question: str) -> bool:
        frame = self.display.shot()
        a = self._ask(f"This is a screenshot. Answer from what it shows, and nothing else: {question}", frame, {"answer": "true or false"}, 30)
        return str(a.get("answer")).lower() == "true"

    def read_once(self, fields: dict, frame: np.ndarray, where: str = "") -> dict:
        """Descriptions go in the question and the answer slots stay empty: given a description in a slot, the model sometimes copies it back as the answer."""
        rows = isinstance(fields.get("rows"), list)
        spec = fields["rows"][0] if rows else fields
        wanted = "\n".join(f"- {k}: {v}" for k, v in spec.items())
        blank = {k: None for k in spec}
        shape = {"rows": [blank]} if rows else blank
        ask = "Copy every matching row." if rows else "Copy these values."
        return self._ask(f"This is a screenshot. {ask} Copy exactly what the screen shows, and never guess. Use null for anything not visible. {where}\n{wanted}", frame, shape, 900 if rows else 300)

    def read(self, fields: dict, types: dict | None = None) -> dict:
        """Two looks. A value only counts if they match; a third look may settle one split, and otherwise it stops."""
        types = types or {}
        frame = self.display.shot()
        a, b = self.read_once(fields, frame), self.read_once(fields, team.second_look(frame))
        out = {}
        for key in fields:
            kind = types.get(key, "text")
            x, y = team.normal(a.get(key), kind), team.normal(b.get(key), kind)
            if x == y:
                out[key] = a.get(key)
                continue
            c = self.read_once({key: fields[key]}, frame)
            z = team.normal(c.get(key), kind)
            if z in (x, y) and z:
                out[key] = c.get(key)
            else:
                raise NeedsHelp(f"the reads of {key} disagree: {a.get(key)!r}, {b.get(key)!r}, {c.get(key)!r}")
        return out


class PlanRunner:
    def __init__(self, plan: dict, display: Display, emit: Emit | None = None, stop: threading.Event | None = None, max_seconds: float = 600):
        self.plan, self.display = plan, display
        self.emit = emit or (lambda e: None)
        self.stop = stop or threading.Event()
        self.eyes = Eyes(display)
        self.skills = {s["name"]: s for s in plan["skills"]}
        self.trace: list[dict] = []
        self.frames: list[np.ndarray] = []
        self.deadline = time.time() + max_seconds
        self.outputs: dict = {}
        self.writes: list[dict] = []

    def fill(self, text, scope: dict):
        """{name} from what's held in memory. A whole-string {name} keeps its type, so a list stays a list."""
        if not isinstance(text, str):
            return text

        def look(path: str):
            cur = scope
            for part in path.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    raise NeedsHelp(f"the plan asked for {path}, which nothing has provided")
                cur = cur[part]
            return cur
        whole = re.fullmatch(r"\{([\w.]+)\}", text)
        if whole:
            return look(whole[1])
        return re.sub(r"\{([\w.]+)\}", lambda m: str(look(m[1])), text)

    def note(self, step: dict, ok: bool, detail: str = "", t0: float | None = None) -> None:
        entry = {"do": step.get("do"), "what": str(step.get("target") or step.get("question") or step.get("into") or step.get("keys") or step.get("skill") or "")[:120], "ok": ok, "detail": detail[:200], "seconds": round(time.time() - t0, 1) if t0 else 0}
        self.trace.append(entry)
        self.emit({"type": "step", **entry})

    def settle(self) -> None:
        self.display.wait_stable(2.0, quiet=0.3)

    def find(self, target: str, step: dict) -> tuple[int, int]:
        for attempt in range(3):
            spot = self.eyes.locate(target)
            if spot:
                return spot
            time.sleep(1 + attempt)
        raise NeedsHelp(f"can't find: {target}")

    def run_steps(self, steps: list, scope: dict) -> None:
        for step in steps:
            if self.stop.is_set():
                raise NeedsHelp("stopped by a person")
            if time.time() > self.deadline:
                raise NeedsHelp("ran out of time")
            self.frames = (self.frames + [self.display.shot()])[-2:]
            self.do(step, scope)

    def replace_text(self, spot: tuple[int, int], text: str) -> None:
        self.display.click(*spot)
        time.sleep(0.15)
        self.display.press("ctrl+a")
        self.display.press("Delete")
        self.display.type(text)

    def do(self, step: dict, scope: dict) -> None:
        t0 = time.time()
        kind = step["do"]
        d = self.display
        if kind in ("click", "double_click"):
            target = self.fill(step["target"], scope)
            spot = self.find(target, step)
            d.click(*spot, "left", 2 if kind == "double_click" else 1)
            self.settle()
            self.note({**step, "target": target}, True, str(spot), t0)
        elif kind == "type":
            target, text = self.fill(step["target"], scope), str(self.fill(step["text"], scope))
            spot = self.find(target, step)
            for attempt in range(2):
                self.replace_text(spot, text)
                d.wait_stable(0.8, quiet=0.15)
                if step.get("secret") or step.get("no_check"):
                    break
                seen = self.eyes.read_once({"value": f"the text now in: {target}"}, d.shot()).get("value")
                if team.normal(seen) == team.normal(text):
                    break
                if attempt == 1:
                    raise NeedsHelp(f"typed {text!r} into {target}, but it reads back as {seen!r}")
            self.writes.append({"target": target, "text": "(hidden)" if step.get("secret") else text})
            if step.get("enter"):
                d.press("Return")
            self.settle()
            self.note({**step, "target": target}, True, "(hidden)" if step.get("secret") else text, t0)
        elif kind == "choose":
            target, option = self.fill(step["target"], scope), str(self.fill(step["option"], scope))
            d.click(*self.find(target, step))
            time.sleep(0.3)
            d.type(option)
            d.press("Return")
            self.settle()
            seen = self.eyes.read_once({"value": f"the option now chosen in: {target}"}, d.shot()).get("value")
            if option.lower() not in team.normal(seen) and team.normal(seen) not in option.lower():
                raise NeedsHelp(f"chose {option!r} in {target}, but it reads back as {seen!r}")
            self.note({**step, "target": target}, True, option, t0)
        elif kind == "key":
            d.press(str(step["keys"]))
            self.settle()
            self.note(step, True, "", t0)
        elif kind == "wait":
            time.sleep(min(float(step.get("seconds", 1)), 15))
            self.settle()
            self.note(step, True, "", t0)
        elif kind == "scroll":
            spot = self.find(self.fill(step["target"], scope), step) if step.get("target") else (d.width // 2, d.height // 2)
            d.scroll(*spot, 0, int(step.get("dy", 3)))
            self.settle()
            self.note(step, True, "", t0)
        elif kind == "ensure":
            question = self.fill(step["question"], scope)
            ok = self.eyes.yes(question) or (time.sleep(2) or self.settle() or self.eyes.yes(question))
            self.note({**step, "question": question}, ok, "", t0)
            if not ok:
                raise NeedsHelp(f"expected, but not true: {question}")
        elif kind == "dismiss":
            question = self.fill(step["question"], scope)
            hit = self.eyes.yes(question)
            if hit:
                d.click(*self.find(self.fill(step["target"], scope), step))
                self.settle()
            self.note({**step, "question": question}, True, "dismissed" if hit else "not there", t0)
        elif kind == "read":
            fields = {k: self.fill(v, scope) for k, v in step["fields"].items()}
            got = self.eyes.read(fields, step.get("types"))
            scope.setdefault(step["into"], {}).update(got)
            self.outputs[step["into"]] = scope[step["into"]]
            self.note(step, True, json.dumps(got)[:190], t0)
        elif kind == "read_list":
            self.read_list(step, scope, t0)
        elif kind == "compare":
            a, b = str(self.fill(step["a"], scope)), str(self.fill(step["b"], scope))
            how = step.get("kind", "text")
            ok = team.normal(a, how) == team.normal(b, how)
            self.note(step, ok, f"{a} / {b}", t0)
            if not ok:
                raise NeedsHelp(f"these should match and don't: {a!r} and {b!r}")
        elif kind == "if":
            yes = self.eyes.yes(self.fill(step["question"], scope))
            self.note(step, True, "yes" if yes else "no", t0)
            self.run_steps(step.get("then" if yes else "else") or [], scope)
        elif kind == "for_each":
            rows = self.fill(step["list"], scope)
            if not isinstance(rows, list):
                raise NeedsHelp(f"for_each expected a list, got {type(rows).__name__}")
            for row in rows:
                self.run_steps(step["steps"], {**scope, step["as"]: row})
        elif kind == "call":
            inputs = {k: self.fill(v, scope) for k, v in (step.get("with") or {}).items()}
            self.note(step, True, "", t0)
            child = {**scope, **inputs}
            self.run_steps(self.skills[step["skill"]]["steps"], child)
            for k, v in child.items():  # what a skill read stays available to whoever called it
                if k not in scope and k not in inputs:
                    scope[k] = v
        elif kind == "stop_for_person":
            message = str(self.fill(step["message"], scope))
            self.note(step, True, message, t0)
            self.outputs["_stopped_for_person"] = message
            raise StopForPerson(message)
        else:
            raise NeedsHelp(f"unknown step {kind}")

    def read_list(self, step: dict, scope: dict, t0: float) -> None:
        """A list longer than one screen: read a page, scroll, and let code merge rows. Stops once a page adds nothing."""
        item = {k: self.fill(v, scope) for k, v in step["item"].items()}
        where = self.fill(step.get("where") or "", scope)
        first_key = next(iter(item))
        rows: dict[str, dict] = {}
        pages = max(1, int(step.get("max_pages", 6)))
        scroll = int(step.get("scroll", 0))
        shape = {"rows": [{k: v for k, v in item.items()}]}
        for page in range(pages):
            frame = self.display.shot()
            a = self.eyes.read_once(shape, frame, where).get("rows") or []
            b = self.eyes.read_once(shape, team.second_look(frame), where).get("rows") or []
            before = len(rows)
            seen_a = {team.normal(r.get(first_key)): r for r in a if isinstance(r, dict) and r.get(first_key)}
            seen_b = {team.normal(r.get(first_key)): r for r in b if isinstance(r, dict) and r.get(first_key)}
            for name in set(seen_a) | set(seen_b):
                if name not in seen_a or name not in seen_b:
                    if not scroll:
                        raise NeedsHelp(f"one read saw a row the other didn't: {name}")
                    continue  # partly off the screen on this page; the next page settles it
                x, y = seen_a[name], seen_b[name]
                for k in item:
                    if team.normal(x.get(k)) != team.normal(y.get(k)):
                        z = self.eyes.read_once({k: f"{item[k]}, for the row {name}"}, frame).get(k)
                        if team.normal(z) not in (team.normal(x.get(k)), team.normal(y.get(k))) or not z:
                            raise NeedsHelp(f"the reads of {name}: {k} disagree: {x.get(k)!r}, {y.get(k)!r}, {z!r}")
                        x = {**x, k: z}
                if name in rows and any(team.normal(rows[name].get(k)) != team.normal(x.get(k)) for k in item):
                    raise NeedsHelp(f"{name} read differently on two pages")
                rows[name] = x
            if not scroll or (page > 0 and len(rows) == before):
                break
            self.display.scroll(self.display.width // 2, self.display.height // 2, 0, scroll)
            self.settle()
        scope[step["into"]] = list(rows.values())
        self.outputs[step["into"]] = scope[step["into"]]
        self.note(step, True, f"{len(rows)} rows", t0)

    def run(self, skill: str, inputs: dict) -> dict:
        t0 = time.time()
        if skill not in self.skills:
            raise ValueError(f"no skill called {skill}")
        scope = dict(inputs)
        status, reason = "done", ""
        try:
            self.run_steps(self.skills[skill]["steps"], scope)
        except StopForPerson as e:
            status, reason = "stopped_for_person", str(e)
        except NeedsHelp as e:
            status, reason = "needs_help", str(e)
            self.frames = (self.frames + [self.display.shot()])[-2:]
        except (KeyError, TypeError, ValueError, RuntimeError) as e:
            status, reason = "needs_help", f"{type(e).__name__}: {e}"
            self.frames = (self.frames + [self.display.shot()])[-2:]
        return {"status": status, "reason": reason, "outputs": self.outputs, "seconds": round(time.time() - t0, 1), "questions": self.eyes.questions, "steps": len(self.trace), "trace": self.trace, "writes": self.writes, "scope": {k: v for k, v in scope.items() if isinstance(v, (str, int, float, list, dict))}}


class StopForPerson(Exception):
    pass


# ---- A library of compiled interfaces, and the whole lesson in one call -------------------------------------------------------

def _plans_dirs():
    return [config.HOME / "uiteam", config.REPO / "plans" / "ui"]


def saved_plans() -> dict[str, dict]:
    """Plans learned on this machine, then the ones the repo ships with."""
    out: dict[str, dict] = {}
    for f in sorted((config.HOME / "uiteam").glob("*/plan.json")):
        try:
            out.setdefault(f.parent.name, {**check_plan(json.loads(f.read_text())), "id": f.parent.name})
        except ValueError:
            continue
    folder = config.REPO / "plans" / "ui"
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            out.setdefault(f.stem, {**check_plan(json.loads(f.read_text())), "id": f.stem})
        except ValueError:
            continue
    return out


def plan_brief(p: dict) -> dict:
    return {"id": p["id"], "app": p.get("app") or p["id"], "how": p.get("how_it_behaves", ""), "target": p.get("target"), "cost": p.get("compile_usd"), "repairs": p.get("repairs", 0), "samples": p.get("samples") or {},
            "skills": [{"name": s["name"], "does": s.get("does", ""), "inputs": s.get("inputs") or {}, "size": count_steps(s["steps"])} for s in p["skills"]], "jobs": p.get("jobs") or {}}


def count_steps(steps: list) -> int:
    return sum(1 + count_steps(s.get("steps") or []) + count_steps(s.get("then") or []) + count_steps(s.get("else") or []) for s in steps)


def teach(app_id: str, spec: dict, goal: str, inputs: dict, display: Display, target, emit: Emit, stop: threading.Event, repairs: int = 4, limit_usd: float = 4.0) -> dict:
    """Explore, compile, prove, repair. Passing here means the plan finished and a separate model, shown only the final screen, agrees."""
    from .teacher import judge_final_screen

    folder = config.HOME / "uiteam" / app_id
    folder.mkdir(parents=True, exist_ok=True)
    meter = Meter()
    full_goal = goal + (f"\nInputs: {json.dumps(inputs)}" if inputs else "")
    emit({"type": "stage", "stage": "explore", "text": "Muse Spark is using the interface for the first time."})
    record = explore(display, target, full_goal, meter, limit_usd=min(1.0, limit_usd), emit=lambda e: emit({**e, "usd": round(meter.usd, 4)}), stop=stop)
    emit({"type": "stage", "stage": "compile", "text": "Muse Wonder is writing the plan.", "usd": round(meter.usd, 4)})
    note = f"Name the job's skill run_job, with these inputs: {json.dumps(sorted(inputs))}." if inputs else "Name the job's skill run_job."
    plan = compile_plan([record], note, meter=meter, limit_usd=min(1.5, limit_usd))
    plan.update(target=spec, samples={"run_job": inputs}, repairs=0, goal=goal)
    emit({"type": "plan", "plan": plan_brief({**plan, "id": app_id}), "usd": round(meter.usd, 4)})
    frames: list[np.ndarray] = []
    for attempt in range(repairs + 1):
        if stop.is_set():
            break
        emit({"type": "stage", "stage": "prove", "text": "Muse Glimmer is running the plan on its own.", "usd": round(meter.usd, 4)})
        target.reset()
        runner = PlanRunner(plan, display, emit=emit, stop=stop)
        result = runner.run("run_job" if "run_job" in runner.skills else plan["skills"][-1]["name"], inputs)
        frames = runner.frames
        verdict = {"achieved": False, "why": result["reason"]}
        if result["status"] in ("done", "stopped_for_person"):
            verdict = judge_final_screen(Cloud(meter=meter, limit_usd=limit_usd), full_goal, display.shot(), summary=json.dumps(result["outputs"])[:800])
        emit({"type": "proof", "attempt": attempt + 1, "status": result["status"], "achieved": verdict["achieved"], "why": verdict["why"], "seconds": result["seconds"], "questions": result["questions"], "usd": round(meter.usd, 4)})
        if verdict["achieved"]:
            plan.update(compile_usd=round(meter.usd, 4))
            (folder / "plan.json").write_text(json.dumps(plan, indent=1))
            emit({"type": "learned", "id": app_id, "usd": round(meter.usd, 4)})
            return {"ok": True, "plan": plan, "usd": meter.usd}
        if attempt == repairs or meter.usd >= limit_usd:
            break
        emit({"type": "stage", "stage": "repair", "text": "Muse Wonder is fixing the plan from what went wrong.", "usd": round(meter.usd, 4)})
        failure = {"status": result["status"], "reason": result["reason"], "judge": verdict["why"], "trace": result["trace"][-40:]}
        try:
            plan = {**repair_plan(plan, failure, frames, meter=meter), "target": spec, "samples": {"run_job": inputs}, "goal": goal, "repairs": attempt + 1}
        except (ValueError, CloudError) as e:
            emit({"type": "log", "text": f"The repair didn't work: {e}"[:300]})
    emit({"type": "not_learned", "why": "It didn't pass within its repair limit, so nothing was saved.", "usd": round(meter.usd, 4)})
    return {"ok": False, "usd": meter.usd}
