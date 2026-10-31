"""Screenshots of the web app in a real browser, for checking the design. usage: shot.py URL OUT [WIDTH HEIGHT]"""
import sys

from playwright.sync_api import sync_playwright

url, out = sys.argv[1], sys.argv[2]
w, h = int(sys.argv[3]) if len(sys.argv) > 3 else 1440, int(sys.argv[4]) if len(sys.argv) > 4 else 900
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox"])
    page = b.new_page(viewport={"width": w, "height": h})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    page.screenshot(path=out, full_page=len(sys.argv) > 5)
    print("page errors:", errors)
    b.close()
