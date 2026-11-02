"""The rule that makes the paperwork team safe lives in plain code, so it can be tested without a model."""
import json
from pathlib import Path

import pytest

from autoharness import team

PLAN = json.loads((Path(__file__).parents[1] / "plans" / "clinic.json").read_text())


def read(page, reader, **data):
    return {"page": page, "reader": reader, "data": data, "seconds": 1}


TRIALS = [{"drug": "Sertraline 100 mg", "start": "01/08/2024", "end": "08/19/2024", "outcome": "Inadequate response"}, {"drug": "Bupropion XL 300 mg", "start": "09/03/2024", "end": "05/12/2025", "outcome": "Intolerance"}]
GOOD = dict(patient_name="Nadia Whitlock", dob="04/22/1981", member_id="MBR-418207", icd10="F33.1", drug="Vortioxetine", strength="10 mg", quantity="30", days="30", prior_treatments=TRIALS)


def two_reads(**over):
    return [read(0, "Whole page", **{**GOOD, **over}), read(0, "Specialist", **GOOD)]


def kinds(result):
    return {(i["kind"], i["field"]) for i in result["issues"]}


def test_two_agreeing_reads_clear():
    r = team.merge(PLAN, [read(0, "Whole page", **GOOD), read(0, "Specialist", **GOOD)])
    assert r["status"] == "clear" and not r["issues"]


def test_one_wrong_digit_goes_to_a_person_with_both_values():
    r = team.merge(PLAN, two_reads(member_id="MBR-418208"))
    assert r["status"] == "needs_person"
    issue = next(i for i in r["issues"] if i["field"] == "member_id")
    assert issue["kind"] == "identity" and {v["value"] for v in issue["votes"]} == {"MBR-418207", "MBR-418208"}
    field = next(f for f in r["fields"] if f["key"] == "member_id")
    assert field["value"] is None  # no majority wins: a disagreement never fills in a value


def test_a_majority_doesnt_outvote_a_single_disagreement():
    answers = [read(0, n, **GOOD) for n in "abc"] + [read(1, "d", member_id="MBR-999999")]
    assert ("identity", "member_id") in kinds(team.merge(PLAN, answers))


def test_one_read_alone_is_not_enough():
    assert ("unconfirmed", "patient_name") in kinds(team.merge(PLAN, [read(0, "Whole page", **GOOD)]))


def test_same_value_written_differently_is_not_a_disagreement():
    answers = two_reads(patient_name="Whitlock, Nadia", dob="April 22, 1981", member_id="MBR 418207", strength="10mg", prior_treatments=[{**TRIALS[0], "start": "1/8/24", "end": "19-Aug-2024"}, TRIALS[1]])
    assert team.merge(PLAN, answers)["status"] == "clear"


def test_missing_required_value_is_flagged():
    answers = [read(0, n, **{k: v for k, v in GOOD.items() if k != "quantity"}) for n in "ab"]
    assert ("missing", "quantity") in kinds(team.merge(PLAN, answers))


def test_too_few_complete_rows_is_a_gap():
    gap = [TRIALS[0], {**TRIALS[1], "end": None}]
    answers = [read(0, n, **{**GOOD, "prior_treatments": gap}) for n in "ab"]
    r = team.merge(PLAN, answers)
    assert ("gap", "prior_treatments") in kinds(r) and r["status"] == "needs_person"


def test_a_treatment_cant_end_before_it_starts():
    bad = [{**TRIALS[0], "end": "08/19/2023"}, TRIALS[1]]
    answers = [read(0, n, **{**GOOD, "prior_treatments": bad}) for n in "ab"]
    assert any(i["kind"] == "date_order" for i in team.merge(PLAN, answers)["issues"])


def test_a_short_name_joins_the_longer_row():
    short = [{**TRIALS[0], "drug": "Sertraline"}, TRIALS[1]]
    r = team.merge(PLAN, two_reads(prior_treatments=short))
    assert len(r["tables"][0]["rows"]) == 2 and r["tables"][0]["rows"][0]["cells"]["drug"]["value"] == "Sertraline 100 mg"


def test_a_failed_read_means_a_person_looks():
    answers = two_reads() + [{"page": 0, "reader": "x", "data": {}, "seconds": 1, "error": "timeout"}]
    assert any(i["kind"] == "unread" for i in team.merge(PLAN, answers)["issues"])


def test_values_outside_the_choices_are_flagged():
    odd = [{**TRIALS[0], "outcome": "Patient preference"}, TRIALS[1]]
    r = team.merge(PLAN, [read(0, n, **{**GOOD, "prior_treatments": odd}) for n in "ab"])
    assert r["status"] == "needs_person"


@pytest.mark.parametrize("raw,want", [("03/04/2024", "2024-03-04"), ("3/4/24", "2024-03-04"), ("March 4, 2024", "2024-03-04"), ("04-Mar-2024", "2024-03-04"), ("2024-03-04", "2024-03-04"), ("13/45/2024", None), ("soon", None)])
def test_dates(raw, want):
    assert team.parse_date(raw) == want


def test_a_stray_space_inside_a_date_still_trips_the_date_check():
    # Found by the hard test: "3/2 3/24" couldn't be parsed, so the check for an impossible date was silently skipped.
    bad = [TRIALS[0], {**TRIALS[1], "start": "3/2 3/24", "end": "7/9/23"}]
    r = team.merge(PLAN, [read(0, n, **{**GOOD, "prior_treatments": bad}) for n in "ab"])
    assert any(i["kind"] == "date_order" for i in r["issues"])


def test_a_date_that_cant_be_understood_goes_to_a_person():
    bad = [TRIALS[0], {**TRIALS[1], "start": "sometime in spring"}]
    r = team.merge(PLAN, [read(0, n, **{**GOOD, "prior_treatments": bad}) for n in "ab"])
    assert any(i["kind"] == "unreadable" for i in r["issues"]) and r["status"] == "needs_person"


def test_sum_check():
    plan = {"document": "an invoice", "fields": [{"key": "total", "label": "Total", "type": "money"}], "tables": [{"key": "items", "columns": [{"key": "name"}, {"key": "amount", "type": "money"}]}],
            "readers": [{"name": "a", "reads": ["total", "items"]}], "checks": [{"kind": "sum", "table": "items", "column": "amount", "total": "total"}]}
    team.check_plan(plan)
    items = [{"name": "Bolts", "amount": "$10.00"}, {"name": "Tape", "amount": "$5.50"}]
    ok = [read(0, n, total="$15.50", items=items) for n in "ab"]
    bad = [read(0, n, total="$25.50", items=items) for n in "ab"]
    assert team.merge(plan, ok)["status"] == "clear"
    assert any(i["kind"] == "sum" for i in team.merge(plan, bad)["issues"])


@pytest.mark.parametrize("change", [
    lambda p: p.pop("readers"),
    lambda p: p["readers"].__setitem__(0, {"name": "x", "reads": ["no_such_field"]}),
    lambda p: p["fields"][0].__setitem__("type", "python"),
    lambda p: p["fields"][0].__setitem__("key", "../../etc"),
    lambda p: p["checks"].append({"kind": "run_this_code", "code": "import os"}),
])
def test_a_bad_plan_is_refused(change):
    plan = json.loads(json.dumps(PLAN))
    change(plan)
    with pytest.raises(ValueError):
        team.check_plan(plan)


def test_uploads_only_from_the_upload_folder():
    from autoharness import server
    with pytest.raises(ValueError):
        server._uploaded(["/etc/passwd"])
