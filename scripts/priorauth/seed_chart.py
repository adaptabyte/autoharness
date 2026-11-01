#!/usr/bin/env python3
"""Put the made-up patients from cases.json into the local OpenEMR. Safe to run twice: existing patients are skipped."""
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

B = "http://127.0.0.1:8300"
CASES = json.loads((Path(__file__).parent / "cases.json").read_text())


def issue(pg, pid, kind, title, begin="", end="", comments="", diagnosis=""):
    pg.goto(f"{B}/interface/patient_file/summary/add_edit_issue.php?issue=0&thistype={kind}&thispid={pid}")
    pg.wait_for_timeout(700)
    pg.fill("[name=form_title]", title)
    if begin:
        pg.fill("[name=form_begin]", begin)
    if end:
        pg.fill("[name=form_end]", end)
    if comments:
        pg.fill("[name=form_comments]", comments)
    pg.keyboard.press("Escape")
    # Outside OpenEMR's tab frame this page reloads and resubmits itself after saving, so only the first save may reach the server.
    posts = []

    def once(route):
        if route.request.method == "POST":
            posts.append(1)
            if len(posts) > 1:
                return route.abort()
        route.continue_()

    pg.route("**/add_edit_issue.php*", once)
    with pg.expect_response(lambda r: r.request.method == "POST" and "add_edit_issue" in r.url):
        pg.click("[name=form_save]")
    pg.wait_for_timeout(300)
    pg.unroute("**/add_edit_issue.php*", once)
    pg.goto("about:blank")


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1280, "height": 800})
        pg.on("dialog", lambda d: d.accept())
        pg.goto(B + "/interface/login/login.php?site=default")
        pg.fill("#authUser", "admin")
        pg.fill("#clearPass", "pass")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(4000)
        def find(c):
            pg.goto(B + "/interface/main/finder/dynamic_finder.php")
            pg.wait_for_timeout(2000)
            pg.fill("input[type=search]", c["last"])
            pg.wait_for_timeout(2000)
            ids = pg.evaluate("""([first, last]) => [...document.querySelectorAll('table tbody tr')]
                .filter(r => r.innerText.toLowerCase().startsWith((last + ', ' + first).toLowerCase())).map(r => r.id.replace('pid_', ''))""", [c["first"], c["last"]])
            return ids[0] if ids else None

        for c in CASES:
            pid = find(c)
            if not pid:
                pg.goto(B + "/interface/new/new.php")
                pg.wait_for_timeout(1000)
                pg.fill("[name=form_fname]", c["first"])
                pg.fill("[name=form_lname]", c["last"])
                pg.fill("[name=form_DOB]", c["dob"])
                pg.keyboard.press("Escape")
                pg.select_option("[name=form_sex]", c["sex"])
                pg.fill("[name=form_pubpid]", c["member_id"])
                # The Create button opens a duplicate-check popup that needs OpenEMR's tab frame; this is only test setup, so submit its form directly.
                with pg.expect_navigation():
                    pg.evaluate("document.forms['demographics_form'].submit()")
                pg.wait_for_timeout(2000)
                pid = find(c)
            pg.goto(f"{B}/interface/patient_file/summary/demographics.php?set_pid={pid}")
            pg.wait_for_timeout(1500)
            pg.goto(f"{B}/interface/patient_file/summary/stats_full.php?active=all")
            pg.wait_for_timeout(1200)
            if c["problem"] in pg.evaluate("()=>document.body.innerText"):
                print("already seeded", c["first"], c["last"], "pid", pid)
                continue
            issue(pg, pid, "medical_problem", f'{c["problem"]} ({c["icd10"]})')
            for t in c["trials"]:
                issue(pg, pid, "medication", t["drug"], t["start"], t["end"], (f'Stopped: {t["outcome"].lower()}' if t["outcome"] else ""))
            r = c["request"]
            issue(pg, pid, "medication", f'{r["drug"]} {r["strength"]}', comments=f'New order: quantity {r["quantity"]}, {r["days"]} days supply. Prior authorization needed.')
            pg.goto(f"{B}/interface/patient_file/summary/stats_full.php?active=all")
            pg.wait_for_timeout(1200)
            saved = pg.evaluate("()=>document.body.innerText")
            count = saved.count(c["icd10"]), saved.count(r["drug"]), sum(saved.count(t["drug"]) for t in c["trials"])
            print("seeded", c["first"], c["last"], "pid", pid, "ok" if count == (1, 1, len(c["trials"])) else f"WRONG COUNTS {count}")
        b.close()


main()
