#!/usr/bin/env python3
"""Copies the compiled plans into the repo with what the app needs to run them: the interface, sample inputs, and made-up inputs for a swarm.
A plan is the entire output of teaching, and it holds no key or real data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "priorauth"), str(Path(__file__).parent)]
from autoharness import config  # noqa: E402

import jobs as J  # noqa: E402

OUT = ROOT / "plans" / "ui"
OUT.mkdir(parents=True, exist_ok=True)
NAMES = {"portal": "A made-up insurer's portal", "openemr": "OpenEMR", "openemr-chart": "OpenEMR, reading whole charts", "backoffice": "A Django admin back office", "calculator": "GNOME Calculator"}
for app, title in NAMES.items():
    file = config.HOME / "uiteam" / app / "plan.json"
    if not file.exists():
        continue
    plan = json.loads(file.read_text())
    plan["app"] = title
    plan["target"] = J.APPS[app]["spec"]()
    samples = {}
    for job, info in J.APPS[app]["jobs"].items():
        skill = info.get("skill") or plan.get("jobs", {}).get(job) or job
        inputs = info["inputs"](1)
        samples[skill] = info["plan_inputs"](inputs) if info.get("plan_inputs") else inputs
    plan["samples"] = samples
    if app == "portal":
        plan["swarm_inputs"] = [J.portal_inputs(c) for c in json.loads((ROOT / "scripts" / "priorauth" / "swarm_cases.json").read_text())]
    plan["jobs"] = {job: info.get("skill") or plan.get("jobs", {}).get(job) or job for job, info in J.APPS[app]["jobs"].items()}
    for target in (file, OUT / f"{app}.json"):
        target.write_text(json.dumps(plan, indent=1))
    print(app, "shipped")
