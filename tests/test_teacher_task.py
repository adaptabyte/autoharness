"""A lost conversation must not lose what the teacher was asked to do, and adding verbs must really add them."""
from types import SimpleNamespace

import numpy as np

from autoharness.teacher import Teacher


def teacher(verbs: list[str], task: str = "") -> Teacher:
    t = Teacher.__new__(Teacher)
    t.pkg = SimpleNamespace(manifest={"goal": "g", "version": 1, "interface": {"verbs": [{"name": v} for v in verbs]}}, code="", assets=SimpleNamespace(glob=lambda _: []))
    t.target = SimpleNamespace(name="app")
    t.display = SimpleNamespace(shot=lambda: np.zeros((4, 4, 3), dtype=np.uint8))
    t.understanding, t.notes, t.frame_n, t.task, t.old_verbs = "", [], 0, task, None
    return t


def test_rebuild_keeps_the_request():
    text = teacher(["login"], "add a verb that counts patients")._rebuilt_items([])[0]["content"][0]["text"]
    assert "add a verb that counts patients" in text


def test_new_verbs_are_detected():
    t = teacher(["login", "count"])
    t.old_verbs = {"login"}
    assert t._new_verbs() == {"count"}
    t.old_verbs = {"login", "count"}
    assert not t._new_verbs()
