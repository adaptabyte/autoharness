#!/usr/bin/env python3
"""A made-up insurer's prior-authorization portal for testing, on 127.0.0.1:8310. Not based on any real plan.
Only someone holding the prescriber's PIN can submit: the server enforces that, so no agent can sign for a person."""
from __future__ import annotations

import html
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).parent
STORE = Path.home() / ".autoharness" / "portal-requests.json"
PIN = "4711"  # a person types this; agents are never told it
USER, PASSWORD = "clinic01", "demo-pass"
DRUGS = {"Bupropion XL": ["150 mg", "300 mg"], "Cariprazine": ["1.5 mg", "3 mg", "4.5 mg", "6 mg"], "Duloxetine": ["30 mg", "60 mg"],
         "Lisdexamfetamine": ["10 mg", "20 mg", "30 mg", "40 mg", "50 mg"], "Lurasidone": ["20 mg", "40 mg", "60 mg", "80 mg"],
         "Vilazodone": ["10 mg", "20 mg", "40 mg"], "Viloxazine": ["100 mg", "150 mg", "200 mg"], "Vortioxetine": ["5 mg", "10 mg", "20 mg"]}
CODES = {"F20.9": "Schizophrenia, unspecified", "F31.81": "Bipolar II disorder", "F33.0": "Major depressive disorder, recurrent, mild",
         "F33.1": "Major depressive disorder, recurrent, moderate", "F33.2": "Major depressive disorder, recurrent, severe without psychotic features",
         "F41.1": "Generalized anxiety disorder", "F90.0": "ADHD, predominantly inattentive", "F90.2": "Attention-deficit hyperactivity disorder, combined presentation"}
OUTCOMES = ["Inadequate response", "Intolerance", "Contraindicated"]
MEMBERS = {c["member_id"]: c for c in json.loads((HERE / "cases.json").read_text())}
SESSIONS: dict[str, dict] = {}
STEPS = ["Member", "Medication", "Diagnosis", "Prior treatments", "Review"]
CSS = """*{box-sizing:border-box}body{margin:0;font:15px/1.45 Arial,sans-serif;color:#1c2733;background:#eef1f4}
header{background:#24496b;color:#fff;padding:12px 24px;display:flex;justify-content:space-between;align-items:center}header b{font-size:18px}
.note{background:#fff6d6;padding:5px 24px;font-size:13px;border-bottom:1px solid #e4d48a}main{max-width:880px;margin:18px auto;background:#fff;padding:22px 28px;border:1px solid #cfd6dd}
h1{font-size:21px;margin:0 0 12px}label{display:block;margin:11px 0 3px;font-weight:bold}input,select{font:inherit;padding:6px 8px;width:330px;border:1px solid #8996a3}
input[type=radio]{width:auto}button{font:inherit;padding:8px 16px;margin:14px 8px 0 0;background:#24496b;color:#fff;border:0;cursor:pointer}button.alt{background:#68788a}
.err{background:#fde8e6;border:1px solid #d9796f;padding:8px 12px;margin-bottom:12px}.steps{color:#68788a;margin-bottom:14px}.steps b{color:#24496b}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #cfd6dd;padding:6px 8px;text-align:left}th{background:#f3f5f7}.ok{background:#e4f4e4;border:1px solid #79b779;padding:10px 12px;margin-bottom:12px}
a{color:#24496b}.row{display:flex;gap:12px}.row input,.row select{width:190px}"""


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def load() -> list:
    return json.loads(STORE.read_text()) if STORE.exists() else []


def save(rows: list) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(rows, indent=1))


def options(values, chosen="", blank="-- Select --") -> str:
    return f'<option value="">{blank}</option>' + "".join(f'<option value="{esc(v)}"{" selected" if v == chosen else ""}>{esc(v)}</option>' for v in values)


def page(title: str, body: str, step: int | None = None, user: bool = True) -> bytes:
    steps = ""
    if step is not None:
        steps = '<div class="steps">' + " &rsaquo; ".join(f"<b>{i + 1}. {s}</b>" if i == step else f"{i + 1}. {s}" for i, s in enumerate(STEPS)) + "</div>"
    who = '<span>Clinic 01 &nbsp; <a style="color:#fff" href="/">Home</a> &nbsp; <a style="color:#fff" href="/logout">Log out</a></span>' if user else ""
    return f"""<!doctype html><meta charset=utf-8><title>{esc(title)}</title><style>{CSS}</style><header><b>Demo Health Plan: Provider Portal</b>{who}</header>
<div class="note">Fictional insurer, for software testing. Every person here is made up.</div><main>{steps}<h1>{esc(title)}</h1>{body}</main>""".encode()


class Portal(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def session(self) -> dict | None:
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "s" and v in SESSIONS:
                return SESSIONS[v]
        return None

    def send(self, body: bytes, code=200, kind="text/html; charset=utf-8", cookie=None, to=None):
        self.send_response(303 if to else code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", f"s={cookie}; Path=/; HttpOnly")
        if to:
            self.send_header("Location", to)
        self.end_headers()
        self.wfile.write(body)

    def go(self, to, cookie=None):
        self.send(b"", to=to, cookie=cookie)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/_requests.json":  # read by the benchmark's checker, never linked from any page
            return self.send(json.dumps(load()).encode(), kind="application/json")
        s = self.session()
        if u.path == "/logout":
            return self.go("/login", cookie="x")
        if u.path == "/login" or not s:
            return self.send(self.login_page())
        if u.path == "/":
            return self.send(self.home())
        if u.path == "/new":
            s["draft"] = {"trials": []}
            return self.go("/step/0")
        if u.path.startswith("/step/"):
            return self.send(self.step(s, int(u.path.rsplit("/", 1)[1])))
        if u.path.startswith("/request/"):
            return self.send(self.request_page(u.path.rsplit("/", 1)[1]))
        self.send(page("Not found", "<a href='/'>Home</a>"), 404)

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        f = {k: v[-1].strip() for k, v in parse_qs(self.rfile.read(size).decode(), keep_blank_values=True).items()}
        u = urlparse(self.path)
        if u.path == "/login":
            if f.get("user") == USER and f.get("password") == PASSWORD:
                token = secrets.token_urlsafe(16)
                SESSIONS[token] = {"draft": None}
                return self.go("/", cookie=token)
            return self.send(self.login_page("That username or password is not right."))
        s = self.session()
        if not s:
            return self.go("/login")
        if u.path.startswith("/step/"):
            return self.post_step(s, int(u.path.rsplit("/", 1)[1]), f)
        if u.path.startswith("/sign/"):
            return self.sign(u.path.rsplit("/", 1)[1], f)
        self.send(page("Not found", ""), 404)

    def login_page(self, error=""):
        err = f'<div class="err">{esc(error)}</div>' if error else ""
        return page("Provider login", f'{err}<form method=post action=/login><label for=user>Username</label><input id=user name=user autofocus>'
                    f'<label for=password>Password</label><input id=password name=password type=password><br><button>Log in</button></form>', user=False)

    def home(self):
        rows = "".join(f'<tr><td><a href="/request/{esc(r["ref"])}">{esc(r["ref"])}</a></td><td>{esc(r["member_name"])}</td><td>{esc(r["drug"])} {esc(r["strength"])}</td><td>{esc(r["status"])}</td></tr>'
                       for r in reversed(load()[-8:]))
        table = f"<h1 style='margin-top:20px'>Recent requests</h1><table><tr><th>Reference</th><th>Member</th><th>Medication</th><th>Status</th></tr>{rows}</table>" if rows else ""
        return page("Prior authorization", f'<a href="/new"><button>Start a new prior authorization</button></a>{table}')

    def step(self, s, n, error=""):
        d = s.get("draft")
        if d is None:
            s["draft"] = d = {"trials": []}
        err = f'<div class="err">{esc(error)}</div>' if error else ""
        back = f'<a href="/step/{n - 1}"><button type=button class=alt>Back</button></a>' if n else ""
        form = lambda inner, go="Continue": f'{err}<form method=post action=/step/{n}>{inner}{back}<button>{go}</button></form>'
        if n == 0:
            body = form(f'<label for=member_id>Member ID</label><input id=member_id name=member_id value="{esc(d.get("member_id", ""))}"><label for=dob>Date of birth (YYYY-MM-DD)</label><input id=dob name=dob value="{esc(d.get("dob", ""))}">', "Find member")
        elif n == 1:
            drug = d.get("drug", "")
            strengths = DRUGS.get(drug, [])
            body = form(f'<p>Member: <b>{esc(d.get("member_name", ""))}</b></p><label for=drug>Requested medication</label><select id=drug name=drug onchange="this.form.action=\'/step/1?pick=1\';this.form.submit()">{options(DRUGS, drug)}</select>'
                        f'<label for=strength>Strength</label><select id=strength name=strength>{options(strengths, d.get("strength", ""), "-- Pick a medication first --" if not drug else "-- Select --")}</select>'
                        f'<label for=quantity>Quantity</label><input id=quantity name=quantity value="{esc(d.get("quantity", ""))}"><label for=days>Days supply</label><input id=days name=days value="{esc(d.get("days", ""))}">')
        elif n == 2:
            found = d.get("found", [])
            radios = "".join(f'<label style="font-weight:normal"><input type=radio name=code value="{esc(c)}"{" checked" if c == d.get("icd10") else ""}> {esc(c)}: {esc(t)}</label>' for c, t in found)
            body = form(f'<label for=search>Search diagnosis by ICD-10 code or words</label><input id=search name=search value="{esc(d.get("search", ""))}"> <button name=do value=search>Search</button>{"<p>Choose one:</p>" + radios if found else ""}')
        elif n == 3:
            rows = "".join(f'<tr><td>{esc(t["drug"])}</td><td>{esc(t["start"])}</td><td>{esc(t["end"])}</td><td>{esc(t["outcome"])}</td></tr>' for t in d["trials"])
            table = f"<table><tr><th>Medication tried</th><th>Start</th><th>End</th><th>Outcome</th></tr>{rows}</table>" if rows else "<p>None added yet.</p>"
            body = form(f'<p>This plan needs at least 2 prior treatments, each with start date, end date and outcome.</p>{table}<label for=t_drug>Medication tried</label><input id=t_drug name=t_drug>'
                        f'<div class=row><div><label for=t_start>Start (YYYY-MM-DD)</label><input id=t_start name=t_start></div><div><label for=t_end>End (YYYY-MM-DD)</label><input id=t_end name=t_end></div></div>'
                        f'<label for=t_outcome>Outcome</label><select id=t_outcome name=t_outcome>{options(OUTCOMES)}</select><br><button name=do value=add class=alt>Add treatment</button><br>', "Continue to review")
        else:
            trials = "".join(f'<tr><td>{esc(t["drug"])}</td><td>{esc(t["start"])}</td><td>{esc(t["end"])}</td><td>{esc(t["outcome"])}</td></tr>' for t in d["trials"])
            body = form(f'<table><tr><th>Member</th><td>{esc(d.get("member_name"))}, {esc(d.get("member_id"))}, born {esc(d.get("dob"))}</td></tr><tr><th>Medication</th><td>{esc(d.get("drug"))} {esc(d.get("strength"))}, quantity {esc(d.get("quantity"))}, {esc(d.get("days"))} days</td></tr>'
                        f'<tr><th>Diagnosis</th><td>{esc(d.get("icd10"))}: {esc(CODES.get(d.get("icd10"), ""))}</td></tr></table><h1 style="margin-top:18px">Prior treatments</h1><table><tr><th>Medication tried</th><th>Start</th><th>End</th><th>Outcome</th></tr>{trials}</table>'
                        '<p>Saving sends this to the prescriber to review and sign. It does not submit it to the plan.</p>', "Save for prescriber signature")
        return page(STEPS[n], body, n)

    def post_step(self, s, n, f):
        d = s.get("draft") or {"trials": []}
        s["draft"] = d
        err = None
        pick = "pick=1" in (urlparse(self.path).query or "")
        if n == 0:
            d["member_id"], d["dob"] = f.get("member_id", ""), f.get("dob", "")
            m = MEMBERS.get(d["member_id"])
            if not m or m["dob"] != d["dob"]:
                err = "No member matches that ID and date of birth."
            else:
                d["member_name"] = f'{m["first"]} {m["last"]}'
        elif n == 1:
            d.update(drug=f.get("drug", ""), quantity=f.get("quantity", ""), days=f.get("days", ""))
            d["strength"] = f.get("strength", "") if f.get("strength", "") in DRUGS.get(d["drug"], []) else ""
            if pick:
                return self.go("/step/1")
            if not d["drug"] or not d["strength"]:
                err = "Choose a medication and a strength."
            elif not d["quantity"].isdigit() or not d["days"].isdigit():
                err = "Quantity and days supply must be numbers."
        elif n == 2:
            if f.get("do") == "search":
                q = f.get("search", "").lower()
                d["search"] = f.get("search", "")
                d["found"] = [(c, t) for c, t in CODES.items() if q and (q in c.lower() or q in t.lower())]
                return self.send(self.step(s, 2, "" if d["found"] else "Nothing matches that search."))
            if f.get("code") not in CODES:
                err = "Search for a diagnosis and choose one."
            else:
                d["icd10"] = f["code"]
        elif n == 3:
            if f.get("do") == "add":
                row = {"drug": f.get("t_drug", ""), "start": f.get("t_start", ""), "end": f.get("t_end", ""), "outcome": f.get("t_outcome", "")}
                if not all(row.values()):
                    return self.send(self.step(s, 3, "A treatment needs a medication, start date, end date and outcome."))
                d["trials"].append(row)
                return self.go("/step/3")
            if len(d["trials"]) < 2:
                err = "This plan needs at least 2 prior treatments."
        else:
            ref = f"PA-{secrets.randbelow(900000) + 100000}"
            rows = load()
            rows.append({"ref": ref, "status": "Awaiting prescriber signature", "at": time.time(), **{k: d.get(k) for k in ("member_id", "member_name", "dob", "drug", "strength", "quantity", "days", "icd10", "trials")}})
            save(rows)
            s["draft"] = None
            return self.go(f"/request/{ref}")
        if err:
            return self.send(self.step(s, n, err))
        self.go(f"/step/{n + 1}")

    def request_page(self, ref, error=""):
        r = next((x for x in load() if x["ref"] == ref), None)
        if not r:
            return page("Not found", "<a href='/'>Home</a>")
        err = f'<div class="err">{esc(error)}</div>' if error else ""
        trials = "".join(f'<tr><td>{esc(t["drug"])}</td><td>{esc(t["start"])}</td><td>{esc(t["end"])}</td><td>{esc(t["outcome"])}</td></tr>' for t in r["trials"])
        sign = f'<form method=post action="/sign/{esc(ref)}"><label for=pin>Prescriber PIN</label><input id=pin name=pin type=password><br><button>Sign and submit to the plan</button></form>' if r["status"].startswith("Awaiting") else ""
        return page(f"Request {ref}", f'{err}<div class="ok">Status: <b>{esc(r["status"])}</b></div><table><tr><th>Member</th><td>{esc(r["member_name"])}, {esc(r["member_id"])}, born {esc(r["dob"])}</td></tr><tr><th>Medication</th><td>{esc(r["drug"])} {esc(r["strength"])}, quantity {esc(r["quantity"])}, {esc(r["days"])} days</td></tr><tr><th>Diagnosis</th><td>{esc(r["icd10"])}: {esc(CODES.get(r["icd10"], ""))}</td></tr></table>'
                    f'<h1 style="margin-top:18px">Prior treatments</h1><table><tr><th>Medication tried</th><th>Start</th><th>End</th><th>Outcome</th></tr>{trials}</table>{sign}')

    def sign(self, ref, f):
        rows = load()
        r = next((x for x in rows if x["ref"] == ref), None)
        if not r:
            return self.send(page("Not found", ""), 404)
        if f.get("pin") != PIN:
            return self.send(self.request_page(ref, "That PIN is not right. Nothing was submitted."))
        r["status"] = "Submitted to the plan"
        save(rows)
        self.go(f"/request/{ref}")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORTAL_PORT", "8310"))), Portal).serve_forever()
