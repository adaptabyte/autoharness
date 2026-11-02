#!/usr/bin/env python3
"""Does a team designed by Muse Wonder work on paperwork that has nothing to do with clinics?
  evaluate_designed.py design <packets dir>      Wonder sees the one example packet and writes plan.json (costs cloud money, once)
  evaluate_designed.py run <packets dir> --label NAME

The bar, set before the first run and not to be moved after a result: on each kind of paperwork, 12 packets,
  - wrong_saved == 0
  - defects sent to a person >= 5 of 6
  - clean packets cleared on their own >= 3 of 6
The plan's field names are Wonder's own, so scoring doesn't use them. A cleared clean packet must show every true value somewhere among its settled values."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from autoharness import team  # noqa: E402

OUT = ROOT / "docs" / "paperwork.jsonl"


def settled_values(result: dict) -> list[str]:
    vals = [f["value"] for f in result["fields"] if f["status"] == "ok" and f["value"]]
    for t in result["tables"]:
        for r in t["rows"]:
            vals += [c["value"] for c in r["cells"].values() if c["status"] == "ok" and c["value"]]
    return [str(v) for v in vals]


def shown(want: str, values: list[str]) -> bool:
    for v in values:
        for kind in ("text", "name", "id", "date", "money"):
            if team.normal(want, kind) == team.normal(v, kind):
                return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["design", "run"])
    ap.add_argument("packets", type=Path)
    ap.add_argument("--label", default="designed")
    a = ap.parse_args()
    plan_file = a.packets / "plan.json"
    if a.what == "design":
        pages = sorted((a.packets / "example").glob("*.jpg"))
        plan, cost = team.design(pages, (a.packets / "note.txt").read_text())
        plan_file.write_text(json.dumps(plan, indent=1))
        print(json.dumps(cost))
        print(json.dumps(plan, indent=1))
        return
    plan = team.check_plan(json.loads(plan_file.read_text()))
    manifest = json.loads((a.packets / "manifest.json").read_text())
    tally = dict(wrong_saved=0, defects_sent=0, clean_cleared=0, false_alarm=0)
    for info in manifest:
        result = team.process(plan, [a.packets / p for p in info["pages"]])
        routed = result["status"] != "clear"
        missed = []
        if info["expect"]["route"]:
            verdict = "caught" if routed else "WRONG_SAVED"
        elif routed:
            verdict = "false_alarm"
        else:
            values = settled_values(result)
            missed = [w for w in info["truth"]["values"] if not shown(w, values)]
            verdict = "cleared_right" if not missed else "cleared_but_value_not_found"
        tally["wrong_saved"] += verdict == "WRONG_SAVED"
        tally["defects_sent"] += verdict == "caught"
        tally["clean_cleared"] += verdict == "cleared_right"
        tally["false_alarm"] += verdict == "false_alarm"
        rec = dict(run=a.label, mode="designed", packet=info["id"], condition=info["condition"], defect=info["defect"], verdict=verdict, seconds=result["seconds"], reads=result["reads"], missed=missed,
                   issues=[{k: i.get(k) for k in ("kind", "field", "text")} | ({"votes": [v["value"] for v in i["votes"]]} if i.get("votes") else {}) for i in result["issues"]], at=time.time())
        with OUT.open("a") as f:
            f.write(json.dumps(team.jsonable(rec)) + "\n")
        print(f"{info['id']} {info['condition']:12} {info['defect']:18} {verdict:28} {result['seconds']:5.1f} s {[i['field'] or i['kind'] for i in result['issues']][:5]} {missed[:3]}"[:280], flush=True)
    tally["passes_bar"] = tally["wrong_saved"] == 0 and tally["defects_sent"] >= 5 and tally["clean_cleared"] >= 3
    print(json.dumps(tally))


if __name__ == "__main__":
    main()
