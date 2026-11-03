"""docsdb: what Autoharness learns about an app, kept as one guide per app, and shared when the person says so.

Every lesson leaves a guide on this computer, ~/.autoharness/guides/<id>/SKILL.md. It brings together the docs the person
gave, what Spark saw on the screen, and how the plan or program does the job, and each later lesson about the same app
updates it. The next lesson reads it first, like any other docs.

A guide is an Agent Skill (agentskills.io): a SKILL.md with a name and a description. So Claude, Codex, Gemini CLI and other
agents can use it too, not only Autoharness.

`autoharness share <id>` shows the guide and offers it to everyone in docsdb, at autoharness.adaptabyte.com/docsdb, as a pull request
to the public repo. Nothing leaves this computer without a yes, and a person reviews every guide before it's live: a guide
becomes instructions for other people's agents, so it's never published unchecked.

A guide never holds anything typed or read during a lesson (inputs, logins, values on the screen), people, records,
addresses on this network, file paths, keys or tokens. The model is told so, code removes what it can find, and the
person reads the file before it's shared.
"""
from __future__ import annotations

import base64
import datetime
import difflib
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config
from .cloud import Cloud, Meter, response_text
from .local import extract_json

REPO = "adaptabyte/autoharness"
BRANCH = "master"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/docsdb"
SITE = "https://autoharness.adaptabyte.com/docsdb"
LICENSE = "CC-BY-SA-4.0"  # docs are often CC BY-SA themselves, so what's built on them is shared the same way


def folder() -> Path:
    return config.HOME / "guides"


def slug(text: str) -> str:
    """A skill name: lowercase letters, digits and single hyphens, at most 64 characters."""
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:64].strip("-")


def local_path(gid: str) -> Path:
    return folder() / gid / "SKILL.md"


def load_local(gid: str) -> str | None:
    p = local_path(gid)
    return p.read_text() if p.exists() else None


def shared_url(gid: str) -> str:
    return f"{RAW}/{gid}/SKILL.md"


def page_url(gid: str) -> str:
    return f"{SITE}/{gid}/"


# ---- What may never be shared ------------------------------------------------------------------------------------------------

PRIVATE_HOST = re.compile(r"^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|169\.254\.|\[?::1\]?$|\[?f[cd][0-9a-f]{2}:|.*\.(local|lan|internal|home|ts\.net|corp)$|[^.]+$)", re.I)


def is_public_url(url: str) -> bool:
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.hostname) and not u.username and not PRIVATE_HOST.match(u.hostname or "")


_PATTERNS = [
    ("an email address", re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")),
    ("a private web address", re.compile(r"\b(?:https?|vnc|file|ftp|ssh|rdp)://[^\s)\]>\"'`]+", re.I)),
    ("a network address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b")),
    ("a file path", re.compile(r"(?:~/|/home/|/Users/|/root/|[A-Za-z]:\\\\?Users\\\\?)[^\s)\]>\"'`]*")),
    ("a key or token", re.compile(r"\b(?:sk|pk|ghp|gho|xox[bap]|AKIA|eyJ)[A-Za-z0-9_\-.]{12,}|\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b")),
    ("a phone number", re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")),
    ("an ID number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{7,}\b")),
]


def scrub(text: str, private: list[str] | None = None) -> tuple[str, list[str]]:
    """Removes what code can recognise: values from this lesson, addresses, paths, keys, numbers that look like IDs. Public
    web addresses stay, since they're where the docs came from. Returns the text and what kinds of things were removed."""
    removed: dict[str, int] = {}
    for value in sorted({str(v).strip() for v in private or [] if len(str(v).strip()) >= 3}, key=len, reverse=True):
        text, n = re.subn(re.escape(value), "[removed]", text, flags=re.I)
        if n:
            removed["something typed or read in the lesson"] = removed.get("something typed or read in the lesson", 0) + n

    for label, pattern in _PATTERNS:
        def sub(m, label=label):
            if label == "a private web address" and is_public_url(m.group(0).rstrip(".,;:")):
                return m.group(0)
            removed[label] = removed.get(label, 0) + 1
            return "[removed]"
        text = pattern.sub(sub, text)
    return text, [f"{n} × {k}" for k, n in removed.items()]


def private_values(inputs: dict | None, spec: dict | None) -> list[str]:
    """Everything a lesson was given that's about this person rather than the app."""
    values = [str(v) for v in (inputs or {}).values() if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
    s = spec or {}
    for key in ("url", "host"):
        if s.get(key) and not is_public_url(str(s[key])):
            values.append(str(s[key]))
            host = urllib.parse.urlsplit(str(s[key])).hostname
            if host:
                values.append(host)
    return values


# ---- Writing the guide ---------------------------------------------------------------------------------------------------------

GUIDE_RULES = """You keep the shared guide to one app: what an agent needs to know to use it through its screen. Anyone may \
read it, and other people's agents will follow it. A lesson just finished; update the guide with what it found.

Facts about the app only. Never include anything typed or read during the lesson, or any person, record, account, password, \
name, number or date seen on the screen, or any file path or network address. Leave out pixel positions and sizes that \
depend on one screen; say where things are in the window instead. Keep everything in the current guide unless the new \
notes show it's wrong, and then say what the screen showed. Anything a plan or program that passed its runs does or checks \
counts as seen on screen. Keep it under 1,200 words, plain and specific.

Reply with only JSON:
{{"app": "the app's full name, like GNOME Robots", "description": "one sentence on what the guide covers and when to use it",
"platforms": "where it runs, like Linux, Windows, Mac or web", "body": "the guide, in markdown, with these sections:
## What it is
## Controls  (a table: Input | What it does | Status, where Status is 'seen on screen', 'from the docs', or what the screen showed instead)
## How to do common jobs
## How it behaves
## Traps
## Not known yet"}}

THE CURRENT GUIDE:
{previous}

WHAT THE DOCS SAID (if any were given):
{docs}

WHAT THIS LESSON FOUND ON THE SCREEN, AND HOW THE JOB IS NOW DONE:
{notes}

HOW THE LESSON ENDED: {outcome}"""


def _front(gid: str, app: str, description: str, matches: list[str], platforms: str, sources: list[str], proven: str, made_by: str) -> str:
    meta = {"app": app, "matches": " ".join(dict.fromkeys(m for m in matches if m)), "platforms": platforms,
            "sources": " ".join(dict.fromkeys(sources)), "updated": datetime.date.today().isoformat(), "made-by": made_by, "proven": proven}
    lines = ["---", f"name: {gid}", f"description: {json.dumps(description[:1000])}", f"license: {LICENSE}", "metadata:"]
    lines += [f"  {k}: {json.dumps(str(v))}" for k, v in meta.items() if v]
    return "\n".join(lines) + "\n---\n"


def parse(md: str) -> tuple[dict, str]:
    """A guide's frontmatter, flattened (metadata's keys sit beside name and description), and its body."""
    m = re.match(r"---\n(.*?)\n---\n?", md, re.S)
    if not m:
        return {}, md
    head: dict = {}
    for line in m.group(1).splitlines():
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if not value:
            continue
        try:
            head[key] = json.loads(value)
        except ValueError:
            head[key] = value
    return head, md[m.end():]


def matches_for(spec: dict | None) -> list[str]:
    """What a guide is looked up by: the app's command, or its public web address. Never an address on this network."""
    s = spec or {}
    out = []
    if s.get("kind") == "desktop" and s.get("command"):
        out.append(slug(Path(str(s["command"][0])).name))
    if s.get("url") and is_public_url(str(s["url"])):
        out.append(slug(re.sub(r"^www\.", "", urllib.parse.urlsplit(str(s["url"])).hostname or "")))
    return [m for m in out if m]


def update(app_hint: str, spec: dict | None, docs_text: str, notes: str, outcome: str, sources: list[str], private: list[str],
           meter: Meter | None = None, limit_usd: float = 0.1) -> dict:
    """Merge one lesson into the app's guide on this computer. Spark writes it from text only: no screenshots, no inputs."""
    meter = meter or Meter()
    candidates = [slug(app_hint)] + matches_for(spec)
    gid = next((c for c in candidates if c and local_path(c).exists()), None)
    previous = load_local(gid) if gid else None
    prompt = GUIDE_RULES.format(previous=parse(previous)[1].strip() if previous else "(none yet)", docs=docs_text.strip() or "(none)",
                                notes=scrub(notes, private)[0].strip() or "(none)", outcome=outcome)
    out = Cloud(meter=meter, limit_usd=limit_usd).respond(model=config.SPARK_MODEL, reasoning={"effort": "medium"},
                                                          input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}])
    try:
        reply = extract_json(response_text(out))
        body = str(reply["body"]).strip()
    except (ValueError, KeyError, TypeError):
        return {"ok": False, "why": "the guide couldn't be written this time", "usd": round(meter.usd, 4)}
    app = str(reply.get("app") or app_hint).strip()[:80] or app_hint
    gid = gid or slug(app) or next((c for c in candidates if c), "app")
    old_head = parse(previous)[0] if previous else {}

    def keep(key: str) -> list[str]:
        return str(old_head.get(key) or "").split()
    public = [s for s in sources if is_public_url(s)]
    description = str(reply.get("description") or f"How to use {app} through its screen.").strip()
    md = _front(gid, app, description, keep("matches") + matches_for(spec), str(reply.get("platforms") or "").strip()[:60],
                keep("sources") + public, outcome if outcome.startswith("learned") else str(old_head.get("proven") or ""),
                "Autoharness: Muse Wonder read the docs, Muse Spark checked them on the screen" if docs_text.strip() or "read the docs" in str(old_head.get("made-by"))
                else "Autoharness: Muse Spark used the app on the screen")
    body = re.sub(r"^# .*\n+", "", body)  # the title comes from the app's name
    md += f"\n# {app}\n\n{body}\n"
    if public:
        md += "\n## Sources\n\n" + "\n".join(f"- {s}" for s in dict.fromkeys(keep("sources") + public)) + "\n"
    md, removed = scrub(md, private)
    path = local_path(gid)
    path.parent.mkdir(parents=True, exist_ok=True)
    changed = previous != md
    path.write_text(md)
    return {"ok": True, "id": gid, "path": str(path), "changed": changed, "new": previous is None, "removed": removed, "usd": round(meter.usd, 4)}


# ---- Finding guides --------------------------------------------------------------------------------------------------------------

def fetch_shared(gid: str, timeout: float = 6) -> str | None:
    """The reviewed guide from docsdb, or None if there isn't one."""
    try:
        with urllib.request.urlopen(urllib.request.Request(shared_url(gid), headers={"User-Agent": "Autoharness"}), timeout=timeout) as r:
            return r.read(2_000_000).decode("utf8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def find(spec: dict | None, names: list[str] | None = None) -> list[dict]:
    """Guides for this app: the one on this computer, and the shared one in docsdb. Looked up by the app's command, its
    public web address, or a name the person gave."""
    out = []
    for gid in dict.fromkeys([*matches_for(spec), *(slug(n) for n in names or [] if n)]):
        if not gid:
            continue
        mine = load_local(gid)
        if mine is not None:
            out.append({"id": gid, "where": "this computer", "source": str(local_path(gid))})
        try:
            shared = fetch_shared(gid, timeout=4)
            if shared and shared != mine:  # the same guide twice would only cost more to read
                out.append({"id": gid, "where": "docsdb", "source": shared_url(gid)})
        except (OSError, urllib.error.URLError):
            pass  # offline: docsdb is a bonus, never a requirement
    return out


# ---- Sharing ---------------------------------------------------------------------------------------------------------------------

def share_settings(gid: str) -> dict:
    p = folder() / gid / "share.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def set_always(gid: str, always: bool) -> None:
    p = folder() / gid / "share.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"always": always}))


def check_shareable(md: str, gid: str) -> str:
    """The last look before anything leaves this computer."""
    head, body = parse(md)
    if head.get("name") != gid or not head.get("description"):
        raise ValueError("this guide's header is damaged; teach the app again to rewrite it")
    clean, removed = scrub(md)
    if removed:
        raise ValueError(f"this guide still holds {', '.join(removed)}. Edit {local_path(gid)} or teach again, then share")
    if len(md) > 60_000:
        raise ValueError("this guide is too long to share; it should be under about 1,200 words")
    return clean


def what_changes(gid: str, md: str) -> str:
    try:
        online = fetch_shared(gid)
    except (OSError, urllib.error.URLError):
        online = None
    if online is None:
        return "new"
    return "".join(difflib.unified_diff(online.splitlines(True), md.splitlines(True), "docsdb", "yours", n=1)) or "same"


def _gh(args: list[str], body: dict | None = None, run=subprocess.run) -> dict:
    cmd = ["gh", "api", *args] + (["--input", "-"] if body is not None else [])
    p = run(cmd, input=json.dumps(body) if body is not None else None, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:300] or "gh failed")
    return json.loads(p.stdout or "{}")


def open_pull_request(gid: str, md: str, run=subprocess.run) -> str:
    """The guide as a pull request to the public repo, through the GitHub CLI and its own sign-in. Someone without write
    access gets a fork first, as GitHub always works. Returns the pull request's address."""
    me = _gh(["user"], run=run)["login"]
    repo = _gh([f"repos/{REPO}"], run=run)
    where = REPO
    if not (repo.get("permissions") or {}).get("push"):
        where = _gh(["-X", "POST", f"repos/{REPO}/forks"], body={}, run=run)["full_name"]
    head_sha = _gh([f"repos/{where}/git/ref/heads/{BRANCH}"], run=run)["object"]["sha"]
    branch = f"docsdb-{gid}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    _gh(["-X", "POST", f"repos/{where}/git/refs"], body={"ref": f"refs/heads/{branch}", "sha": head_sha}, run=run)
    path = f"docsdb/{gid}/SKILL.md"
    put = {"message": f"docsdb: {gid}", "content": base64.b64encode(md.encode()).decode(), "branch": branch}
    try:
        put["sha"] = _gh([f"repos/{where}/contents/{path}?ref={branch}"], run=run)["sha"]
    except RuntimeError:
        pass  # a new guide
    _gh(["-X", "PUT", f"repos/{where}/contents/{path}"], body=put, run=run)
    head = branch if where == REPO else f"{me}:{branch}"
    pr = _gh(["-X", "POST", f"repos/{REPO}/pulls"], body={
        "title": f"docsdb: {gid}", "head": head, "base": BRANCH,
        "body": (f"A guide to {gid}, written by Autoharness from a lesson on this app and offered by @{me}.\n\n"
                 "It holds no inputs, logins, values from the screen, addresses or file paths: the model was told, code removed "
                 "what it could find, and the person read it before sharing. Please check it before merging.")}, run=run)
    return pr["html_url"]
