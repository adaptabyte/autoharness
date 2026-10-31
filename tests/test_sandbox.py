"""Generated code is untrusted. These tests attack the sandbox from the inside."""
import json
from pathlib import Path

from autoharness import sandbox

ATTACK = """
import os, socket, subprocess
def run(app):
    r = {}
    def t(name, f):
        try:
            f(); r[name] = "ALLOWED"
        except BaseException as e:
            r[name] = "blocked"
    t("socket", lambda: socket.socket())
    t("unix_socket", lambda: socket.socket(socket.AF_UNIX))
    t("read_home", lambda: os.listdir(os.environ.get("REAL_HOME", "%HOME%")))
    t("read_key", lambda: open("%HOME%/.config/muse/auth.json").read())
    t("start_program", lambda: subprocess.run(["/usr/bin/id"]))
    t("write_usr", lambda: open("/usr/autoharness-test", "w"))
    t("write_tmp", lambda: open("/tmp/autoharness-escape", "w"))
    t("signal_init", lambda: os.kill(1, 0))
    t("read_proc", lambda: open("/proc/1/environ").read())
    r["key_in_env"] = "MODEL_API_KEY" in os.environ
    r["uses_numpy"] = float(__import__("numpy").eye(3).sum())
    app.done("attack finished", r=r)
"""


def run_child(pkg: Path, work: Path):
    p = sandbox.spawn(pkg, work)
    p.stdin.write(json.dumps({"width": 8, "height": 8, "params": {}}) + "\n")
    p.stdin.flush()
    messages = []
    for line in p.stdout:
        m = json.loads(line)
        messages.append(m)
        if m["m"] == "end":
            break
    p.kill()
    p.wait()
    return messages


def test_generated_code_cannot_escape(tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "assets").mkdir(parents=True)
    (pkg / "harness.py").write_text(ATTACK.replace("%HOME%", str(Path.home())))
    messages = run_child(pkg, tmp_path / "work")
    assert messages[0] == {"m": "ready", "locked": True}
    result = messages[-1]["result"]["r"]
    assert result["key_in_env"] is False
    assert result["uses_numpy"] == 3.0
    for name in ("socket", "unix_socket", "read_home", "read_key", "start_program", "write_usr", "write_tmp",
                 "signal_init", "read_proc"):
        assert result[name] == "blocked", name


def test_stalled_harness_is_stopped_and_says_where(tmp_path):
    """A harness spinning without acting must not eat the whole time limit, and must leave evidence."""
    from autoharness.runtime import Runner, RunResult

    pkg = tmp_path / "pkg"
    (pkg / "assets").mkdir(parents=True)
    (pkg / "harness.py").write_text("def spin_here():\n    while True:\n        pass\n\ndef run(app):\n    spin_here()\n")

    class FakeDisplay:
        width, height = 8, 8

    class P:
        path = pkg
        manifest = {}

    r = Runner(P, FakeDisplay(), max_seconds=30, code_dir=pkg)
    r.stall_seconds = 1.0
    r._t_end = __import__("time").time() + 30
    end = r._launch(tmp_path / "work", RunResult())
    assert end["status"] == "stalled"
    assert "spin_here" in end["traceback"]


def test_ocr_process_cannot_reach_the_network():
    """OCR's runtime ships with telemetry, so the promise rests on the kernel, not on a setting."""
    import numpy as np

    from autoharness import runtime
    assert runtime.ocr_can_open_sockets() is False
    runtime.ocr(np.full((120, 300, 3), 255, dtype=np.uint8))  # and it still works
