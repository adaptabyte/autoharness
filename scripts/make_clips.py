#!/usr/bin/env python3
"""Records the real app, on real runs, into clips/ for the demo video. Nothing is mocked.
  make_clips.py home run swarm digit clean teach
Needs the app on :4140, Glimmer, and the portal. teach spends real money, about $0.40."""
from __future__ import annotations

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


def record(name: str, body) -> Path:
    tmp = tempfile.mkdtemp()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=tmp, record_video_size={"width": 1280, "height": 720})
        pg = ctx.new_page()
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
            opt.click()
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
    fields.nth(1).type("Log in with username manager and password demo-pass. Find order ORD-10530 and report its total and customer.", delay=12)
    pg.wait_for_timeout(1000)
    pg.click("button:has-text('Teach it')")
    pg.wait_for_selector(".live", timeout=30000)
    pg.wait_for_selector(".verdict", timeout=900 * 1000)
    pg.wait_for_timeout(5000)


CLIPSET = {"home": home, "run": run, "swarm": swarm, "digit": paperwork("One wrong digit"), "stray": paperwork("Someone else"), "clean": paperwork("A clean stack"), "invoice": paperwork("An invoice"), "teach": teach}

if __name__ == "__main__":
    for name in sys.argv[1:] or list(CLIPSET):
        record(name, CLIPSET[name])
