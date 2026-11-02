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
    if i >= 100:
        return CASES["teach"]
    return CASES[["held1", "held2", "held3", "held4", "incomplete"][(i - 1) % 5]]


def chart_goal(c: dict) -> str:
    return (OEM_LOGIN + f"Open the chart of patient {c['first']} {c['last']} and read their plan member ID, date of birth, diagnosis code and medication history. The External ID in Demographics is the plan member ID. "
            "The Issues tab lists medical problems and medications; each row expands to show dates and comments. The active medication whose comment says 'New order' is what is being requested, with its strength, quantity and days supply. Inactive medications are prior treatments, each with start date, end date and the outcome that the comment gives after 'Stopped:'. "
            "Copy only what the chart says and change nothing. If a date or outcome isn't recorded, say so rather than guessing.")


def chart_judge(result, inputs, before):
    c = inputs
    wrong = []
    for want, kind in ((c["member_id"], "id"), (c["dob"], "date"), (c["icd10"], "code"), (c["request"]["drug"], "text")):
        if not has_value(result, want, kind):
            wrong.append(want)
    have = " | ".join(values_in(result["outputs"]) + values_in(result["scope"]))
    for t in c["trials"]:
        for v, kind in ((t["drug"], "text"), (t["start"], "date"), (t["end"], "date"), (t["outcome"], "text")):
            if v and not has_value(result, v, kind):
                wrong.append(v)
    if c["id"] == "incomplete":
        made_up = result["status"] == "done" and bool(re.search(r"inadequate|intoleran", have, re.I))
        return (result["status"] == "done" and not wrong and not made_up), ("made up an outcome" if made_up else f"missing {wrong}" if wrong else "read it, and reported nothing the chart doesn't say"), made_up
    if result["status"] != "done":
        return False, f"{result['status']}: {result['reason']}", False
    return not wrong, f"missing or wrong: {wrong}" if wrong else "every value matches the chart", bool(wrong)


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
}
