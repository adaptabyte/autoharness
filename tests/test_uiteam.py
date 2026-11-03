"""The code that walks a plan decides when a run may keep going, so its rules are tested without a model or a screen."""
import numpy as np
import pytest

from autoharness import uiteam


class Screen:
    width, height = 1000, 1000

    def __init__(self):
        self.clicks, self.typed = [], []

    def shot(self):
        return np.zeros((10, 10, 3), np.uint8)

    def wait_stable(self, *a, **k):
        return True

    def click(self, x, y, button="left", count=1):
        self.clicks.append((x, y))

    def press(self, combo):
        pass

    def type(self, text):
        self.typed.append(text)

    def scroll(self, *a):
        pass


class Eyes:
    """Answers from a script, the way the small model would."""

    def read_box(self, frame, spot, target):
        self.questions += 1
        return self.answers.get("value")

    def __init__(self, answers=None, spots=True):
        self.answers, self.questions, self.spots = dict(answers or {}), 0, spots

    def locate(self, target):
        self.questions += 1
        return (500, 500) if self.spots else None

    def yes(self, question, closer=False):
        self.questions += 1
        return self.answers.get(question, True)

    def read_once(self, fields, frame, where=""):
        self.questions += 1
        return {k: self.answers.get(k) for k in fields}

    def read(self, fields, types=None):
        return {k: self.answers.get(k) for k in fields}


def run(steps, inputs=None, eyes=None, skills=None):
    plan = {"skills": [{"name": "job", "steps": steps}, *(skills or [])]}
    uiteam.check_plan(plan)
    r = uiteam.PlanRunner(plan, Screen())
    r.eyes = eyes or Eyes()
    r.settle = lambda: None
    return r.run("job", inputs or {}), r


def test_a_finished_plan_reports_done():
    result, _ = run([{"do": "click", "target": "Login"}])
    assert result["status"] == "done"


def test_a_failed_ensure_stops_and_nothing_after_it_runs():
    eyes = Eyes({"Is this the right page?": False})
    result, r = run([{"do": "ensure", "question": "Is this the right page?"}, {"do": "click", "target": "Delete"}], eyes=eyes)
    assert result["status"] == "needs_help" and r.display.clicks == []


def test_a_typed_value_that_reads_back_wrong_stops():
    result, _ = run([{"do": "type", "target": "Phone box", "text": "555-0100"}], eyes=Eyes({"value": "555-0199"}))
    assert result["status"] == "needs_help" and "reads back" in result["reason"]


def test_a_typed_value_that_reads_back_right_continues():
    result, r = run([{"do": "type", "target": "Phone box", "text": "{phone}"}], {"phone": "555-0100"}, Eyes({"value": "555-0100"}))
    assert result["status"] == "done" and r.display.typed == ["555-0100"]


def test_opening_the_wrong_record_stops():
    result, _ = run([{"do": "read", "into": "facts", "fields": {"name": "the name"}}, {"do": "compare", "a": "{facts.name}", "b": "{first} {last}", "kind": "name"}], {"first": "Ada", "last": "Lane"}, Eyes({"name": "Ida Lane"}))
    assert result["status"] == "needs_help" and "don't" in result["reason"]


def test_the_same_name_written_differently_passes():
    result, _ = run([{"do": "read", "into": "facts", "fields": {"name": "the name"}}, {"do": "compare", "a": "{facts.name}", "b": "{first} {last}", "kind": "name"}], {"first": "Ada", "last": "Lane"}, Eyes({"name": "Lane, Ada"}))
    assert result["status"] == "done"


def test_a_thing_it_cant_find_stops_rather_than_clicking_somewhere(monkeypatch):
    monkeypatch.setattr(uiteam.time, "sleep", lambda s: None)
    result, r = run([{"do": "click", "target": "Save"}], eyes=Eyes(spots=False))
    assert result["status"] == "needs_help" and r.display.clicks == []


def test_stop_for_person_ends_the_run_there():
    result, r = run([{"do": "stop_for_person", "message": "Prescriber signs this"}, {"do": "click", "target": "Submit"}])
    assert result["status"] == "stopped_for_person" and r.display.clicks == []


def test_an_input_nobody_provided_stops():
    result, _ = run([{"do": "type", "target": "box", "text": "{missing}"}])
    assert result["status"] == "needs_help"


def test_memory_is_held_in_code_and_lists_keep_their_type():
    steps = [{"do": "for_each", "list": "{rows}", "as": "row", "steps": [{"do": "type", "target": "box", "text": "{row.name}", "no_check": True}]}]
    result, r = run(steps, {"rows": [{"name": "a"}, {"name": "b"}]})
    assert result["status"] == "done" and r.display.typed == ["a", "b"]


def test_a_skill_can_call_a_skill_and_what_it_read_stays():
    inner = {"name": "read_it", "steps": [{"do": "read", "into": "facts", "fields": {"dob": "x"}}]}
    result, _ = run([{"do": "call", "skill": "read_it"}, {"do": "compare", "a": "{facts.dob}", "b": "1980-01-01"}], eyes=Eyes({"dob": "1980-01-01"}), skills=[inner])
    assert result["status"] == "done"


@pytest.mark.parametrize("bad", [
    {"skills": []},
    {"skills": [{"name": "a", "steps": [{"do": "run_shell", "command": "rm -rf /"}]}]},
    {"skills": [{"name": "a", "steps": [{"do": "call", "skill": "nobody"}]}]},
    {"skills": [{"name": "a", "steps": [{"do": "click"}]}]},
])
def test_a_bad_plan_is_refused(bad):
    with pytest.raises(ValueError):
        uiteam.check_plan(bad)


def test_a_big_difference_isnt_treated_as_a_misread():
    assert uiteam.close_enough("darius fenwick", "dariusz fenwick") and not uiteam.close_enough("ida lane", "marcus oyelaran")


def test_a_one_letter_misread_gets_a_closer_look_and_can_recover():
    class Later(Eyes):
        def __init__(self):
            super().__init__({"name": "Darius Fenwick"})
            self.looks = 0

        def read_once(self, fields, frame, where=""):
            self.looks += 1
            return {k: "Dariusz Fenwick" for k in fields}
    steps = [{"do": "read", "into": "facts", "fields": {"name": "the name"}}, {"do": "compare", "a": "{facts.name}", "b": "{first} {last}", "kind": "name"}]
    result, _ = run(steps, {"first": "Dariusz", "last": "Fenwick"}, Later())
    assert result["status"] == "done"


def test_a_similar_name_that_stays_different_on_a_closer_look_still_stops():
    steps = [{"do": "read", "into": "facts", "fields": {"name": "the name"}}, {"do": "compare", "a": "{facts.name}", "b": "{first} {last}", "kind": "name"}]
    result, _ = run(steps, {"first": "Dariusz", "last": "Fenwick"}, Eyes({"name": "Darius Fenwick"}))
    assert result["status"] == "needs_help"


class Pages(Eyes):
    """A list that scrolls, returning a fixed answer per page, the same to both reads."""

    def __init__(self, pages):
        super().__init__()
        self.pages, self.seen = pages, 0

    def read_once(self, fields, frame, where=""):
        page = self.pages[min(self.seen // 2, len(self.pages) - 1)]
        self.seen += 1
        return {"rows": page}


def list_step():
    return [{"do": "read_list", "into": "rows", "item": {"name": "n", "end": "e"}, "scroll": 3, "max_pages": 3}]


def test_a_row_cut_off_on_one_page_is_filled_from_the_next():
    result, _ = run(list_step(), eyes=Pages([[{"name": "A", "end": None}], [{"name": "A", "end": "2024-01-01"}], [{"name": "A", "end": "2024-01-01"}]]))
    assert result["status"] == "done" and result["outputs"]["rows"][0]["end"] == "2024-01-01"


def test_two_real_values_for_one_row_still_stop():
    result, _ = run(list_step(), eyes=Pages([[{"name": "A", "end": "2024-01-01"}], [{"name": "A", "end": "2024-01-09"}]]))
    assert result["status"] == "needs_help" and "differently" in result["reason"]


def test_what_is_read_in_a_loop_stays_with_its_row():
    class ByRow(Eyes):
        def __init__(self):
            super().__init__()
            self.n = 0

        def read(self, fields, types=None):
            self.n += 1
            return {"start": f"day{self.n}"}
    steps = [{"do": "for_each", "list": "{rows}", "as": "row", "steps": [{"do": "read", "into": "detail", "fields": {"start": "the start"}}]}]
    result, _ = run(steps, {"rows": [{"title": "A"}, {"title": "B"}]}, ByRow())
    assert result["outputs"]["detail"] == [{"title": "A", "start": "day1"}, {"title": "B", "start": "day2"}]


def test_a_placeholder_copied_back_counts_as_nothing():
    from autoharness import team
    assert team.normal("...") == "" and team.normal("…") == ""


def test_running_a_plan_never_touches_the_cloud(monkeypatch):
    from autoharness import cloud

    def blocked(*a, **k):
        raise AssertionError("a plan's run tried to use the cloud")
    monkeypatch.setattr(cloud.Cloud, "_post", blocked)
    monkeypatch.setattr(cloud.Cloud, "respond", blocked)
    result, _ = run([{"do": "click", "target": "Login"}, {"do": "ensure", "question": "Is it open?"}, {"do": "type", "target": "Box", "text": "x", "no_check": True}])
    assert result["status"] == "done"


# ---- A compiled interface, offered to other models as tools ---------------------------------------------------------------------

def shipped(name):
    import json
    from pathlib import Path
    return {**uiteam.check_plan(json.loads((Path(__file__).resolve().parent.parent / "plans" / "ui" / f"{name}.json").read_text())), "id": name}


def test_each_whole_job_is_one_tool_and_its_parts_are_not_offered():
    tools = uiteam.plan_tools(shipped("backoffice"))
    assert [t["name"] for t in tools] == ["ship_order", "read_order"]
    schema = tools[0]["inputSchema"]
    assert set(schema["required"]) == {"number", "new_status", "new_tracking", "username", "password"}
    assert schema["additionalProperties"] is False


def test_a_list_input_gets_its_shape_from_the_proven_sample():
    tool = uiteam.plan_tools(shipped("portal"))[0]
    trials = tool["inputSchema"]["properties"]["trials"]
    assert trials["type"] == "array" and set(trials["items"]["properties"]) == {"drug", "start", "end", "outcome"}


def test_a_call_with_a_gap_is_refused_before_anything_opens():
    plan = shipped("backoffice")
    good = {"number": "ORD-1", "username": "u", "password": "p"}
    assert uiteam.check_tool_call(plan, "read_order", good) == good
    for bad, why in [({"username": "u", "password": "p"}, "missing: number"), ({**good, "note": "x"}, "not inputs of this job: note"),
                     ({**good, "number": ["ORD-1"]}, "should be text")]:
        with pytest.raises(ValueError, match=why):
            uiteam.check_tool_call(plan, "read_order", bad)
    with pytest.raises(ValueError, match="no job called"):
        uiteam.check_tool_call(plan, "log_in", {"username": "u", "password": "p"})


def test_the_mcp_server_lists_every_interface_and_refuses_bad_calls_without_running(monkeypatch, tmp_path):
    from autoharness import config, server
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(uiteam, "saved_plans", lambda: {"backoffice": shipped("backoffice"), "calculator": shipped("calculator")})
    started = []
    monkeypatch.setattr(server, "start_ui_run", lambda *a, **k: started.append(a))
    init = server.ui_mcp_reply(None, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["capabilities"] == {"tools": {}}
    names = [t["name"] for t in server.ui_mcp_reply(None, {"id": 2, "method": "tools/list"})["result"]["tools"]]
    assert names == ["backoffice__ship_order", "backoffice__read_order", "calculator__calculate"]
    assert [t["name"] for t in server.ui_mcp_reply("calculator", {"id": 3, "method": "tools/list"})["result"]["tools"]] == ["calculate"]
    refused = server.ui_mcp_reply(None, {"id": 4, "method": "tools/call", "params": {"name": "backoffice__read_order", "arguments": {"number": "ORD-1"}}})
    assert refused["result"]["isError"] and "missing: username, password" in refused["result"]["content"][0]["text"]
    assert server.ui_mcp_reply(None, {"id": 5, "method": "tools/call", "params": {"name": "nobody__x", "arguments": {}}})["result"]["isError"]
    assert server.ui_mcp_reply(None, {"method": "notifications/initialized"}) is None
    assert server.ui_mcp_reply("nope", {"id": 6, "method": "tools/list"})["error"]["code"] == -32602
    assert started == []


def test_a_taught_job_gets_a_readable_name_and_never_overwrites_another(monkeypatch):
    plan = {"skills": [{"name": "log_in", "steps": []}, {"name": "read_order", "steps": []}], "jobs": {"read_order": "read_order"}}
    assert uiteam.main_job(plan) == "read_order"
    assert uiteam.main_job({**plan, "jobs": {}}) == "read_order"
    monkeypatch.setattr(uiteam, "saved_plans", lambda: {"django-administration": {}})
    assert uiteam.new_plan_id("Django administration", "x") == "django-administration-2"
    assert uiteam.new_plan_id("", "127-0-0-1-8320") == "127-0-0-1-8320"


def test_a_login_kept_on_this_computer_is_never_shown_to_the_caller_and_is_filled_in(monkeypatch, tmp_path):
    from autoharness import config
    monkeypatch.setattr(config, "HOME", tmp_path)
    (tmp_path / "logins.json").write_text('{"backoffice": {"username": "manager", "password": "demo-pass"}}')
    kept = uiteam.kept_logins("backoffice")
    plan = shipped("backoffice")
    tool = next(t for t in uiteam.plan_tools(plan, kept) if t["name"] == "read_order")
    assert set(tool["inputSchema"]["properties"]) == {"number"} and "demo-pass" not in str(tool)
    assert uiteam.check_tool_call(plan, "read_order", {"number": "ORD-1"}, kept) == {"number": "ORD-1", "username": "manager", "password": "demo-pass"}
    with pytest.raises(ValueError, match="not inputs of this job: password"):
        uiteam.check_tool_call(plan, "read_order", {"number": "ORD-1", "password": "guess"}, kept)
    assert uiteam.kept_logins("calculator") == {}


def test_a_whole_number_sent_as_a_float_is_typed_as_a_whole_number():
    plan = shipped("portal")
    props = uiteam.plan_tools(plan)[0]["inputSchema"]["properties"]
    assert props["quantity"]["type"] == ["integer", "string"]
    args = {**plan["samples"]["save_request"], "quantity": 30.0, "days": 30.0}
    args["trials"] = [{**args["trials"][0], "drug": "Lamotrigine 200 mg"}]
    out = uiteam.check_tool_call(plan, "save_request", args)
    assert out["quantity"] == 30 and isinstance(out["quantity"], int) and out["days"] == 30
