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

    def __init__(self, answers=None, spots=True):
        self.answers, self.questions, self.spots = dict(answers or {}), 0, spots

    def locate(self, target):
        self.questions += 1
        return (500, 500) if self.spots else None

    def yes(self, question):
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
