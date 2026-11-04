#!/usr/bin/env python3
"""Records the real app, on real runs, into clips/ for the demo video. Nothing is mocked.
  make_clips.py home run swarm digit clean teach
Needs the app on :4140, Glimmer, and the portal. teach spends real money, about $0.40."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4140"
CLIPS = Path(__file__).resolve().parents[1] / "clips"
SHOP = "http://127.0.0.1:8320/admin/"
TEACH_JOB = "Log in with username manager and password demo-pass. Find the customer named Theo Rasmussen and report their email and city."
ASK = "What email and city do we have on file for Astrid Kowalczyk?"


MARKS: dict[str, float] = {}
START = [0.0]


def mark(name: str) -> None:
    """A named moment, in seconds into the recording, so the video can cut to it instead of a guessed second."""
    MARKS[name] = round(time.time() - START[0], 1)


def record(name: str, body) -> Path:
    tmp = tempfile.mkdtemp()
    MARKS.clear()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=tmp, record_video_size={"width": 1280, "height": 720})
        pg = ctx.new_page()
        START[0] = time.time()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        t0 = time.time()
        body(pg)
        ctx.close()
        b.close()
    raw = next(Path(tmp).glob("*.webm"))
    CLIPS.mkdir(exist_ok=True)
    out = CLIPS / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "22", str(out)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    if MARKS:
        (CLIPS / f"{name}.marks.json").write_text(json.dumps(MARKS))
    print(f"{out} {round(time.time() - t0)} s {'ERRORS ' + str(errors) if errors else ''}", flush=True)
    return out


def slow_scroll(pg, seconds: float = 8) -> None:
    height = pg.evaluate("document.documentElement.scrollHeight - innerHeight")
    steps = int(seconds * 10)
    for i in range(steps + 1):
        pg.evaluate(f"scrollTo(0, {height * i / steps})")
        pg.wait_for_timeout(100)


def home(pg):
    pg.goto(BASE + "/")
    pg.wait_for_selector(".drop")
    pg.wait_for_timeout(2500)
    slow_scroll(pg)
    pg.wait_for_timeout(1000)


def wait_verdict(pg, seconds: int) -> None:
    pg.wait_for_selector(".verdict", timeout=seconds * 1000)
    pg.wait_for_timeout(5000)


def run(pg):
    pg.goto(BASE + "/#/ui/portal")
    pg.wait_for_selector("select")
    pg.wait_for_timeout(2500)
    pg.click("button:has-text('Run it on this computer')")
    wait_verdict(pg, 400)


def robots(pg):
    """The program Wonder wrote from GNOME Robots' manual, run as a tool, on this computer."""
    pg.goto(BASE + "/#/ui/robots")
    pg.wait_for_selector("button:has-text('Run it on this computer')")
    pg.wait_for_timeout(2000)
    pg.click("button:has-text('Run it on this computer')")
    mark("started")
    wait_verdict(pg, 420)
    mark("verdict")


def docsdb(pg):
    """The guide that lesson left, live in docsdb."""
    pg.goto("https://autoharness.adaptabyte.com/docsdb/")
    pg.wait_for_timeout(2500)
    pg.goto("https://autoharness.adaptabyte.com/docsdb/gnome-robots/")
    pg.wait_for_timeout(2000)
    slow_scroll(pg, 9)
    pg.wait_for_timeout(1000)


def swarm(pg):
    pg.goto(BASE + "/#/ui/portal")
    pg.wait_for_selector("select")
    pg.wait_for_timeout(1500)
    pg.click("button:has-text('at once')")
    pg.wait_for_selector(".swarm .card")
    pg.wait_for_function("document.querySelector('.reading h1').innerText.includes('finished and verified')", timeout=1200 * 1000)
    pg.wait_for_timeout(5000)


def paperwork(sample_title: str):
    def body(pg):
        pg.goto(BASE + "/")
        pg.wait_for_selector(".drop")
        pg.locator(f".sample:has-text('{sample_title}')").scroll_into_view_if_needed()
        pg.wait_for_timeout(1500)
        pg.click(f".sample:has-text('{sample_title}')")
        pg.wait_for_selector(".verdict", timeout=200 * 1000)
        pg.wait_for_timeout(5000)
        for opt in pg.locator(".opt").all()[:1]:
            opt.locator("span").click()  # the image opens a zoom, and the label just chooses
            pg.wait_for_timeout(2500)
        approve = pg.locator("button:has-text('Approve')").first
        if approve.is_enabled() and sample_title == "A clean stack":
            approve.click()
            pg.wait_for_selector(".live", timeout=30000)
            wait_verdict(pg, 400)
    return body


def teach(pg):
    pg.goto(BASE + "/")
    pg.wait_for_selector(".drop")
    pg.wait_for_timeout(1500)
    fields = pg.locator(".card input[type=text]")
    fields.nth(0).type(SHOP, delay=25)
    fields.nth(1).type(TEACH_JOB, delay=12)
    pg.wait_for_timeout(1000)
    pg.click("button:has-text('Teach it')")
    pg.wait_for_selector(".live", timeout=30000)
    mark("start")
    pg.wait_for_selector(".feed :text('Plan written')", timeout=900 * 1000)
    mark("plan")
    pg.wait_for_selector(".verdict", timeout=900 * 1000)
    mark("verdict")
    pg.wait_for_timeout(5000)


AGENT_PAGE = r"""<!doctype html><meta charset=utf-8><style>
body{margin:0;display:grid;grid-template-columns:420px 860px;height:720px;background:#f6f5f1;font:15px/1.45 "DejaVu Sans Mono",monospace;overflow:hidden}
.term{background:#14191a;color:#d7dcd9;padding:18px 18px 0;overflow:hidden;display:flex;flex-direction:column}
.bar{display:flex;gap:7px;margin:0 0 12px}.bar i{width:11px;height:11px;border-radius:50%;background:#3b4442}
.title{color:#7d8a85;font-size:12.5px;margin:-4px 0 12px}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font:inherit;flex:1;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end}
.g{color:#7d8a85}.b{color:#fff;font-weight:700}.ok{color:#5fd39a}.warn{color:#f0b35a}
.app{position:relative;overflow:hidden}iframe{border:0;width:1280px;height:1056px;transform:scale(.671875);transform-origin:0 0;background:#f6f5f1}
</style><div class=term><div class=bar><i></i><i></i><i></i></div><div class=title>any agent, over MCP: scripts/ask.py</div><pre><div id=log></div></pre></div><div class=app><iframe id=app src="http://127.0.0.1:4140/"></iframe></div>
<script>
const esc=t=>t.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"})[c]);
const ansi=t=>esc(t).replace(/\x1b\[90m/g,'<span class=g>').replace(/\x1b\[1m/g,'<span class=b>').replace(/\x1b\[32m/g,'<span class=ok>').replace(/\x1b\[33m/g,'<span class=warn>').replace(/\x1b\[0m/g,'</span>');
setInterval(async()=>{try{const t=await (await fetch('/log')).text();document.getElementById('log').innerHTML=ansi(t)}catch(e){}},300);
</script>"""


def agent(pg):
    """A model asks in plain words; the job runs here. Left: the agent's real terminal output, as it happens. Right: the app, live."""
    import http.server
    import threading
    log = Path(tempfile.mkdtemp()) / "ask.log"
    log.write_text("")

    class Page(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            data = (log.read_bytes() if self.path == "/log" else AGENT_PAGE.encode())
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8" if self.path == "/log" else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
    app = pg.frame_locator("#app")
    app.locator(".drop").wait_for()
    pg.wait_for_timeout(2500)
    with log.open("w") as out:
        proc = subprocess.Popen([sys.executable, "-u", str(CLIPS.parent / "scripts" / "ask.py"), ASK], stdout=out, stderr=subprocess.STDOUT, cwd=CLIPS.parent)
        app.locator(".live-pill").first.wait_for(timeout=120000)
        pg.wait_for_timeout(1200)
        app.locator(".live-pill").first.click()
        mark("running")
        while proc.poll() is None:
            pg.wait_for_timeout(500)
    pg.wait_for_timeout(7000)
    srv.shutdown()
    print(log.read_text())


STILL = """<!doctype html><style>body{margin:0;background:#f6f5f1;color:#17201c;font:20px/1.4 Arial,sans-serif;padding:34px 52px}h1{font-size:34px;margin:0 0 6px;letter-spacing:-.02em}p{color:#5f6a64;margin:0 0 18px;font-size:18px}table{border-collapse:collapse;width:100%%;background:#fff;font-size:18px}td,th{padding:10px 14px;text-align:left;border-bottom:1px solid #e1dfd7}th{color:#5f6a64;font-size:15px;font-weight:600}b{font-weight:700}.us{color:#116149}li{margin:0 0 13px;font-size:21px}ul{padding-left:24px}</style>%s"""


def table(pg):
    import json
    data = json.loads((CLIPS.parent / "docs" / "paperwork-final.json").read_text())
    rows = "".join("<tr>" + "".join(f"<td>{'<b class=us>' + c + '</b>' if i == 1 else c}</td>" for i, c in enumerate(r)) + "</tr>" for r in data["rows"])
    pg.set_content(STILL % f"<h1>{data['title']}</h1><p>{data['note']}</p><table><tr>{''.join(f'<th>{c}</th>' for c in data['columns'])}</tr>{rows}</table>")
    pg.wait_for_timeout(24000)


def failed(pg):
    items = ["Patching a plan again and again made it worse. It overfit to one patient and went 0 of 5 on new ones.", "The first paperwork test failed its bar, because my own code skipped a date check.", "On rental applications it let through one missing date.", "A swarm barely adds speed on this hardware.", "Spark still wins anything it wasn't taught, and costs only cents on small jobs.", "All data is made up, and it isn't ready for real patients."]
    pg.set_content(STILL % f"<h1>What failed</h1><p>Every run is in the repo.</p><ul>{''.join(f'<li>{i}</li>' for i in items)}</ul>")
    pg.wait_for_timeout(8000)


CLIPSET = {"robots": robots, "docsdb": docsdb, "agent": agent, "table": table, "failed": failed, "home": home, "run": run, "swarm": swarm, "digit": paperwork("One wrong digit"), "stray": paperwork("Someone else"), "clean": paperwork("A clean stack"), "invoice": paperwork("An invoice"), "teach": teach}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(CLIPSET):
        record(name, CLIPSET[name])
