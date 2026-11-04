"""Builds autoharness.adaptabyte.com from the repo: a landing page, and docsdb, the shared guides to apps.

    python scripts/build_docsdb.py _site       # the site, as GitHub Pages serves it
    python scripts/build_docsdb.py --check     # the checks every pull request to docsdb must pass

Each guide is docsdb/<name>/SKILL.md, an Agent Skill written by Autoharness from a lesson and reviewed before it's merged.
Every link here is relative, so the site works at adaptabyte.github.io/autoharness and at its own domain alike.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autoharness import guides  # noqa: E402

DB = ROOT / "docsdb"
REPO_URL = f"https://github.com/{guides.REPO}"


def all_guides() -> list[dict]:
    out = []
    for f in sorted(DB.glob("*/SKILL.md")):
        md = f.read_text()
        head, body = guides.parse(md)
        out.append({"id": f.parent.name, "md": md, "body": body, **{k: str(v) for k, v in head.items()}})
    return out


def check(found: list[dict]) -> list[str]:
    """What stops a guide from being merged: a wrong name, no description, or anything that looks private."""
    problems = []
    for g in found:
        if g.get("name") != g["id"] or guides.slug(g["id"]) != g["id"]:
            problems.append(f"{g['id']}: the name in the header must be the folder's name, in lowercase letters, digits and hyphens")
        if not g.get("description"):
            problems.append(f"{g['id']}: it needs a description")
        _, removed = guides.scrub(g["md"])
        if removed:
            problems.append(f"{g['id']}: it holds {', '.join(removed)}")
        if len(g["md"]) > 60_000:
            problems.append(f"{g['id']}: it's too long")
        if re.search(r"<\s*(script|iframe|object|embed|style|form)\b|javascript:|\bon[a-z]+\s*=\s*[\"']", g["md"], re.I):
            problems.append(f"{g['id']}: it holds HTML or script, which guides never need")
    return problems


def render(body: str) -> str:
    """Markdown to HTML, with any raw HTML in the guide shown as text and only web links kept."""
    import markdown
    safe = body.replace("&", "&amp;").replace("<", "&lt;")
    out = markdown.markdown(safe, extensions=["tables", "fenced_code", "sane_lists"])
    return re.sub(r'href="(?!https?://|#)[^"]*"', 'href="#"', out)


CSS = """
:root{--bg:#fbfaf7;--card:#fff;--ink:#1d1d1b;--soft:#5f5d57;--line:#e6e2d9;--accent:#2f5d50;--chip:#eef3f0;--code:#f3f1ec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--card:#1f1f1d;--ink:#ecebe6;--soft:#a5a39b;--line:#33322e;--accent:#8cc5b3;--chip:#22302b;--code:#262623}}
:root[data-theme="dark"]{--bg:#161615;--card:#1f1f1d;--ink:#ecebe6;--soft:#a5a39b;--line:#33322e;--accent:#8cc5b3;--chip:#22302b;--code:#262623}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 16px 80px}a{color:var(--accent)}h1{font-size:34px;line-height:1.15;letter-spacing:-.02em;margin:8px 0 10px}
h2{font-size:20px;margin:32px 0 8px}.lede{color:var(--soft);font-size:18px;margin:0 0 24px}.crumb{font-size:14px;color:var(--soft)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}
.card h3{margin:0 0 4px;font-size:18px}.card p{margin:0;color:var(--soft)}.meta{font-size:13px;color:var(--soft);margin-top:8px}
.chip{display:inline-block;background:var(--chip);border-radius:99px;padding:1px 9px;margin-right:6px;font-size:12px;color:var(--accent)}
input[type=search]{width:100%;font:inherit;padding:10px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink)}
code,pre{font:13.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--code);border-radius:6px}code{padding:1px 5px}pre{padding:12px 14px;overflow-x:auto}pre code{padding:0}
table{border-collapse:collapse;width:100%;display:block;overflow-x:auto;font-size:15px}th,td{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
.use{border-left:3px solid var(--accent)}.guide h1{display:none}.empty{color:var(--soft)}
"""


def page(title: str, body: str, depth: int) -> str:
    up = "../" * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><meta name="description" content="Shared guides to apps, written by AI from real use, for any agent.">
<style>{CSS}</style></head><body><main><div class="crumb"><a href="{up}">Autoharness</a> · <a href="{up}docsdb/">docsdb</a> · <a href="{REPO_URL}">GitHub</a></div>
{body}</main></body></html>"""


def build(out: Path) -> None:
    found = all_guides()
    problems = check(found)
    if problems:
        sys.exit("Not built:\n" + "\n".join(problems))
    if out.exists():
        shutil.rmtree(out)
    (out / "docsdb").mkdir(parents=True)
    index = []
    cards = []
    for g in found:
        gid = g["id"]
        d = out / "docsdb" / gid
        d.mkdir()
        (d / "SKILL.md").write_text(g["md"])
        index.append({k: g.get(k, "") for k in ("id", "app", "description", "platforms", "updated", "proven", "matches", "sources")}
                     | {"page": f"docsdb/{gid}/", "skill": f"docsdb/{gid}/SKILL.md", "raw": guides.shared_url(gid)})
        chips = "".join(f'<span class="chip">{html.escape(p.strip())}</span>' for p in re.split(r"[,/]", g.get("platforms", "")) if p.strip())
        cards.append(f'<a class="card" style="display:block;text-decoration:none;color:inherit" href="{gid}/" data-text="{html.escape((g.get("app", "") + " " + g.get("description", "") + " " + gid).lower())}">'
                     f'<h3>{html.escape(g.get("app") or gid)}</h3><p>{html.escape(g.get("description", ""))}</p>'
                     f'<div class="meta">{chips}updated {html.escape(g.get("updated", "?"))}{" · " + html.escape(g["proven"]) if g.get("proven") else ""}</div></a>')
        use = (f'<div class="card use"><b>Use it</b><p>Autoharness reads it before a lesson on this app, by itself. To name it outright:</p>'
               f'<pre><code>autoharness teach &lt;the app&gt; "&lt;the job&gt;" --docs docsdb:{gid}</code></pre>'
               f'<p>It\'s also an <a href="https://agentskills.io">Agent Skill</a>, so any agent that takes skills can use it: '
               f'<a href="SKILL.md" download>download SKILL.md</a> into a folder named <code>{gid}</code> in your agent\'s skills folder.</p>'
               f'<p class="meta">Wrong or out of date? Teach the app again and run <code>autoharness share {gid}</code>, or '
               f'<a href="{REPO_URL}/issues/new?title=docsdb:%20{gid}">say what\'s wrong</a>. '
               f'<a href="{REPO_URL}/commits/{guides.BRANCH}/docsdb/{gid}/SKILL.md">History of this guide</a>.</p></div>')
        (d / "index.html").write_text(page(f"{g.get('app') or gid}: docsdb",
                                           f'<h1>{html.escape(g.get("app") or gid)}</h1><p class="lede">{html.escape(g.get("description", ""))}</p>{use}'
                                           f'<div class="guide">{render(g["body"])}</div>', 2))
    (out / "docsdb" / "index.json").write_text(json.dumps({"guides": index}, indent=1))
    listing = "".join(cards) or '<p class="empty">No guides yet.</p>'
    (out / "docsdb" / "index.html").write_text(page("docsdb: shared guides to apps", f"""
<h1>docsdb</h1><p class="lede">Guides to apps, one per app, written by AI from real use and checked on the real screen. Any agent can use them.</p>
<div class="card use"><b>Where they come from</b><p>When <a href="{REPO_URL}">Autoharness</a> learns a job in an app, it reads the docs you give it, uses the app
on the screen, and writes down what it found: the controls, how jobs are done, and the traps, each marked as seen on screen or only in the docs.
With your yes, the guide is offered here as a pull request, and a person checks it before it's live. Nothing typed or read during a lesson,
and no names, accounts, addresses or keys, is ever in a guide. Each one is an <a href="https://agentskills.io">Agent Skill</a>, so Claude, Codex,
Gemini CLI and other agents can use it too.</p></div>
<input type="search" placeholder="Search {len(found)} guide{'s' if len(found) != 1 else ''}" aria-label="Search guides" oninput="for(const c of document.querySelectorAll('#list .card'))c.style.display=c.dataset.text.includes(this.value.toLowerCase())?'':'none'">
<div id="list">{listing}</div>
<h2>Add one</h2><p>Teach Autoharness a job in the app, then run <code>autoharness share &lt;name&gt;</code>. You read the guide first, and it goes up for review.
For machines: <a href="index.json">index.json</a> lists every guide.</p>""", 1))
    (out / "index.html").write_text(page("Autoharness", f"""
<h1>Autoharness</h1><p class="lede">Point it at any app, on this computer or another. A big model learns the app once, and a small model then does the job on your
own computer, checking every step.</p>
<div class="card use"><h3><a href="https://demo.adaptabyte.com">Try it live</a></h3><p>For the hackathon judges: a locked-down copy running on my GPUs. The sign-in is in the submission.</p></div>
<div class="card"><h3><a href="docsdb/">docsdb</a></h3><p>Shared guides to apps, written from real use, for any agent.</p></div>
<div class="card"><h3><a href="{REPO_URL}">The code, and how to start</a></h3><p>One command teaches an app; any agent then calls it as a tool.</p></div>""", 0))
    (out / ".nojekyll").write_text("")
    print(f"Built {len(found)} guide{'s' if len(found) != 1 else ''} into {out}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        bad = check(all_guides())
        print("\n".join(bad) or f"All {len(all_guides())} guides pass.")
        sys.exit(1 if bad else 0)
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "_site"))
