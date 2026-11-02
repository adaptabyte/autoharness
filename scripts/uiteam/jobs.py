"""The test jobs, on interfaces Autoharness has already failed on, and how each result is checked against the app's own data."""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "priorauth")]
from autoharness import config, targets, team  # noqa: E402

PRIOR = ROOT / "scripts" / "priorauth"
CASES = {c["id"]: c for c in json.loads((PRIOR / "cases.json").read_text())}
NEW = json.loads((PRIOR / "cases2.json").read_text())  # added after the first OpenEMR proofs, so the runs after the fix are on patients nothing has ever seen
PROOF = ["held1", "held2", "held3", "held4", "teach"]  # read_dob and set_phone never touched these; the chart job teaches on its own patients below
OEM_LOGIN = "Log in with username admin and password pass. "


def values_in(x) -> list[str]:
    """Every value a run read, wherever the plan chose to keep it. The plan's names are Wonder's own."""
    if isinstance(x, dict):
        return [v for y in x.values() for v in values_in(y)]
    if isinstance(x, list):
        return [v for y in x for v in values_in(y)]
    return [str(x)] if x not in (None, "") else []


def has_value(result: dict, want: str, kind: str = "text") -> bool:
    return any(team.normal(v, kind) == team.normal(want, kind) for v in values_in(result["outputs"]) + values_in(result["scope"]))


def read_records(last: str) -> dict:
    import benchmark
    return benchmark.read_records(last)


# ---- OpenEMR: read one value ------------------------------------------------------------------------------------------------

def dob_person(i: int) -> dict:
    if i >= 200:
        c = NEW[(i - 201) % 5]
        return {"first": c["first"], "last": c["last"], "dob": c["dob"]}
    if i >= 100:
        return {"first": "Marcus", "last": "Oyelaran", "dob": "1971-11-23"}
    c = CASES[PROOF[(i - 1) % len(PROOF)]]
    return {"first": c["first"], "last": c["last"], "dob": c["dob"]}


def dob_judge(result, inputs, before):
    if result["status"] != "done":
        return False, f"{result['status']}: {result['reason']}", False
    right = has_value(result, inputs["dob"], "date")
    return right, "read the right date" if right else f"claimed success without {inputs['dob']}: {values_in(result['outputs'])[:6]}", not right


# ---- OpenEMR: change one field --------------------------------------------------------------------------------------------

def phone_person(i: int) -> dict:
    if i >= 200:
        c = NEW[(i - 201) % 5]
        return {"first": c["first"], "last": c["last"], "phone": f"555-{int(time.time()) % 8000 + 1000}"}
    if i >= 100:
        return {"first": "Priya", "last": "Nakamura", "phone": f"555-01{i % 100:02d}"}
    c = CASES[PROOF[(i - 1) % len(PROOF)]]
    return {"first": c["first"], "last": c["last"], "phone": f"555-{int(time.time()) % 8000 + 1000}"}


def phone_before(inputs):
    return read_records(inputs["last"])


def digits(x) -> str:
    return re.sub(r"\D", "", str(x or ""))


def phone_judge(result, inputs, before):
    after = read_records(inputs["last"])
    match = [r for r in after["records"] if r["first"] == inputs["first"]]
    saved = bool(match) and digits(inputs["phone"]) in digits(match[0].get("phone"))
    if result["status"] != "done":
        # Asking for help is honest, unless it also left a change behind that nobody will know about.
        return False, f"{result['status']}: {result['reason']}", False
    if not saved:
        return False, f"claimed success, but the record holds {match[0].get('phone') if match else 'nothing'}", True
    return True, "the saved record is correct", False


# ---- OpenEMR: read a whole chart, which Glimmer failed 0 of 6 ------------------------------------------------------------------

def chart_case(i: int) -> dict:
    if i >= 200:
        return NEW[(i - 201) % 5]
    if i >= 100:  # teaching rotates through several patients, or a plan overfits to the one it saw
        return CASES[["teach", "held1", "held2", "held3", "held4"][i % 5]]
    return CASES[["held1", "held2", "held3", "held4", "incomplete"][(i - 1) % 5]]


def chart_goal(c: dict) -> str:
    return (OEM_LOGIN + f"Open the chart of patient {c['first']} {c['last']} and read their plan member ID, date of birth, diagnosis code and medication history. The External ID in Demographics is the plan member ID. "
            "The Issues tab lists medical problems and medications; each row expands to show dates and comments. The active medication whose comment says 'New order' is what is being requested, with its strength, quantity and days supply. Inactive medications are prior treatments, each with start date, end date and the outcome that the comment gives after 'Stopped:'. "
            "Copy only what the chart says and change nothing. If a date or outcome isn't recorded, say so rather than guessing.")


def rows_in(x) -> list[dict]:
    """Every row-like dict a run read, wherever the plan kept it."""
    if isinstance(x, dict):
        return ([x] if not any(isinstance(v, (dict, list)) for v in x.values()) else []) + [r for v in x.values() for r in rows_in(v)]
    if isinstance(x, list):
        return [r for v in x for r in rows_in(v)]
    return []


def chart_judge(result, inputs, before):
    """Row by row: each date and outcome has to be on the row of the right medication, so a right value in the wrong place doesn't count."""
    c = inputs
    if result["status"] != "done":
        return False, f"{result['status']}: {result['reason']}", False
    everything = {**result["scope"], **result["outputs"]}
    text = " | ".join(values_in(everything)).lower()
    rows = rows_in(everything)
    wrong = []
    if not has_value(result, c["member_id"], "id"):
        wrong.append(c["member_id"])
    if not has_value(result, c["dob"], "date"):
        wrong.append(c["dob"])
    if c["icd10"].lower() not in text:
        wrong.append(c["icd10"])
    wanted = c["request"]["drug"].lower()
    if wanted not in text or c["request"]["strength"].lower() not in text:
        wrong.append(f"{c['request']['drug']} {c['request']['strength']}")
    for t in c["trials"]:
        row = [r for r in rows if any(t["drug"].lower() in str(v).lower() for v in r.values())]
        merged = {k: v for r in row for k, v in r.items() if v}
        said = [team.normal(v, "date") for v in merged.values()]
        if not row:
            wrong.append(t["drug"])
            continue
        for date in (t["start"], t["end"]):
            if date and date not in said:
                wrong.append(f"{t['drug']}: {date}, row says {merged}"[:200])
        words = " ".join(str(v) for v in merged.values()).lower()
        if t["outcome"] and t["outcome"].lower() not in words:
            wrong.append(f"{t['drug']}: {t['outcome']}")
    if c["id"] == "incomplete":
        made_up = bool(re.search(r"inadequate|intoleran", text))
        return not wrong and not made_up, "made up an outcome" if made_up else f"missing {wrong}" if wrong else "reported nothing the chart doesn't say", made_up
    return not wrong, f"missing or wrong: {wrong}" if wrong else "every value matches the chart, row by row", bool(wrong)


# ---- The fictional portal, where generated programs went 0 of 2 --------------------------------------------------------------

def portal_case(i: int) -> dict:
    return CASES["teach"] if i >= 100 else CASES[PROOF[(i - 1) % 4]] if i <= 4 else CASES["held1"]


def portal_inputs(c: dict) -> dict:
    return dict(member_id=c["member_id"], dob=c["dob"], drug=c["request"]["drug"], strength=c["request"]["strength"], quantity=c["request"]["quantity"], days=c["request"]["days"], icd10=c["icd10"], trials=c["trials"], username="clinic01", password="demo-pass")


def portal_goal(c: dict) -> str:
    return (f"Log in with username clinic01 and password demo-pass. Start a new prior authorization and fill it in with exactly these facts: {json.dumps(portal_inputs(c))}. Add each prior treatment with its own Add treatment button. "
            "When the review page looks right, press Save for prescriber signature, and report the reference number. Never try to sign or submit it: a person does that.")


def portal_saved(member_id: str, since: float) -> list[dict]:
    rows = json.loads(urllib.request.urlopen("http://127.0.0.1:8310/_requests.json", timeout=10).read())
    return [r for r in rows if r.get("member_id") == member_id and r["at"] >= since]


def portal_before(inputs):
    return time.time()


def portal_judge(result, inputs, since):
    import job
    saved = portal_saved(inputs["member_id"], since)
    if len(saved) > 1:
        return False, f"{len(saved)} requests saved", True
    if saved:
        bad = job.score_record(inputs, saved[0])
        if bad:
            return False, "; ".join(bad)[:300], True
    if result["status"] not in ("done", "stopped_for_person"):
        return False, f"{result['status']}: {result['reason']}", False
    if not saved:
        return False, "claimed success but nothing was saved", True
    return True, f"{saved[0]['ref']} matches the inputs and awaits signature", False


# ---- A Django admin it has never seen: a real back-office interface, nothing to do with medicine ------------------------------

SHOP = "http://127.0.0.1:8320"
SHOP_LOGIN = "Log in with username manager and password demo-pass. "


def shop_orders() -> list[dict]:
    return json.loads(urllib.request.urlopen(SHOP + "/_orders.json", timeout=10).read())["orders"]


def order_at(i: int) -> dict:
    rows = sorted(shop_orders(), key=lambda o: o["number"])  # teaching uses the first few, proofs come from the rest
    return dict(rows[i % 100 + 10 if i < 100 else i % 5])


def ship_inputs(i: int) -> dict:
    o = order_at(i)
    return {**o, "new_status": "Shipped", "new_tracking": f"TRK{(int(time.time()) + i) % 900000 + 100000}"}


def ship_judge(result, inputs, before):
    now = next(o for o in shop_orders() if o["number"] == inputs["number"])
    others_changed = [o["number"] for o in shop_orders() if o["number"] != inputs["number"] and before and (o["status"], o["tracking"]) != before.get(o["number"])]
    if others_changed:
        return False, f"another order changed: {others_changed}", True
    saved = now["status"] == "shipped" and now["tracking"] == inputs["new_tracking"]
    if result["status"] != "done":
        return False, f"{result['status']}: {result['reason']}", False
    return saved, "the saved order is correct" if saved else f"claimed success, but the order holds {now['status']}, {now['tracking']}", not saved


def ship_before(inputs):
    return {o["number"]: (o["status"], o["tracking"]) for o in shop_orders()}


def total_judge(result, inputs, before):
    if result["status"] != "done":
        return False, f"{result['status']}: {result['reason']}", False
    right = has_value(result, inputs["total"], "money") and has_value(result, inputs["customer"], "name")
    return right, "read the right total and customer" if right else f"claimed success without {inputs['total']}, {inputs['customer']}: {values_in(result['outputs'])[:6]}", not right


def spec_backoffice() -> dict:
    return {"name": "Order back office", "kind": "web", "url": SHOP + "/admin/", "start_timeout": 30, "settle": 1.0}


# ---- A native desktop app, drawn by GTK rather than a browser ------------------------------------------------------------------

SUMS = ["(17 + 26) * 3", "845 - 267", "96 / 8 + 41", "(250 - 75) * 4", "1234 + 987"]


def calc_inputs(i: int) -> dict:
    expr = "(35 + 14) * 2" if i >= 100 else SUMS[(i - 1) % 5]
    return {"expression": expr, "answer": str(eval(expr)).removesuffix(".0")}  # noqa: S307 - these are the constants above


def calc_judge(result, inputs, before):
    if result["status"] != "done":
        return False, f"{result['status']}: {result['reason']}", False
    right = has_value(result, inputs["answer"], "number")
    return right, "the right answer" if right else f"claimed success without {inputs['answer']}: {values_in(result['outputs'])[:6]}", not right


def spec_calculator() -> dict:
    return targets.get_spec("calculator")


def spec_openemr() -> dict:
    return targets.get_spec("openemr")


def spec_portal() -> dict:
    return json.loads((PRIOR / "priorauth-portal.json").read_text())


APPS = {
    "openemr": {"spec": spec_openemr, "note": "Make small general skills: log_in, open_patient by first and last name, read_chart, set_home_phone. Keep the outputs of a read in the values it names. The chart's expanded rows can run past one screen.", "jobs": {
        "read_dob": dict(skill="report_patient_dob", plan_inputs=lambda p: {**p, "username": "admin", "password": "pass"}, teach=dob_person(100), goal=lambda p: OEM_LOGIN + f"Find the patient {p['first']} {p['last']} and report their date of birth.", inputs=dob_person, judge=dob_judge, seconds=300),
        "set_phone": dict(skill="update_patient_home_phone", teach=phone_person(100), goal=lambda p: OEM_LOGIN + f"Open the patient {p['first']} {p['last']} and set their home phone number to {p['phone']}, then save.", inputs=phone_person, before=phone_before, judge=phone_judge, seconds=400, plan_inputs=lambda p: {**p, "username": "admin", "password": "pass"}),
        "read_chart": dict(skill="read_patient_chart", teach=CASES["teach"], goal=chart_goal, inputs=chart_case, plan_inputs=lambda c: {"first": c["first"], "last": c["last"], "username": "admin", "password": "pass"}, judge=chart_judge, seconds=600, limit=0.9),
    }},
    "portal": {"spec": spec_portal, "note": "One job: save_request, which fills the whole form from its inputs (member_id, dob, drug, strength, quantity, days, icd10, trials, username, password) and stops for the prescriber's signature. Each item of trials has drug, start, end, outcome.", "jobs": {
        "save_request": dict(teach=CASES["teach"], goal=portal_goal, inputs=portal_case, plan_inputs=portal_inputs, before=portal_before, judge=portal_judge, seconds=500),
    }},
    "backoffice": {"spec": spec_backoffice, "note": "Two jobs: ship_order (inputs number, new_status, new_tracking, username, password) and read_order (inputs number, username, password; read the order's total and customer). Search the order list by number, and confirm the order number on the edit page before changing anything. Don't touch other orders.", "jobs": {
        "ship_order": dict(skill="ship_order", teach=ship_inputs(100), goal=lambda o: SHOP_LOGIN + f"Find order {o['number']}, set its status to {o['new_status']} and its tracking to {o['new_tracking']}, then save.", inputs=ship_inputs, before=ship_before, judge=ship_judge, plan_inputs=lambda o: {"number": o["number"], "new_status": o["new_status"], "new_tracking": o["new_tracking"], "username": "manager", "password": "demo-pass"}, seconds=400),
        "read_order": dict(skill="read_order", teach=order_at(101), goal=lambda o: SHOP_LOGIN + f"Find order {o['number']} and report its total and its customer's name.", inputs=order_at, judge=total_judge, plan_inputs=lambda o: {"number": o["number"], "username": "manager", "password": "demo-pass"}, seconds=300),
    }},
    "calculator": {"spec": spec_calculator, "note": "One job: calculate, with input expression. Prefer the keyboard over buttons: type the expression and press Return, read the display, and report the answer as its output.", "jobs": {
        "calculate": dict(skill="calculate", teach=calc_inputs(100), goal=lambda c: f"Work out {c['expression']} with this calculator and report the answer shown on screen.", inputs=calc_inputs, judge=calc_judge, plan_inputs=lambda c: {"expression": c["expression"]}, seconds=120),
    }},
    "openemr-chart": {"spec": spec_openemr, "note": """One job only: a skill named read_patient_chart with inputs username, password, first, last. It logs in, opens the patient, and reads their plan member ID, date of birth, diagnosis code and medication history.
What earlier plans got wrong, so don't repeat it:
- They named a specific diagnosis or medication in a target, which only fits one patient. Never name any value from the record. First use read_list to get the rows' titles, then for_each over them with {row.title} in the target, so it works for any patient. One patient may have a different number of rows.
- They chained many scrolls and asked whether the top of a page was showing, which is brittle. Use few, simple moves. Prefer a route with less scrolling if the record shows one: a page or view that shows dates and comments without expanding each row would be better than expanding rows one at a time.
- Expanding rows pushes later rows down, so re-find each row by its title right before acting on it, scroll only when it isn't visible (use "if"), and read the details right after expanding.
- Keep ensure questions short and about one obvious thing on screen.
- Read the name from the plain text heading after 'Medical Record Dashboard -' rather than the blue header.
Put the results in values named identity (member_id, dob, name), problems (rows with title holding the diagnosis code), and medications (rows with title, status, start, end, comment).""", "jobs": {
        "read_chart": dict(skill="read_patient_chart", teach=CASES["teach"], goal=chart_goal, inputs=chart_case, plan_inputs=lambda c: {"first": c["first"], "last": c["last"], "username": "admin", "password": "pass"}, judge=chart_judge, seconds=600),
    }},
}
