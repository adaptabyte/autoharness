#!/usr/bin/env python3
"""Cuts the real recordings in clips/ into the 3-minute video, clips/draft.mp4, and a short one for X, clips/teaser.mp4.
  make_video.py [draft|teaser|both] [--cards]     --cards also saves each card as clips/cards/*.png

Footage is real. Wherever it's sped up, a tag in the corner says by how much, because watching a run in real time
isn't the point and hiding the speed-up would be. Cards and captions are HTML, rendered by the same browser that records."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CLIPS = ROOT / "clips"
W, H, FPS = 1280, 720, 24
BG = "f6f5f1"

STYLE = """<link rel=preconnect href=https://fonts.googleapis.com><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel=stylesheet>
<style>*{box-sizing:border-box}html,body{margin:0;width:1280px;height:720px;font-family:Inter,"Noto Sans",sans-serif;color:#17201c;-webkit-font-smoothing:antialiased}
.card{width:1280px;height:720px;background:#f6f5f1;padding:76px 96px;display:flex;flex-direction:column;justify-content:center;position:relative}
.kicker{font-size:22px;font-weight:600;color:#116149;letter-spacing:.01em;margin:0 0 18px}
h1{font-size:64px;line-height:1.04;letter-spacing:-.035em;font-weight:800;margin:0 0 22px}
h2{font-size:30px;line-height:1.3;letter-spacing:-.015em;font-weight:500;color:#5f6a64;margin:0}
.foot{position:absolute;left:96px;right:96px;bottom:44px;font-size:17px;color:#8b948f;display:flex;justify-content:space-between}
.logo{display:inline-flex;align-items:center;gap:12px;font-weight:700;font-size:22px}.logo i{width:34px;height:34px;border-radius:9px;background:#116149;display:grid;place-items:center}
.vs{display:grid;grid-template-columns:1fr 70px 1fr;align-items:center;margin:34px 0 0}.box{background:#fff;border:1px solid #e1dfd7;border-radius:22px;padding:30px 36px}
.box small{display:block;font-size:22px;color:#5f6a64;font-weight:500;margin-bottom:6px}.box b{font-size:112px;letter-spacing:-.05em;line-height:1;font-weight:800}
.box.bad b{color:#b3261e}.box.good{border:2px solid #116149;background:#e4f1ec}.box.good b{color:#116149}.arrow{text-align:center;font-size:44px;color:#8b948f}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:40px}.step{background:#fff;border:1px solid #e1dfd7;border-radius:18px;padding:22px 24px}
.step b{display:block;font-size:24px;letter-spacing:-.01em;margin-bottom:4px}.step span{font-size:18px;color:#5f6a64}.tag{display:inline-block;margin-top:14px;font-size:15px;font-weight:700;font-style:normal;padding:4px 10px;border-radius:7px}
.cloud{color:#a15c00;background:#fbf0dc}.local{color:#116149;background:#e4f1ec}
ul{margin:26px 0 0;padding:0;list-style:none}li{font-size:29px;line-height:1.3;margin:0 0 18px;padding-left:40px;position:relative;letter-spacing:-.01em}li:before{content:"";position:absolute;left:4px;top:13px;width:14px;height:14px;border-radius:4px;background:#c9c6ba}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e1dfd7;border-radius:16px;overflow:hidden;margin-top:22px;font-variant-numeric:tabular-nums}
td,th{padding:11px 18px;text-align:left;border-bottom:1px solid #eceae3;font-size:19px}th{font-size:15px;color:#5f6a64;font-weight:600}tr:last-child td{border-bottom:0}td.us{font-weight:800;color:#116149}td.dim{color:#5f6a64}
.mono{font-family:"JetBrains Mono",monospace;font-size:22px;color:#116149}
.cap{position:absolute;left:50%;bottom:30px;transform:translateX(-50%);max-width:1080px;background:rgba(20,26,24,.88);color:#fff;font-size:26px;line-height:1.32;font-weight:600;letter-spacing:-.005em;padding:14px 26px;border-radius:14px;text-align:center}
.term{background:#17201c;border-radius:18px;padding:24px 30px;font:500 21px/1.75 "JetBrains Mono",monospace;color:#e9ece8}.term s{text-decoration:none;color:#7fd1ae;margin-right:12px}.term em{font:500 17px Inter,sans-serif;color:#8b948f;margin-left:18px;font-style:normal}.term .ok{color:#7fd1ae}
.speed{position:absolute;right:22px;top:20px;background:rgba(20,26,24,.78);color:#fff;font-size:15px;font-weight:700;padding:6px 12px;border-radius:9px}
</style>"""

LOGO = '<span class=logo><i><svg width=20 height=20 viewBox="0 0 16 16"><path d="M3 8.5l3.2 3.2L13 4.5" stroke="#fff" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></i>Autoharness</span>'


def proof_rows() -> list[list[str]]:
    return json.loads((ROOT / "docs" / "paperwork-final.json").read_text())["rows"]


def card_html(kind: str) -> str:
    foot = f'<div class=foot>{LOGO}<span>Made-up records throughout</span></div>'
    if kind == "hook":
        return f"""<div class=card><p class=kicker>Same small model. Same job: reading a patient's chart in OpenEMR.</p>
<div class=vs><div class="box bad"><small>Given the whole job</small><b>0/6</b></div><div class=arrow>→</div><div class="box good"><small>Compiled first</small><b>5/5</b></div></div>
<h2 style="margin-top:34px">The model didn't change. A frontier model did the thinking in advance.</h2>{foot}</div>"""
    if kind == "problem":
        return f"""<div class=card><p class=kicker>The problem</p><h1>AI agents pay a genius<br>to click every button.</h1>
<ul><li>Software is built for human eyes and hands, and most of it has no API.</li><li>Agents send a frontier model a screenshot at almost every step.</li><li>That's slow, it costs money every run, and your screen goes to the cloud.</li></ul>{foot}</div>"""
    if kind == "idea":
        return f"""<div class=card><p class=kicker>The idea</p><h1>Computer use should be the<br>compiler, not the runtime.</h1>
<div class=steps><div class=step><b>Muse Spark explores</b><span>Uses the interface once. Everything is recorded.</span><br><em class="tag cloud">Cloud, once</em></div>
<div class=step><b>Muse Wonder compiles</b><span>A plan, with every decision made in advance.</span><br><em class="tag cloud">Cloud, once</em></div>
<div class=step><b>Muse Glimmer runs it</b><span>Small, open, every step checked by code.</span><br><em class="tag local">Your computer, every run</em></div></div>{foot}</div>"""
    if kind == "plug":
        return f"""<div class=card style="padding:60px 96px"><p class=kicker>Plug and play</p><h1 style="font-size:54px;margin:0 0 26px">Three commands.<br>One line for any agent.</h1>
<div class=term><div><s>$</s> autoharness up<em>starts it, and checks what's ready</em></div>
<div><s>$</s> autoharness teach &lt;address&gt; "&lt;the job, in plain words&gt;"<em>learns it, once</em></div>
<div style="padding-left:38px;font:500 17px Inter,sans-serif;color:#8b948f;margin:-4px 0 6px">a web address, an app's command, or vnc:// for any other computer: Windows, Mac, a game PC</div>
<div><s>$</s> autoharness call orders__read_order order_number=ORD-26616</div>
<div class=ok>✓ Verified in 22 s, 26 checks, $0 in the cloud</div></div>
<h2 style="font-size:24px;margin-top:26px">Any MCP client: <span class=mono style="font-size:22px">127.0.0.1:4140/mcp/ui</span>, or the command <span class=mono style="font-size:22px">autoharness mcp</span></h2>{foot}</div>"""
    if kind == "manual":
        return f"""<div class=card><p class=kicker>Not just forms: any app, with its manual</p><h1 style="font-size:54px">Give it the manual.<br>It checks what the manual says.</h1>
<ul><li>GNOME Robots: its keys can't be guessed. You move with y k u h l b j n.</li><li>Muse Wonder read the 8-page help site, and told Spark what to check first.</li>
<li>The program it wrote moves with exactly those keys. Level 1 cleared in 5 of 5 runs on its own, for $1.64 once.</li></ul>{foot}</div>"""
    if kind == "table":
        rows = "".join(f"<tr><td>{escape(r[0])}</td><td class=us>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td class=dim>{escape(r[4])}</td></tr>" for r in proof_rows())
        return f"""<div class=card style="padding:52px 80px"><p class=kicker style="margin:0 0 4px">Measured on inputs it hadn't seen, checked against each app's own data</p>
<h1 style="font-size:46px;margin:6px 0 0">35 of 35 runs. Nothing wrong saved.</h1>
<table><tr><th>Job</th><th>Glimmer + plan</th><th>Median</th><th>Cloud</th><th>Muse Spark, live</th></tr>{rows}</table>
<p style="font-size:16px;color:#8b948f;margin:14px 0 0">Small samples. Pass bars committed to git before the runs. Every failed round is in docs/PROOF.md.</p></div>"""
    if kind == "honest":
        return f"""<div class=card><p class=kicker>What it isn't, yet</p><h1>Honest limits</h1>
<ul><li>It isn't ready for real patients. Every record here is made up.</li><li>A plan only knows what it was taught. Spark does better on new jobs.</li><li>The samples are small, and a swarm barely adds speed on my hardware.</li><li>Every failed round is in the repo, with bars committed before each test.</li></ul>{foot}</div>"""
    if kind == "vision":
        return f"""<div class=card><p class=kicker>The vision</p><h1 style="font-size:56px">Every interface was built for people.<br>Now models build the version for models.</h1>
<h2>A frontier model learns it once. A small model runs it from then on. Any agent can call it.</h2>
<p style="margin:34px 0 0;font-size:34px;font-weight:800;letter-spacing:-.02em;color:#116149">By the models, for the models.</p>{foot}</div>"""
    if kind == "end":
        return f"""<div class=card style="align-items:center;text-align:center">{LOGO.replace('font-size:22px', '')}
<h1 style="margin:26px 0 12px;font-size:60px">Any interface,<br>compiled for a small model.</h1>
<p class=mono>github.com/adaptabyte/autoharness</p>
<p class=mono style="margin-top:6px">Try it live: demo.adaptabyte.com · Shared guides: autoharness.adaptabyte.com/docsdb</p>
<h2 style="font-size:22px;margin-top:26px">Built with Muse Spark, Muse Wonder and Muse Glimmer (open weights).<br>Claude Code wrote most of the code.</h2></div>"""
    raise KeyError(kind)


def overlay_html(caption: str, speed: float) -> str:
    tag = f"<div class=speed>Real run, {speed:g}× speed</div>" if speed > 1 else ""
    cap = f"<div class=cap>{escape(caption).replace(chr(10), '<br>')}</div>" if caption else ""
    return f"<body style='background:transparent'>{tag}{cap}</body>"


# (clip, seconds into it (negative: from the end), seconds in the cut, speed-up, caption). A card is ("card:<kind>", 0, seconds, 1, "").
DRAFT = [
    ("swarm", 60, 6, 40, "Eight apps built for people. One small open model running them, on my desk. No cloud."),
    ("card:hook", 0, 8, 1, ""),
    ("card:problem", 0, 8, 1, ""),
    ("card:idea", 0, 7, 1, ""),
    ("home", 1.5, 5, 1, "Autoharness. Point it at any interface."),
    ("teach", 0, 7, 1, "Here's an app it has never seen. Give it the address and the job, in plain words."),
    ("teach", 16, 8, 6, "Muse Spark uses it once, and everything is recorded."),
    ("teach", "plan", 9, 5, "Muse Wonder compiles a plan. Then Glimmer has to pass on its own before it's kept."),
    ("teach", "verdict", 5, 1, "Learned, for $0.13, once. Now it's a tool."),
    ("agent", 1, 7, 1, "Any agent can call it. Here Muse Spark is the agent, asking about a customer it wasn't taught on."),
    ("agent", 10, 6, 5, "Spark picks the job. The small model does the work in the app, on this computer."),
    ("agent", -7, 5, 1, "Spark gets back only the verified answer. Never the screen, never the login."),
    ("card:plug", 0, 7, 1, ""),
    ("card:manual", 0, 7, 1, ""),
    ("robots", "started", 7, 8, "The program Wonder wrote from the manual, clearing level 1. On this computer, no cloud."),
    ("docsdb", 2.5, 5, 1.5, "What a lesson learns becomes a guide in docsdb: an Agent Skill any agent can use."),
    ("run", 20, 7, 4, "Muse Glimmer answers one narrow question per screen. Code holds the memory."),
    ("run", 95, 6, 2, "What it types is read back. What it reads is read twice.\nA run ends verified, or it stops and asks."),
    ("card:table", 0, 11, 1, ""),
    ("digit", 25, 6, 3, "I'm a psychiatrist. Paper is an interface too: each page is read on this computer."),
    ("digit", -9, 7, 1, "One digit differs between pages. It doesn't pick one. It comes to me, side by side."),
    ("clean", 45, 7, 8, "Approve a clean stack, and a compiled plan fills the insurer's portal."),
    ("clean", -7, 5, 1, "It stops at the signature. Only a person signs."),
    ("card:honest", 0, 6, 1, ""),
    ("card:vision", 0, 6, 1, ""),
    ("card:end", 0, 7, 1, ""),
]

TEASER = [
    ("card:hook", 0, 6, 1, ""),
    ("swarm", 60, 5, 40, "One small open model, on my desk, running apps built for people. No cloud."),
    ("teach", 16, 5, 12, "Meta's frontier models learn an app once..."),
    ("run", 20, 6, 4, "...and compile it, so a small model runs it on my computer, every step checked."),
    ("agent", 10, 6, 5, "Every job becomes a tool any agent can call. The agent never sees the screen."),
    ("robots", "started", 6, 10, "Games too. Given the manual, it learned GNOME Robots' keys and cleared level 1, five of five."),
    ("card:plug", 0, 4, 1, ""),
    ("card:table", 0, 6, 1, ""),
    ("card:end", 0, 5, 1, ""),
]


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def marks(clip: str) -> dict:
    """Named moments in a recording, written next to it by make_clips.py, so a cut can say "plan" instead of a guessed second."""
    f = CLIPS / f"{clip}.marks.json"
    return json.loads(f.read_text()) if f.exists() else {}


def render(cut: list, out: Path, save_cards: bool) -> None:
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": W, "height": H})
        parts = []
        for n, (clip, start, length, speed, caption) in enumerate(cut):
            part = Path(tmp) / f"{n}.mp4"
            fade = f"fade=t=in:st=0:d=0.3:color=0x{BG}"
            if clip.startswith("card:"):
                png = Path(tmp) / f"card{n}.png"
                page.set_content(STYLE + card_html(clip[5:]))
                page.wait_for_timeout(700)
                page.screenshot(path=str(png))
                if save_cards:
                    (CLIPS / "cards").mkdir(exist_ok=True)
                    (CLIPS / "cards" / f"{clip[5:]}.png").write_bytes(png.read_bytes())
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-t", str(length), "-r", str(FPS), "-vf", f"{fade},format=yuv420p",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(part)], check=True)
            else:
                source = CLIPS / f"{clip}.mp4"
                if not source.exists():
                    sys.exit(f"missing {source}: run scripts/make_clips.py {clip}")
                total = duration(source)
                if isinstance(start, str):
                    start = marks(clip).get(start, 0)
                at = max(0.0, total + start if start < 0 else start)
                at = min(at, max(0.0, total - 1))
                png = Path(tmp) / f"over{n}.png"
                page.set_content(STYLE + overlay_html(caption, speed))
                page.wait_for_timeout(300)
                page.screenshot(path=str(png), omit_background=True)
                graph = (f"[0:v]setpts=PTS/{speed},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:0x{BG},"
                         f"tpad=stop_mode=clone:stop_duration={length},fps={FPS}[v];[v][1:v]overlay=0:0,{fade},format=yuv420p")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(at), "-t", str(length * speed), "-i", str(source), "-i", str(png), "-filter_complex", graph,
                                "-t", str(length), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(part)], check=True)
            parts.append(part)
        browser.close()
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{q}'\n" for q in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    print(out, round(duration(out)), "s")


if __name__ == "__main__":
    which = (sys.argv[1:] or ["both"])[0]
    save = "--cards" in sys.argv
    if which in ("draft", "both"):
        render(DRAFT, CLIPS / "draft.mp4", save)
    if which in ("teaser", "both"):
        render(TEASER, CLIPS / "teaser.mp4", save)
