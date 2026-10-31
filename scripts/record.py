"""Records a page of the app to a video file, for the demo. Starts a job if asked.

    python scripts/record.py race minesweeper --seconds 90 --out clips/race.webm
    python scripts/record.py run calculator --seconds 20 --out clips/run.webm
    python scripts/record.py page "#/app/minesweeper" --seconds 8 --out clips/app.webm
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4140"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["race", "run", "session", "page"])
    ap.add_argument("what", help="an app id, or a page like #/app/name")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--out", default="clips/clip.webm")
    ap.add_argument("--ask", help="for session: what to ask Glimmer")
    ap.add_argument("--change-app", action="store_true")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()
    hash_path = args.what
    job = None
    if args.kind != "page":
        path = {"race": "/api/race", "run": "/api/run", "session": "/api/session"}[args.kind]
        job = post(path, {"id": args.what, "change_app": args.change_app})
        hash_path = f"#/job/{job['id']}"
    tmp = tempfile.mkdtemp()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": args.width, "height": args.height}, record_video_dir=tmp,
                                  record_video_size={"width": args.width, "height": args.height}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(f"{BASE}/{hash_path}", wait_until="domcontentloaded")
        if args.ask and job:
            page.wait_for_timeout(1500)
            page.fill("input[placeholder^='Ask']", "")
            page.type("input[placeholder^='Ask']", args.ask, delay=35)
            page.keyboard.press("Enter")
        page.wait_for_timeout(args.seconds * 1000)
        video = page.video
        ctx.close()
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(video.path(), out)
        browser.close()
    if job and args.kind == "session":
        post(f"/api/jobs/{job['id']}/stop", {})
    print(out, round(out.stat().st_size / 1e6, 1), "MB")


if __name__ == "__main__":
    main()
