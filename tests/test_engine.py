"""Claims the project makes about itself, checked."""
import json
import re
from pathlib import Path

import numpy as np

from autoharness import cloud, library, local, targets
from autoharness.teacher import COMPILE_RULES, EXPLORE_RULES, sdk_reference

ROOT = Path(__file__).resolve().parent.parent
ENGINE = sorted((ROOT / "autoharness").glob("*.py"))


def test_no_app_specific_code_anywhere_in_the_engine():
    """The claim: harnesses are generated, never hand-written. So the engine may not know any app."""
    banned = {"mines", "minesweeper", "solitaire", "klondike", "2048", "calculator", "openemr", "patient", "emr", "tile", "flag"}
    for spec in targets.catalog():
        banned |= {spec["id"].lower(), spec["name"].lower()}
    for f in ENGINE:
        words = {w for w in re.findall(r"[a-z0-9]+", f.read_text().lower()) if not w.isdigit()}
        hits = banned & words
        # Illustrations of what a verb looks like, in prompts and docs, are not logic. Anything else is a failure.
        allowed = {"patient"} if f.name in ("teacher.py", "sdk.py") else set()
        assert not (hits - allowed), f"{f.name} mentions {hits - allowed}"


def test_prompts_contain_every_sdk_method():
    ref = sdk_reference()
    for name in ("screen", "find", "read_text", "click", "ask", "confirm", "done", "fail"):
        assert f"app.{name}(" in ref
    assert "{sdk}" in COMPILE_RULES and "{max_turns}" in EXPLORE_RULES


def test_parse_sam_reads_boxes():
    text = "<0f>0<|box;x1=250;y1=170;x2=390;y2=230;w=640;h=400|><|mask;x=0;y=0;data=61,1|><|box;x1=1.4;y1=2;x2=3;y2=4;w=9;h=9|>"
    assert cloud.parse_sam(text) == [{"x1": 250, "y1": 170, "x2": 390, "y2": 230}, {"x1": 1, "y1": 2, "x2": 3, "y2": 4}]


def test_budget_blocks_calls(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud.config, "LEDGER", tmp_path / "ledger.json")
    monkeypatch.setattr(cloud.config, "HOME", tmp_path)
    monkeypatch.setattr(cloud.config, "LIBRARY", tmp_path / "l")
    monkeypatch.setattr(cloud.config, "RUNS", tmp_path / "r")
    monkeypatch.setattr(cloud.config, "BUDGET_USD", 1.0)
    cloud.Ledger.add(1.5, 0, 0, 0)
    try:
        cloud.Cloud()._post("/responses", {})
        raise AssertionError("should have refused")
    except cloud.BudgetExceeded:
        pass


def test_local_only_blocks_every_cloud_call():
    c = cloud.Cloud(allowed=False)
    try:
        c.respond(model="muse-spark-1.3", input="hi")
        raise AssertionError("should have refused")
    except cloud.CloudBlocked:
        pass


def test_extract_json_tolerates_chatter():
    assert local.extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert local.extract_json('The answer: {"verb": "x", "args": {}} done') == {"verb": "x", "args": {}}


def test_import_ignores_anything_but_known_files(monkeypatch, tmp_path):
    import zipfile
    monkeypatch.setattr(library.config, "LIBRARY", tmp_path / "lib")
    monkeypatch.setattr(library.config, "HOME", tmp_path)
    monkeypatch.setattr(library.config, "RUNS", tmp_path / "runs")
    bad = tmp_path / "x.harness"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("manifest.json", json.dumps({"name": "Shared", "goal": "g", "target": {}}))
        z.writestr("harness.py", "def run(app): pass")
        z.writestr("../../evil.py", "boom")
        z.writestr("assets/../../evil2.png", "boom")
        z.writestr("assets/ok.png", "x")
    pkg = library.import_file(bad)
    assert (pkg.path / "harness.py").exists() and (pkg.path / "assets/ok.png").exists()
    assert not (tmp_path / "evil.py").exists() and not list(tmp_path.rglob("evil*"))


def test_mcp_tool_shape():
    from autoharness.session import Session
    s = Session.__new__(Session)
    s.interface = {"verbs": [{"name": "x", "description": "d", "parameters": {"type": "object", "properties": {}}}], "observe_doc": "state"}

    class P:
        manifest = {"goal": "g"}
    s.pkg = P
    names = [t["name"] for t in s.tools()]
    assert names == ["observe", "x", "run_goal"]
