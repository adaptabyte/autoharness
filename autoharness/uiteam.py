"""Any interface, compiled into a team a small model can run.

explore():  a capable model uses the interface through computer use, and everything it sees and does is recorded.
compile_plan(): the strongest model turns that record into a plan. A plan is data, never code: general skills made of small steps.
PlanRunner: code walks the plan and holds all the memory. The small model is only ever asked one narrow question about one
screen: where is this, is this true, what does this say. Every write is read back. Anything that doesn't check out stops the
run and hands off, so a run ends either verified or asking for help, and never quietly wrong.
"""
from __future__ import annotations

import datetime
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

def explore(display: Display, target, goal: str, meter: Meter, frames: list | None = None, limit_usd: float = 0.6, max_turns: int = 45, emit: Emit | None = None, stop: threading.Event | None = None, docs: str = "") -> dict:
    """Muse Spark does the job once through computer use. The record is what the compiler learns from. docs is Wonder's
    brief on the app's docs, if the user gave any."""
    from .docs import FOR_SPARK
    from .teacher import Teacher

    emit = emit or (lambda e: None)
    stop = stop or threading.Event()
    cloud = Cloud(meter=meter, limit_usd=limit_usd)
    helper = Teacher.__new__(Teacher)
    helper.display, helper.target, helper.emit, helper.meter, helper.approve = display, target, emit, meter, None
    target.reset()
    frame = display.shot()
    record: list[dict] = [{"i": 0, "image": frame, "said": "", "did": "the app as it first appears"}]
    told = FOR_SPARK.format(brief=docs) if docs else ""
    items = [{"role": "user", "content": [{"type": "input_text", "text": f"Goal: {goal}\nScreen size: {display.width}x{display.height}.{told}"}, {"type": "input_image", "image_url": image_url(frame)}]}]
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
            items = [{"role": "user", "content": [{"type": "input_text", "text": f"Goal: {goal}\nScreen size: {display.width}x{display.height}. You were already working on this and the earlier conversation had to end. Carry on from the screen as it is now.{told}"}, {"type": "input_image", "image_url": image_url(display.shot())}]}]
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
{"do":"ensure","question":"Is the results table showing, with a row for {last}?","why":"..."}  a yes/no about the current screen. A no stops and asks for help, so use these after anything that changes the screen, before you rely on it.
{"do":"dismiss","question":"Is a popup asking about product registration open?","target":"the Ask Again Later button"}  clicks only if the question is yes. Use it for things that appear only sometimes.
{"do":"read","into":"facts","fields":{"born":"the date of birth","account":"the ID in parentheses after the name"},"types":{"born":"date","account":"id"}}  reads values off the current screen twice, independently. Types: id, date, number, money, name, code, text. If the two reads disagree it stops.
{"do":"read_list","into":"rows","item":{"item_name":"...","start":"..."},"where":"which rows count and which don't","scroll":3,"max_pages":6}  reads a list that may scroll, page by page, merging rows in code, until a page adds nothing new. Set "scroll":0 if it fits on one screen.
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
- Make skills general, with inputs. No value from the record may be baked in: names, dates and numbers must be inputs. Prefer several small reusable skills (log_in, open_record, read_record, edit_field) that one skill per job composes with "call".
- Add a "dismiss" for every popup or interruption seen in the record, wherever it can appear.
- After anything that changes the screen, add an "ensure" that would catch going to the wrong place. Before reading or changing a record, confirm with "read" and "compare" that it's the right one.
- Keep each target description unmistakable on a single screenshot: its label, its kind and where it is, and how to tell it from look-alikes.
- Each read names only what's visible on that one screen; scroll first if needed. Say how to tell a value from look-alikes beside it.
- Where a job could be wrong without an error showing, read the result back at the end and compare.
- Anything irreversible that a person must do, such as signing or submitting, gets stop_for_person. Never go past it.

Steps available, and no others:
{steps}
Reply with only one JSON object, no other text:
{{"app":"name","how_it_behaves":"a few sentences a repairer would need","skills":[{{"name":"snake_case","does":"one plain sentence","inputs":{{"name":"what it is"}},"outputs":["keys of values it reads, to report at the end"],"steps":[...]}}],"jobs":{{"job_name":"skill to run for this kind of request"}},"defaults":{{"input_name":"value from the record, only if asked for below"}}}}"""
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
    cloud = Cloud(meter=meter, limit_usd=meter.usd + limit_usd)  # the limit is per repair; the meter counts the whole lesson
    content: list = [{"type": "input_text", "text": REPAIR_RULES.format(steps=STEP_DOCS) + "\n\nTHE PLAN:\n" + json.dumps(plan) + "\n\nTHE RUN:\n" + json.dumps({k: v for k, v in failure.items() if k != "frames"})[:9000]}]
    for f in frames[-2:]:
        content.append({"type": "input_image", "image_url": image_url(f, 80)})
    out = cloud.respond(model=config.TEACHER_MODEL, reasoning={"effort": "low"}, input=[{"role": "user", "content": content}])
    return check_plan(extract_json(response_text(out)))


# ---- Running: code holds the memory, the small model answers one question at a time ---------------------------------------

def enlarge(frame: np.ndarray, factor: float = 1.5) -> np.ndarray:
    """Small interface text is where the small model slips, reading 'Winterton' as 'Wintertor'. Bigger pixels fix most of that."""
    from PIL import Image

    im = Image.fromarray(frame)
    return np.asarray(im.resize((round(im.width * factor), round(im.height * factor)), Image.LANCZOS))


def crop_around(frame: np.ndarray, spot: tuple[int, int], width: int = 700, height: int = 110, factor: float = 3.0) -> np.ndarray:
    """Just the box that was typed into. Code knows exactly where it clicked, so the check needn't search the whole screen."""
    h, w = frame.shape[:2]
    x0, y0 = max(0, spot[0] - width // 2), max(0, spot[1] - height // 2)
    return enlarge(frame[y0:min(h, y0 + height), x0:min(w, x0 + width)], factor)


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
        """The plain screen first, because it's quick. A closer look only if that finds nothing."""
        frame = self.display.shot()
        for view in (frame, enlarge(frame)):
            a = self._ask(f"This is a screenshot. Find exactly this on it: {target}\nGive the middle of it, on a grid from 0 to 1000 across and 0 to 1000 down. If it isn't visible, say found is false.", view, {"found": "true or false", "x": "0-1000", "y": "0-1000"}, 60)
            if a.get("found") and str(a.get("found")).lower() != "false" and a.get("x") is not None and a.get("y") is not None:
                return round(float(a["x"]) * self.display.width / 1000), round(float(a["y"]) * self.display.height / 1000)
        return None

    def yes(self, question: str, closer: bool = False) -> bool:
        """closer=True gets a second, larger look before answering no. Used where a no would stop the run; a popup that isn't there doesn't need it."""
        frame = self.display.shot()
        for view in (frame, enlarge(frame)) if closer else (frame,):
            a = self._ask(f"This is a screenshot. Answer from what it shows, and nothing else: {question}", view, {"answer": "true or false"}, 30)
            if str(a.get("answer")).lower() == "true":
                return True
        return False

    def read_box(self, frame: np.ndarray, spot: tuple[int, int], target: str):
        """What a box holds, from a close-up of where it was clicked."""
        return self._ask(f"This is a close-up of part of a screen, around this box: {target}\nCopy exactly the text inside that box, character by character. If it's empty, use null.", crop_around(frame, spot), {"value": "..."}, 80).get("value")

    def read_once(self, fields: dict, frame: np.ndarray, where: str = "") -> dict:
        """Descriptions go in the question and the answer slots stay empty: given a description in a slot, the model sometimes copies it back as the answer."""
        rows = isinstance(fields.get("rows"), list)
        spec = fields["rows"][0] if rows else fields
        wanted = "\n".join(f"- {k}: {v}" for k, v in spec.items())
        blank = {k: "..." for k in spec}  # measured: an empty slot gets copied back as "nothing" on one-field reads, 11 times in 15; "..." never was
        shape = {"rows": [blank]} if rows else blank
        ask = "Copy every matching row." if rows else "Copy these values."
        return self._ask(f"This is a screenshot. {ask} Copy exactly what the screen shows, and never guess. Use null for anything not visible. {where}\n{wanted}", frame, shape, 900 if rows else 300)

    def read(self, fields: dict, types: dict | None = None) -> dict:
        """Two looks. A value only counts if they match; a third look may settle one split, and otherwise it stops."""
        types = types or {}
        frame = enlarge(self.display.shot())
        a, b = self.read_once(fields, frame), self.read_once(fields, team.second_look(frame))
        if any(not team.normal(a.get(k), types.get(k, "text")) and not team.normal(b.get(k), types.get(k, "text")) for k in fields):
            # Both reads came back blank on something. Often the page was still drawing, and both looked at the same half-drawn frame, so look at a new one.
            time.sleep(2)
            self.display.wait_stable(2.0, quiet=0.4)
            frame = enlarge(self.display.shot())
            a, b = self.read_once(fields, frame), self.read_once(fields, team.second_look(frame))
        out = {}
        for key in fields:
            kind = types.get(key, "text")
            x, y = team.normal(a.get(key), kind), team.normal(b.get(key), kind)
            if x == y:
                out[key] = a.get(key)
                continue
            c = self.read_once({key: fields[key]}, enlarge(frame, 1.5))
            z = team.normal(c.get(key), kind)
            if z in (x, y) and z:
                out[key] = c.get(key)
            else:
                raise NeedsHelp(f"the reads of {key} disagree: {a.get(key)!r}, {b.get(key)!r}, {c.get(key)!r}")
        return out


def close_enough(a: str, b: str, limit: int = 2) -> bool:
    """Within a couple of letters: small enough to be a misread, so it's worth one closer look. Anything further is a real mismatch."""
    if abs(len(a) - len(b)) > limit:
        return False
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(new[j - 1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = new
    return row[-1] <= limit


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
        self.last_read: tuple[dict, str] | None = None

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
                frame = d.shot()
                seen = self.eyes.read_box(frame, spot, target)
                if team.normal(seen) != team.normal(text):  # the close-up can miss, so check the whole screen before retyping
                    seen = self.eyes.read_once({"value": f"the text now in: {target}"}, enlarge(frame)).get("value") or seen
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
            spot = self.find(target, step)
            d.click(*spot)
            time.sleep(0.3)
            d.type(option)
            d.press("Return")
            self.settle()
            seen = self.eyes.read_box(d.shot(), spot, target)
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
            ok = self.eyes.yes(question, closer=True) or (time.sleep(2) or self.settle() or self.eyes.yes(question, closer=True))
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
            self.last_read = (step, step["into"])
            self.note(step, True, json.dumps(got)[:190], t0)
        elif kind == "read_list":
            self.read_list(step, scope, t0)
        elif kind == "compare":
            a, b = str(self.fill(step["a"], scope)), str(self.fill(step["b"], scope))
            how = step.get("kind", "text")
            ok = team.normal(a, how) == team.normal(b, how)
            if not ok and self.last_read and close_enough(team.normal(a, how), team.normal(b, how)):
                # Possibly a one-letter misread rather than the wrong record. Look again much closer, without saying what's expected.
                read_step, into = self.last_read
                fields = {k: self.fill(v, scope) for k, v in read_step["fields"].items()}
                frame = enlarge(self.display.shot(), 2.5)
                again = self.eyes.read_once(fields, frame)
                again2 = self.eyes.read_once(fields, team.second_look(frame))
                kinds = read_step.get("types") or {}
                settled = {k: again.get(k) for k in fields if team.normal(again.get(k), kinds.get(k, "text")) == team.normal(again2.get(k), kinds.get(k, "text"))}
                scope.setdefault(into, {}).update(settled)
                a = str(self.fill(step["a"], scope))
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
            collected: dict[str, list] = {}
            for row in rows:
                child = {**scope, step["as"]: row}
                self.run_steps(step["steps"], child)
                for key, value in child.items():  # what was read for each row is kept with that row, not overwritten by the next
                    if key not in scope and key != step["as"] and isinstance(value, dict):
                        collected.setdefault(key, []).append({**(row if isinstance(row, dict) else {"item": row}), **value})
            for key, values in collected.items():
                scope[key] = values
                self.outputs[key] = values
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
            frame = enlarge(self.display.shot())
            a = self.eyes.read_once(shape, frame, where).get("rows") or []
            b = self.eyes.read_once(shape, team.second_look(frame), where).get("rows") or []
            if page == 0 and not a and not b:  # the page may still be drawing
                time.sleep(2)
                self.display.wait_stable(2.0, quiet=0.4)
                frame = enlarge(self.display.shot())
                a = self.eyes.read_once(shape, frame, where).get("rows") or []
                b = self.eyes.read_once(shape, team.second_look(frame), where).get("rows") or []
            before = len(rows)
            seen_a = {team.normal(r.get(first_key)): r for r in a if isinstance(r, dict) and r.get(first_key)}
            seen_b = {team.normal(r.get(first_key)): r for r in b if isinstance(r, dict) and r.get(first_key)}
            third = None
            for name in set(seen_a) | set(seen_b):
                if name not in seen_a or name not in seen_b:
                    if third is None:  # one read saw a row the other didn't: a third look settles whether it's there
                        got = self.eyes.read_once(shape, enlarge(frame, 1.4), where).get("rows") or []
                        third = {team.normal(r.get(first_key)): r for r in got if isinstance(r, dict) and r.get(first_key)}
                    if name not in third:
                        if not scroll:
                            raise NeedsHelp(f"one read saw a row the others didn't: {name}")
                        continue  # partly off the screen on this page; the next page settles it
                    if name not in seen_a:
                        seen_a[name] = third[name]
                    else:
                        seen_b[name] = third[name]
                x, y = seen_a[name], seen_b[name]
                for k in item:
                    if team.normal(x.get(k)) != team.normal(y.get(k)):
                        z = self.eyes.read_once({k: f"{item[k]}, for the row {name}"}, frame).get(k)
                        if team.normal(z) not in (team.normal(x.get(k)), team.normal(y.get(k))) or not z:
                            raise NeedsHelp(f"the reads of {name}: {k} disagree: {x.get(k)!r}, {y.get(k)!r}, {z!r}")
                        x = {**x, k: z}
                if name in rows:
                    # A row cut off at the edge of one page is blank there, not different. Only two real values can contradict.
                    clash = [k for k in item if team.normal(rows[name].get(k)) and team.normal(x.get(k)) and team.normal(rows[name].get(k)) != team.normal(x.get(k))]
                    if clash:
                        raise NeedsHelp(f"{name} read differently on two pages: {clash[0]} is {rows[name].get(clash[0])!r} and {x.get(clash[0])!r}")
                    x = {k: x.get(k) if team.normal(x.get(k)) else rows[name].get(k) for k in item}
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


WAYS = """Autoharness can learn a job in an app in one of two ways.

PLAN: the same steps every time, with only the inputs changing. Clicks, typing, reading values off the screen, yes/no checks, \
simple if/else and going through a list. Examples: look up an order, fill in a form, export a report, update a record, \
buy an item in a game's shop, read a character's stats.

PROGRAM: code that has to decide what to do next from what is on the screen, over and over, until a goal is met. Examples: \
win a game, solve a puzzle, play a turn-based game, keep sorting items until none are left when the rule \
depends on what each one shows.

App: {address}
Job: {goal}

Which way fits this job? If the same steps would work every time, it's a plan. Reply with only JSON: {{"way": "plan" or "program", \
"why": "one short plain sentence for the user", "job": "a short snake_case name for the job, like read_order or win_game", \
"app": "the app's name in one or two words, from the job or the address, such as the game's title or the site's name"}}"""


def choose_way(address: str, goal: str, meter: Meter, docs: dict | None = None) -> dict:
    """Spark reads the job, not the screen, and picks plan or program. It costs about a tenth of a cent. Wonder's brief on
    the app's docs, if there is one, says how the app works, which helps tell a game from a form."""
    told = " ".join([str((docs or {}).get("about") or ""), *[str(r) for r in (docs or {}).get("rules") or []][:6]]).strip()
    out = Cloud(meter=meter, limit_usd=0.05).respond(model=config.SPARK_MODEL, reasoning={"effort": "low"}, input=[
        {"role": "user", "content": [{"type": "input_text", "text": WAYS.format(address=address, goal=goal) + (f"\n\nWhat the app's docs say about it: {told}" if told else "")}]}])
    try:
        a = extract_json(response_text(out))
    except ValueError:
        a = {}
    way = "program" if str(a.get("way", "")).lower().strip() == "program" else "plan"
    job = re.sub(r"[^a-z0-9_]+", "_", str(a.get("job") or "").lower()).strip("_")[:40] or ("win" if way == "program" else "do_job")
    return {"way": way, "why": str(a.get("why") or "")[:200], "job": job, "app": str(a.get("app") or "").strip()[:40]}


PROGRAM_NOTE = ("Runs on the user's own computer: a program written for this app does the job, asking a small local model "
                "only when it needs to look, and checks the result. It takes seconds to minutes, and either finishes or stops and says why.")


def program_interfaces() -> dict[str, dict]:
    """Programs learned through `autoharness teach`, for jobs that decide each move from the screen, like a game. Each is
    offered like a plan with one job, so an agent calls a program and a plan the same way."""
    from . import library
    out: dict[str, dict] = {}
    for pkg in library.all_packages():
        m = pkg.manifest
        iface, job = m.get("tool_id"), m.get("tool_job")
        if m.get("status") != "ready" or not iface or not job:
            continue
        params = m.get("params") or {}
        out.setdefault(iface, {"id": iface, "kind": "program", "package": pkg.id, "app": m.get("name") or iface,
                               "how_it_behaves": m.get("how", ""), "target": m.get("target"), "compile_usd": m.get("teach_usd"),
                               "goal": m.get("goal", ""), "jobs": {job: job}, "samples": {job: params},
                               "skills": [{"name": job, "does": m.get("goal", ""), "inputs": {k: k.replace("_", " ") for k in params},
                                           "outputs": [], "steps": []}]})
    return out


def saved_plans() -> dict[str, dict]:
    """Plans learned on this machine, then the ones the repo ships with, then programs learned through the same door."""
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
    for iface, p in program_interfaces().items():
        out.setdefault(iface, p)
    return out


def plan_brief(p: dict) -> dict:
    return {"id": p["id"], "kind": p.get("kind", "plan"), "app": p.get("app") or p["id"], "how": p.get("how_it_behaves", ""), "target": p.get("target"), "cost": p.get("compile_usd"), "repairs": p.get("repairs", 0), "samples": p.get("samples") or {}, "swarm": len(p.get("swarm_inputs") or []),
            "skills": [{"name": s["name"], "does": s.get("does", ""), "inputs": s.get("inputs") or {}, "size": count_steps(s["steps"])} for s in p["skills"]], "jobs": p.get("jobs") or {},
            "tools": [{"name": t["name"], "inputs": list(t["inputSchema"]["properties"])} for t in plan_tools(p, kept_logins(p["id"]))], "kept": sorted(kept_logins(p["id"]))}


TOOL_NOTE = ("Runs on the user's own computer: a small local model operates the real interface, one narrow question per screen, "
             "and code checks every step. It takes seconds to minutes. It either finishes verified, stops for a person "
             "(such as a signature), or stops and says why.")


def _schema(sample) -> dict:
    if isinstance(sample, list):
        return {"type": "array", "items": _schema(sample[0]) if sample else {}}
    if isinstance(sample, dict):
        return {"type": "object", "properties": {k: _schema(v) for k, v in sample.items()}, "required": list(sample)}
    if isinstance(sample, bool):
        return {"type": "boolean"}
    if isinstance(sample, int):
        return {"type": ["integer", "string"]}
    if isinstance(sample, float):
        return {"type": ["number", "string"]}
    return {"type": "string"}


def _whole(value):
    """30.0 from a caller means 30. Typed into a box, "30.0" is a different, often refused, answer."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_whole(v) for v in value]
    if isinstance(value, dict):
        return {k: _whole(v) for k, v in value.items()}
    return value


def kept_logins(app_id: str) -> dict:
    """Values kept on this computer for an interface, like its login, in ~/.autoharness/logins.json. They're filled in at run time
    and left out of the tools, so a calling model never sees them."""
    try:
        return {str(k): v for k, v in (json.loads((config.HOME / "logins.json").read_text()).get(app_id) or {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def keep_login(app_id: str, values: dict) -> None:
    """Saves an interface's login on this computer only, readable by this user alone."""
    if not values:
        return
    file = config.HOME / "logins.json"
    try:
        saved = json.loads(file.read_text())
    except (OSError, ValueError):
        saved = {}
    saved[app_id] = {**(saved.get(app_id) or {}), **{str(k): v for k, v in values.items()}}
    file.parent.mkdir(parents=True, exist_ok=True)
    file.touch(mode=0o600, exist_ok=True)
    file.chmod(0o600)
    file.write_text(json.dumps(saved, indent=1))


def plan_tools(plan: dict, kept: dict | None = None) -> list[dict]:
    """A compiled interface, offered to other models as tools. Each whole job is one tool; the smaller skills it's built from
    aren't offered, so a caller can't start halfway through a job. Input types come from the samples the plan was proven on."""
    by = {s["name"]: s for s in plan["skills"]}
    names = [n for n in dict.fromkeys((plan.get("jobs") or {}).values()) if n in by] or list(by)
    tools = []
    for name in names:
        skill, sample = by[name], (plan.get("samples") or {}).get(name) or {}
        props = {k: {**_schema(sample.get(k, "")), "description": str(text)} for k, text in (skill.get("inputs") or {}).items() if k not in (kept or {})}
        tools.append({"name": name, "title": f"{plan.get('app') or plan.get('id')}: {name.replace('_', ' ')}",
                      "description": f"{skill.get('does', '').strip()} {PROGRAM_NOTE if plan.get('kind') == 'program' else TOOL_NOTE}".strip(),
                      "inputSchema": {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}})
    return tools


def check_tool_call(plan: dict, name: str, inputs, kept: dict | None = None) -> dict:
    """Refuses a call before anything is opened: an unknown job, a missing input or an unexpected one. A plan never fills a gap
    with a guess. Returns the inputs for the run, with the values kept on this computer added."""
    tools = plan_tools(plan, kept)
    tool = next((t for t in tools if t["name"] == name), None)
    if not tool:
        raise ValueError(f"{plan.get('app') or plan.get('id')} has no job called {name!r}; it has {', '.join(t['name'] for t in tools)}")
    if not isinstance(inputs, dict):
        raise ValueError("arguments must be an object")
    props = tool["inputSchema"]["properties"]
    missing = [k for k in props if inputs.get(k) in (None, "")]
    extra = [k for k in inputs if k not in props]
    if missing or extra:
        raise ValueError("; ".join(filter(None, [missing and f"missing: {', '.join(missing)}", extra and f"not inputs of this job: {', '.join(extra)}"])))
    for k, v in inputs.items():
        want = props[k]["type"]
        if want == "array" and not isinstance(v, list) or want == "object" and not isinstance(v, dict) or want == "string" and isinstance(v, (list, dict)):
            raise ValueError(f"{k} should be {'a list' if want == 'array' else 'an object' if want == 'object' else 'text'}")
    needed = set((next(s for s in plan["skills"] if s["name"] == name).get("inputs") or {}))
    return {**_whole(inputs), **{k: v for k, v in (kept or {}).items() if k in needed}}


def count_steps(steps: list) -> int:
    return sum(1 + count_steps(s.get("steps") or []) + count_steps(s.get("then") or []) + count_steps(s.get("else") or []) for s in steps)


def main_job(plan: dict) -> str:
    """The skill that does the whole job: the one the plan lists under jobs, or else its last skill."""
    names = {s["name"] for s in plan["skills"]}
    return next((v for v in (plan.get("jobs") or {}).values() if v in names), plan["skills"][-1]["name"])


def new_plan_id(app_name: str, fallback: str) -> str:
    """A readable id from the interface's own name, like django-administration, that never overwrites a plan already learned."""
    base = re.sub(r"[^a-z0-9]+", "-", app_name.lower()).strip("-")[:32].strip("-") or fallback
    taken = set(saved_plans())
    return next(c for c in [base] + [f"{base}-{n}" for n in range(2, 999)] if c not in taken)


def without_login(text: str, login: dict) -> str:
    """The job as it's kept in the plan, with any login value replaced by its name, so a saved plan never holds a password."""
    for key, value in sorted(login.items(), key=lambda kv: -len(str(kv[1]))):
        if str(value).strip():
            text = text.replace(str(value), "{" + str(key) + "}")
    return text


def teach_program(spec: dict, goal: str, inputs: dict, display: Display, target, emit: Emit, stop: threading.Event, chosen: dict,
                  name: str | None = None, approve=None, limit_usd: float = 4.0, docs: str = "") -> dict:
    """Program mode, through the same door as a plan: Spark explores, Wonder writes a program, and it has to pass its trials
    on its own before it's offered as a tool."""
    from . import library
    from .teacher import Teacher

    app = name or chosen.get("app") or str(spec.get("name") or "app")
    pkg = library.create(app, goal, spec)
    manifest = Teacher(pkg, display, target, emit, stop, limit_usd=limit_usd, sample_params=inputs or None, approve=approve, docs=docs).teach()
    usd = float(manifest.get("teach_usd") or 0)
    understanding = pkg.path / "teach" / "understanding.md"
    notes = "\n\n".join(x for x in ((understanding.read_text() if understanding.exists() else ""), str(manifest.get("how") or "")) if x.strip())
    if manifest.get("status") != "ready":
        why = f"{str(manifest.get('failure') or 'it did not pass its trials').rstrip('.')}."
        emit({"type": "not_learned", "why": f"{why} It isn't offered as a tool.", "usd": usd})
        return {"ok": False, "usd": usd, "notes": notes, "outcome": f"not learned: {why}", "app": app}
    iface = new_plan_id(name or app, "app")
    pkg.update(tool_id=iface, tool_job=chosen["job"], params=inputs or {})
    notes += "\n\n" + proven_notes(pkg)
    emit({"type": "plan", "plan": plan_brief(program_interfaces()[iface]), "usd": usd})
    emit({"type": "learned", "id": iface, "usd": usd, "verified": manifest.get("verified")})
    return {"ok": True, "usd": usd, "notes": notes, "app": app,
            "outcome": f"learned: a program written from this passed {manifest.get('verified')} runs on its own, {datetime.date.today().isoformat()}"}


def teach(app_id: str, spec: dict, goal: str, inputs: dict, display: Display, target, emit: Emit, stop: threading.Event, repairs: int = 4, limit_usd: float = 4.0, name: str | None = None, docs: str = "") -> dict:
    """Explore, compile, prove, repair. Passing here means the plan finished and a separate model, shown only the final screen, agrees."""
    from .teacher import KEPT_SCREEN_NOTE, judge_final_screen, kept_screen

    meter = Meter()
    full_goal = goal + (f"\nInputs: {json.dumps(inputs)}" if inputs else "") + (KEPT_SCREEN_NOTE if kept_screen(spec) else "")
    emit({"type": "stage", "stage": "explore", "text": "Muse Spark is using the interface for the first time."})
    record = explore(display, target, full_goal, meter, limit_usd=min(1.0, limit_usd), emit=lambda e: emit({**e, "usd": round(meter.usd, 4)}), stop=stop, docs=docs)
    emit({"type": "stage", "stage": "compile", "text": "Muse Wonder is writing the plan.", "usd": round(meter.usd, 4)})
    note = ("Give the skill that does the whole job a short snake_case name another program could call it by, like read_order or ship_order, and list it in jobs under that same name. "
            "Every value a run needs that could change, including any login, name or number stated in the job, must be an input used as {name}, "
            'and must also appear with the value from this job in a top-level "defaults" object in your reply, so a run with no other inputs still works. '
            'The one exception is a login: put its values, like username and password, in a top-level "login" object instead of "defaults". '
            "A login is kept on this computer and never shown to programs that call the job.")
    if docs:
        from .docs import FOR_WONDER
        note += FOR_WONDER.format(brief=docs)
    plan = compile_plan([record], note, meter=meter, limit_usd=min(1.5, limit_usd))
    login = plan.pop("login", None)
    login = {str(k): v for k, v in login.items()} if isinstance(login, dict) else {}
    inputs = {**(plan.get("defaults") or {}), **login, **inputs}
    job = main_job(plan)
    goal = without_login(goal, login)
    plan.update(target=spec, samples={job: {k: v for k, v in inputs.items() if k not in login}}, jobs={job: job}, repairs=0, goal=goal)
    app_id = new_plan_id(name or plan.get("app") or "", app_id)
    folder = config.HOME / "uiteam" / app_id
    emit({"type": "plan", "plan": plan_brief({**plan, "id": app_id}), "usd": round(meter.usd, 4)})
    frames: list[np.ndarray] = []
    last_reason = None
    for attempt in range(repairs + 1):
        if stop.is_set():
            break
        emit({"type": "stage", "stage": "prove", "text": "Muse Glimmer is running the plan on its own.", "usd": round(meter.usd, 4)})
        start = target.reset()
        runner = PlanRunner(plan, display, emit=emit, stop=stop)
        result = runner.run(main_job(plan), inputs)
        frames = runner.frames
        verdict = {"achieved": False, "why": result["reason"]}
        if result["status"] in ("done", "stopped_for_person"):
            verdict = judge_final_screen(Cloud(meter=meter, limit_usd=limit_usd), full_goal, display.shot(), summary=json.dumps(result["outputs"])[:800],
                                         start=start if kept_screen(spec) else None)
        emit({"type": "proof", "attempt": attempt + 1, "status": result["status"], "achieved": verdict["achieved"], "why": verdict["why"], "seconds": result["seconds"], "questions": result["questions"], "usd": round(meter.usd, 4)})
        if verdict["achieved"]:
            plan.update(compile_usd=round(meter.usd, 4))
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "plan.json").write_text(json.dumps(plan, indent=1))
            if docs:
                (folder / "docs.md").write_text(docs)
            keep_login(app_id, login)
            emit({"type": "learned", "id": app_id, "usd": round(meter.usd, 4)})
            return {"ok": True, "plan": plan, "usd": meter.usd, "notes": plan_notes(plan, record), "app": plan.get("app") or app_id,
                    "private": [*map(str, login.values()), *map(str, inputs.values())],
                    "outcome": f"learned: a plan written from this passed its proof run on its own, {datetime.date.today().isoformat()}"}
        if attempt == repairs or meter.usd >= limit_usd or result["reason"] == last_reason:
            break  # the same failure twice means repairs aren't reaching the problem, so stop spending
        last_reason = result["reason"]
        emit({"type": "stage", "stage": "repair", "text": "Muse Wonder is fixing the plan from what went wrong.", "usd": round(meter.usd, 4)})
        failure = {"status": result["status"], "reason": result["reason"], "judge": verdict["why"], "trace": result["trace"][-40:]}
        try:
            fixed = repair_plan(plan, failure, frames, meter=meter)
            inputs = {**(fixed.get("defaults") or {}), **inputs}
            job = main_job(fixed)
            fixed.pop("login", None)
            plan = {**fixed, "target": spec, "samples": {job: {k: v for k, v in inputs.items() if k not in login}}, "jobs": {job: job}, "goal": goal, "repairs": attempt + 1}
        except (ValueError, CloudError) as e:
            emit({"type": "log", "text": f"The repair didn't work: {e}"[:300]})
    emit({"type": "not_learned", "why": "It didn't pass within its repair limit, so nothing was saved.", "usd": round(meter.usd, 4)})
    return {"ok": False, "usd": meter.usd, "notes": plan_notes(plan, record), "app": plan.get("app") or app_id,
            "private": [*map(str, login.values()), *map(str, inputs.values())], "outcome": "not learned: the plan didn't pass its proof runs"}


def proven_notes(pkg) -> str:
    """What the passing program proved, for the app's guide: what the judge saw at the end of each run, and the program
    itself, since every control and check in it worked on the real screen."""
    verdicts = []
    for line in (pkg.path / "runs.jsonl").read_text().splitlines() if (pkg.path / "runs.jsonl").exists() else []:
        try:
            run = json.loads(line)
        except ValueError:
            continue
        if run.get("kind") in ("verify", "interface") and run.get("status") == "done":
            verdicts.append(str((run.get("judge") or {}).get("why") or ""))
    return ("WHAT THE JUDGE SAW AT THE END OF PASSING RUNS:\n" + "\n".join(f"- {v}" for v in verdicts[-7:] if v)
            + "\n\nTHE PROGRAM THAT PASSED. Every control it uses and every check it makes worked on the real screen:\n" + pkg.code[:24000])


def plan_notes(plan: dict, record: dict) -> str:
    """What a plan lesson found, for the app's guide: how the app behaves, what each skill does, and Spark's last words."""
    said = [r["said"] for r in record.get("record", []) if r.get("said")]
    skills = "\n".join(f"- {s.get('name')}: {s.get('does', '')}\n  steps: {json.dumps(s.get('steps'))[:3000]}" for s in plan.get("skills", []))
    return f"How it behaves: {plan.get('how_it_behaves', '')}\n\nSkills the plan has:\n{skills}\n\nWhat Spark said while exploring:\n" + "\n".join(said[-12:])
