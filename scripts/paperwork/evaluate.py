#!/usr/bin/env python3
"""Score the reading team against the truth, on packets it has never seen.
  evaluate.py <packets dir> <plan.json> --label NAME [--mode team|one|both] [--limit N]

The pass bar was written here before the first run of this test, and isn't to be moved after a result:
  - wrong_saved == 0: no packet cleared with a wrong value or an undetected defect
  - defects caught for the right reason >= 90%
  - clean packets cleared on their own >= 60%: a system that sends everything to a person isn't useful
  - median under 30 s per packet
Results are appended to docs/paperwork.jsonl."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from autoharness import team  # noqa: E402

OUT = ROOT / "docs" / "paperwork.jsonl"


def truth_errors(result: dict, truth: dict, plan: dict) -> list[str]:
    """Every settled value that differs from the truth."""
    wrong = []
    by = {f["key"]: f for f in result["fields"]}
    kinds = {f["key"]: f.get("type", "text") for f in plan["fields"]}
    names = {"patient_name": truth["name"]}
    for key, f in by.items():
        want = names.get(key, truth.get(key))
        if want is None:
            continue
        if team.normal(f["value"], kinds[key]) != team.normal(want, kinds[key]):
            wrong.append(f"{key}: {f['value']!r}, truth {want!r}")
    rows = result["tables"][0]["rows"]
    got = sorted((team.normal(r["cells"]["drug"]["value"]), team.normal(r["cells"]["start"]["value"], "date"), team.normal(r["cells"]["end"]["value"], "date"), team.normal(r["cells"]["outcome"]["value"])) for r in rows)
    want = sorted((team.normal(t["drug"]), t["start"], t["end"], team.normal(t["outcome"])) for t in truth["trials"])
    if got != want:
        wrong.append(f"treatments: {got}, truth {want}")
    return wrong


def score(result: dict, info: dict, plan: dict) -> dict:
    routed = result["status"] != "clear"
    kinds = sorted({i["kind"] for i in result["issues"]})
    touched = {i.get("field", "").split(".")[0] for i in result["issues"]} | {i["kind"] for i in result["issues"]}
    expect = info["expect"]
    if not expect["route"]:
        errors = truth_errors(result, info["truth"], plan) if not routed else []
        verdict = "cleared_right" if not routed and not errors else ("WRONG_SAVED" if not routed else "false_alarm")
        return dict(verdict=verdict, errors=errors, kinds=kinds)
    if not routed:
        return dict(verdict="WRONG_SAVED", errors=[f"missed planted {expect['defect']}"], kinds=kinds)
    want = set(expect["why"])
    # A gap counts as caught if the row check fired, or the empty cell's own row was flagged.
    if "gap" in want and any(i["kind"] in ("gap", "missing", "unconfirmed") and i.get("field", "").startswith("prior_treatments") for i in result["issues"]):
        return dict(verdict="caught", errors=[], kinds=kinds)
    return dict(verdict="caught" if want & touched else "routed_other_reason", errors=[], kinds=kinds)


def run_mode(label: str, mode: str, plan: dict, manifest: list[dict], packets: Path) -> dict:
    readers = plan["readers"] if mode == "team" else plan["readers"][:1]
    support = 2 if mode == "team" else 1
    records = []
    for info in manifest:
        result = team.process(plan, [packets / p for p in info["pages"]], readers=readers, min_support=support)
        verdict = score(result, info, plan)
        rec = dict(run=label, mode=mode, packet=info["id"], condition=info["condition"], defect=info["defect"], seconds=result["seconds"], reads=result["reads"], status=result["status"],
                   issues=[{k: i.get(k) for k in ("kind", "field", "text")} | ({"votes": [v["value"] for v in i["votes"]]} if i.get("votes") else {}) for i in result["issues"]], **verdict, at=time.time())
        records.append(rec)
        with OUT.open("a") as f:
            f.write(json.dumps(team.jsonable(rec)) + "\n")
        print(f"{mode} {info['id']} {info['condition']:12} {info['defect']:16} {verdict['verdict']:20} {result['seconds']:5.1f} s {[i['field'] or i['kind'] for i in result['issues']][:6]} {verdict['errors'][:2]}"[:300], flush=True)
    return summarize(mode, records)


def summarize(mode: str, records: list[dict]) -> dict:
    n = lambda v: sum(r["verdict"] == v for r in records)
    clean = [r for r in records if r["defect"] == "clean"]
    defects = [r for r in records if r["defect"] != "clean"]
    out = dict(mode=mode, packets=len(records), wrong_saved=n("WRONG_SAVED"), defects_caught=f"{n('caught')}/{len(defects)}", routed_other_reason=n("routed_other_reason"), clean_cleared=f"{n('cleared_right')}/{len(clean)}", false_alarms=n("false_alarm"),
               median_s=round(statistics.median(r["seconds"] for r in records), 1), reads=sum(r["reads"] for r in records))
    out["passes_bar"] = (n("WRONG_SAVED") == 0 and n("caught") >= .9 * len(defects) and n("cleared_right") >= .6 * len(clean) and out["median_s"] < 30)
    by = {}
    for r in records:
        by.setdefault(r["condition"], []).append(r["verdict"])
    out["by_condition"] = {k: {x: v.count(x) for x in sorted(set(v))} for k, v in by.items()}
    print(json.dumps(out, indent=1), flush=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("packets", type=Path)
    ap.add_argument("plan", type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--mode", default="both")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    plan = team.check_plan(json.loads(a.plan.read_text()))
    manifest = json.loads((a.packets / "manifest.json").read_text())[:a.limit]
    for mode in ("team", "one") if a.mode == "both" else (a.mode,):
        run_mode(a.label, mode, plan, manifest, a.packets)
