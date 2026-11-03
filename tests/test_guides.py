"""docsdb guides: one per app, written from what a lesson found, scrubbed of anything private, and shared only through a
pull request a person reviews. The model, GitHub and the network are faked."""
import base64
import json
import subprocess

import pytest

from autoharness import config, docs, guides


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    return tmp_path


def test_names_follow_the_skill_rules():
    assert guides.slug("GNOME Robots") == "gnome-robots"
    assert guides.slug("  --Mines!! (8x8)--  ") == "mines-8x8"
    assert len(guides.slug("x" * 100)) == 64


@pytest.mark.parametrize("url,public", [
    ("https://help.gnome.org/users/gnome-robots/stable/", True), ("https://fdroid.org/docs", True),
    ("http://127.0.0.1:8310/login", False), ("http://192.168.1.20/admin", False), ("https://gamepc/", False),
    ("http://100.101.102.103:4140", False), ("https://mybox.tail1234.ts.net/x", False), ("http://printer.local/", False),
    ("https://user:pw@example.com/", False), ("vnc://gamepc:5900", False)])
def test_what_counts_as_a_public_address(url, public):
    assert guides.is_public_url(url) is public


def test_anything_private_is_taken_out():
    text = ("Log in as jdoe with hunter22 at http://10.0.0.5:8080/login, or mail ops@clinic.org, or call (555) 123-4567. "
            "Patient MRN 12345678, SSN 123-45-6789. Saved to /home/ana/notes.txt and C:\\Users\\ana\\x. Key sk-abcdefghijklmnop12345. "
            "Screen at vnc://:pw@gamepc:5900 on 192.168.0.9. Docs: https://help.gnome.org/users/gnome-robots/stable/. Press Ctrl+N; 8x8 board, 10 mines.")
    clean, removed = guides.scrub(text, ["jdoe", "hunter22", "ab"])
    for gone in ("jdoe", "hunter22", "10.0.0.5", "ops@clinic.org", "555", "12345678", "123-45-6789", "/home/ana", "Users", "sk-abc", "gamepc", "192.168"):
        assert gone not in clean, gone
    assert "https://help.gnome.org/users/gnome-robots/stable/" in clean and "Press Ctrl+N; 8x8 board, 10 mines." in clean
    assert "2 × something typed or read in the lesson" in removed and any("email" in r for r in removed)


def test_a_lessons_private_values_include_its_inputs_and_a_private_address():
    vals = guides.private_values({"username": "jdoe", "count": 3, "flag": True}, {"kind": "vnc", "url": "vnc://gamepc:5900"})
    assert "jdoe" in vals and "3" in vals and "True" not in vals and "gamepc" in vals
    assert guides.private_values({}, {"kind": "web", "url": "https://example.com/app"}) == []


def reply(body, app="GNOME Robots"):
    text = json.dumps({"app": app, "description": "How to play GNOME Robots through its screen. Use when an agent plays it.", "platforms": "Linux", "body": body})
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


BODY = "## What it is\nTurn-based.\n\n## Controls\n| Input | What it does | Status |\n|---|---|---|\n| l | move east | seen on screen |\n| Alt+S | safe teleport | from the docs |"


def test_a_lesson_writes_the_apps_guide_and_the_next_one_updates_it(monkeypatch):
    sent = []
    monkeypatch.setattr(guides.Cloud, "respond", lambda self, **b: sent.append(b) or reply(BODY + "\n\nThe player jdoe was here."))
    spec = {"id": "custom", "name": "gnome-robots", "kind": "desktop", "command": ["gnome-robots"]}
    g = guides.update("Robots", spec, "WHAT THE APP'S DOCS SAY: press l", "Spark pressed l and moved east. Typed jdoe.",
                      "learned: a program passed 5/5", ["https://help.gnome.org/users/gnome-robots/stable/", "/tmp/uploads/abc-manual.pdf"], ["jdoe"])
    assert g["ok"] and g["new"] and g["id"] == "gnome-robots" and g["removed"] == ["1 × something typed or read in the lesson"]
    prompt = sent[0]["input"][0]["content"][0]["text"]
    assert "jdoe" not in prompt and "(none yet)" in prompt and sent[0]["model"] == config.SPARK_MODEL
    md = guides.load_local("gnome-robots")
    head, body = guides.parse(md)
    assert head["name"] == "gnome-robots" and head["license"] == guides.LICENSE and head["matches"] == "gnome-robots"
    assert head["sources"] == "https://help.gnome.org/users/gnome-robots/stable/"  # a file the person uploaded is never named
    assert head["proven"] == "learned: a program passed 5/5"
    assert body.startswith("\n# GNOME Robots\n\n## What it is") and "| Alt+S | safe teleport | from the docs |" in body and "jdoe" not in md
    assert guides.check_shareable(md, "gnome-robots") == md

    # A later lesson that didn't pass still adds what it saw, keeps the sources, and doesn't lose the earlier proof.
    monkeypatch.setattr(guides.Cloud, "respond", lambda self, **b: sent.append(b) or reply(BODY + "\n\n## Traps\nWaiting can get you caught."))
    g2 = guides.update("Robots", spec, "", "Waiting got the player caught.", "not learned: it ran out of time", [], [])
    assert g2["changed"] and not g2["new"]
    assert "Turn-based." in sent[1]["input"][0]["content"][0]["text"]  # the current guide goes in, so nothing is lost
    head2, body2 = guides.parse(guides.load_local("gnome-robots"))
    assert head2["proven"] == "learned: a program passed 5/5" and head2["sources"] == head["sources"] and "Waiting can get you caught." in body2


def test_a_guide_that_still_holds_something_private_is_never_shared(home):
    md = "---\nname: x\ndescription: \"d\"\n---\nMail me at a@b.co"
    with pytest.raises(ValueError, match="email"):
        guides.check_shareable(md, "x")
    with pytest.raises(ValueError, match="header"):
        guides.check_shareable("no header", "x")


def test_finding_guides_here_and_in_docsdb(monkeypatch, home):
    (home / "guides" / "gnome-robots").mkdir(parents=True)
    (home / "guides" / "gnome-robots" / "SKILL.md").write_text("---\nname: gnome-robots\n---\n")
    monkeypatch.setattr(guides, "fetch_shared", lambda gid, timeout=6: "---\nname: gnome-robots\n---\n" if gid == "gnome-robots" else None)
    assert [f["where"] for f in guides.find({"kind": "desktop", "command": ["gnome-robots"]})] == ["this computer"]  # the same text once
    monkeypatch.setattr(guides, "fetch_shared", lambda gid, timeout=6: "shared, and improved by someone" if gid == "gnome-robots" else None)
    found = guides.find({"kind": "desktop", "command": ["/usr/games/gnome-robots"]})
    assert [(f["id"], f["where"]) for f in found] == [("gnome-robots", "this computer"), ("gnome-robots", "docsdb")]
    assert found[1]["source"] == f"{guides.RAW}/gnome-robots/SKILL.md"
    assert guides.find({"kind": "vnc", "url": "vnc://gamepc:5900"}) == []  # a private address is never looked up
    monkeypatch.setattr(guides, "fetch_shared", lambda gid, timeout=6: (_ for _ in ()).throw(OSError("offline")))
    assert [f["where"] for f in guides.find({"kind": "desktop", "command": ["gnome-robots"]})] == ["this computer"]


def test_docsdb_names_are_docs_too(monkeypatch):
    seen = []
    monkeypatch.setattr(docs, "from_url", lambda url, follow=True: seen.append(url) or docs.Doc("g", "text", text="t"))
    docs.read(["docsdb:GNOME Robots"])
    assert seen == [f"{guides.RAW}/gnome-robots/SKILL.md"]


def test_sharing_is_a_pull_request_from_a_fork_for_everyone_else(home):
    calls = []

    def run(cmd, input=None, **kw):
        path = cmd[-1] if input is None else cmd[-3]
        calls.append((cmd[2:], json.loads(input) if input else None))
        out = {"user": {"login": "someone"}, f"repos/{guides.REPO}": {"permissions": {"push": False}},
               f"repos/{guides.REPO}/forks": {"full_name": "someone/autoharness"},
               f"repos/someone/autoharness/git/ref/heads/{guides.BRANCH}": {"object": {"sha": "abc"}},
               f"repos/{guides.REPO}/pulls": {"html_url": "https://github.com/adaptabyte/autoharness/pull/7"}}
        if "contents/" in path and input is None:
            return subprocess.CompletedProcess(cmd, 1, "", "Not Found")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out.get(path, {})), "")
    url = guides.open_pull_request("gnome-robots", "---\nname: gnome-robots\n---\nhi\n", run=run)
    assert url.endswith("/pull/7")
    put = next(b for args, b in calls if args[:2] == ["-X", "PUT"])
    assert base64.b64decode(put["content"]).decode() == "---\nname: gnome-robots\n---\nhi\n" and put["branch"].startswith("docsdb-gnome-robots-")
    assert "sha" not in put  # a new guide
    pr = next(b for args, b in calls if args[-1] == f"repos/{guides.REPO}/pulls" or args[-3:] == ["-X", "POST", f"repos/{guides.REPO}/pulls"] or f"repos/{guides.REPO}/pulls" in args)
    assert pr["head"].startswith("someone:docsdb-gnome-robots-") and pr["base"] == guides.BRANCH and "check it before merging" in pr["body"]


def test_always_sharing_is_remembered_and_can_be_stopped(home):
    assert guides.share_settings("x") == {}
    guides.set_always("x", True)
    assert guides.share_settings("x") == {"always": True}
    guides.set_always("x", False)
    assert guides.share_settings("x") == {"always": False}


def load_builder():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_docsdb", config.REPO / "scripts" / "build_docsdb.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GOOD = """---
name: gnome-robots
description: "How to play GNOME Robots through its screen."
license: CC-BY-SA-4.0
metadata:
  app: "GNOME Robots"
  platforms: "Linux"
  updated: "2026-11-03"
  proven: "learned: a program passed 5/5 runs on its own"
---

# GNOME Robots

## Controls

| Input | What it does | Status |
|---|---|---|
| l | move east | seen on screen |

Not <b>bold</b>, and [no](javascript:alert(1)) script links. [Docs](https://help.gnome.org/).
"""


def test_the_site_shows_every_guide_safely(tmp_path, monkeypatch):
    b = load_builder()
    db = tmp_path / "docsdb"
    (db / "gnome-robots").mkdir(parents=True)
    (db / "gnome-robots" / "SKILL.md").write_text(GOOD.replace("[no](javascript:alert(1)) script links", "no script links"))
    monkeypatch.setattr(b, "DB", db)
    assert b.check(b.all_guides()) == []
    b.build(tmp_path / "site")
    page = (tmp_path / "site" / "docsdb" / "gnome-robots" / "index.html").read_text()
    assert "<td>move east</td>" in page and "Not &lt;b&gt;bold&lt;/b&gt;" in page and 'href="https://help.gnome.org/"' in page
    assert "--docs docsdb:gnome-robots" in page and 'href="SKILL.md"' in page
    index = json.loads((tmp_path / "site" / "docsdb" / "index.json").read_text())["guides"]
    assert index[0]["id"] == "gnome-robots" and index[0]["skill"] == "docsdb/gnome-robots/SKILL.md"
    assert (tmp_path / "site" / "docsdb" / "gnome-robots" / "SKILL.md").read_text().startswith("---\nname: gnome-robots")
    assert 'href="/' not in (tmp_path / "site" / "docsdb" / "index.html").read_text()  # relative links: works on any domain or path


def test_a_bad_guide_is_never_merged(tmp_path, monkeypatch):
    b = load_builder()
    db = tmp_path / "docsdb"
    for name, md in {"wrong-name": GOOD, "Bad_Name": GOOD.replace("gnome-robots", "Bad_Name"), "leaky": GOOD.replace("name: gnome-robots", "name: leaky") + "\nMail a@b.co",
                     "scripted": GOOD.replace("name: gnome-robots", "name: scripted")}.items():
        (db / name).mkdir(parents=True)
        (db / name / "SKILL.md").write_text(md)
    monkeypatch.setattr(b, "DB", db)
    problems = "\n".join(b.check(b.all_guides()))
    assert "wrong-name: the name in the header must be the folder's name" in problems
    assert "Bad_Name: the name in the header" in problems and "leaky: it holds 1 × an email address" in problems
    assert "scripted: it holds HTML or script" in problems
    with pytest.raises(SystemExit):
        b.build(tmp_path / "site")
