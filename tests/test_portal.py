"""The portal's one promise: nothing reaches the plan without the prescriber's PIN, and bad requests can't be saved."""
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8319"  # its own copy, with its own records, never the one a run is using


@pytest.fixture(scope="module")
def portal(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    p = subprocess.Popen([sys.executable, str(ROOT / "scripts/priorauth/portal.py")], env={"HOME": str(home), "PORTAL_PORT": "8319"})
    time.sleep(1)
    yield
    p.terminate()


def client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def post(c, path, **fields):
    return c.open(BASE + path, urllib.parse.urlencode(fields).encode(), timeout=5)


def fill(c, case):
    post(c, "/login", user="clinic01", password="demo-pass")
    c.open(BASE + "/new", timeout=5)
    post(c, "/step/0", member_id=case["member_id"], dob=case["dob"])
    post(c, "/step/1?pick=1", drug=case["request"]["drug"])
    post(c, "/step/1", drug=case["request"]["drug"], strength=case["request"]["strength"], quantity=30, days=30)
    post(c, "/step/2", search=case["icd10"], do="search")
    post(c, "/step/2", code=case["icd10"])
    for t in case["trials"]:
        post(c, "/step/3", t_drug=t["drug"], t_start=t["start"], t_end=t["end"], t_outcome=t["outcome"], do="add")
    return post(c, "/step/3")


def cases():
    return json.loads((ROOT / "scripts/priorauth/cases.json").read_text())


def saved():
    return json.loads(urllib.request.urlopen(BASE + "/_requests.json", timeout=5).read())


def test_only_the_pin_submits(portal):
    case = cases()[0]
    c = client()
    fill(c, case)
    page = post(c, "/step/4")
    ref = page.geturl().rsplit("/", 1)[1]
    row = next(r for r in saved() if r["ref"] == ref)
    assert row["status"] == "Awaiting prescriber signature"
    assert "That PIN is not right" in post(c, f"/sign/{ref}", pin="0000").read().decode()
    assert next(r for r in saved() if r["ref"] == ref)["status"] == "Awaiting prescriber signature"
    post(c, f"/sign/{ref}", pin="4711")
    assert next(r for r in saved() if r["ref"] == ref)["status"] == "Submitted to the plan"


def test_one_prior_treatment_cannot_be_saved(portal):
    case = next(x for x in cases() if x["id"] == "incomplete")
    c = client()
    post(c, "/login", user="clinic01", password="demo-pass")
    c.open(BASE + "/new", timeout=5)
    post(c, "/step/0", member_id=case["member_id"], dob=case["dob"])
    assert "needs a medication, start date" in post(c, "/step/3", t_drug="Fluoxetine 40 mg", t_start="2025-05-12", t_end="", t_outcome="", do="add").read().decode()
    assert "at least 2 prior treatments" in post(c, "/step/3").read().decode()
