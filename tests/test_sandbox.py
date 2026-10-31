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
