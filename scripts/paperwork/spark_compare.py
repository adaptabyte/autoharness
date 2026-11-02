#!/usr/bin/env python3
"""The frontier model on the same packets: Muse Spark reads each page once, in the cloud, with the same merging code.
  spark_compare.py <packets dir> <plan.json> --limit-usd 0.12 --label NAME
It stops at its money limit, and the packets it reached are the comparison. These pages are made up: real ones couldn't be sent like this."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]
import evaluate  # noqa: E402
from autoharness import config, team  # noqa: E402
from autoharness.cloud import BudgetExceeded, Cloud, Meter, image_url, response_text  # noqa: E402
from autoharness.local import extract_json  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packets", type=Path)
    ap.add_argument("plan", type=Path)
    ap.add_argument("--limit-usd", type=float, default=0.12)
    ap.add_argument("--label", required=True)
    a = ap.parse_args()
    plan = team.check_plan(json.loads(a.plan.read_text()))
    reader = plan["readers"][0]
    prompt, shape = team.reader_prompt(plan, reader)
    text = prompt + "\n\nReply with only a JSON object matching this shape, no other text:\n" + json.dumps(shape)
    manifest = json.loads((a.packets / "manifest.json").read_text())
    meter = Meter()
    cloud = Cloud(meter=meter, limit_usd=a.limit_usd)

    def read(job):
        i, name = job
        frame = team.load_page(a.packets / name)
        resp = cloud.respond(model=config.SPARK_MODEL, reasoning={"effort": "low"}, input=[{"role": "user", "content": [{"type": "input_text", "text": text}, {"type": "input_image", "image_url": image_url(frame, 85)}]}])
        try:
            data = extract_json(response_text(resp))
        except ValueError:
            data = {}
        return {"page": i, "reader": "Spark", "data": data if isinstance(data, dict) else {}, "seconds": 0}

    tally, secs = {}, []
    done = 0
    for info in manifest:
        t0 = time.time()
        try:
            with ThreadPoolExecutor(4) as ex:
                answers = list(ex.map(read, enumerate(info["pages"])))
        except BudgetExceeded as e:
            print(e)
            break
        result = team.merge(plan, answers, min_support=1)
        result["seconds"] = round(time.time() - t0, 1)
        verdict = evaluate.score(result, info, plan)
        tally[verdict["verdict"]] = tally.get(verdict["verdict"], 0) + 1
        secs.append(result["seconds"])
        done += 1
        rec = dict(run=a.label, mode="spark", packet=info["id"], condition=info["condition"], defect=info["defect"], seconds=result["seconds"], reads=len(answers), status=result["status"], **verdict, usd_so_far=round(meter.usd, 5),
                   issues=[{k: i.get(k) for k in ("kind", "field", "text")} for i in result["issues"]], at=time.time())
        with evaluate.OUT.open("a") as f:
            f.write(json.dumps(team.jsonable(rec)) + "\n")
        print(info["id"], info["defect"], verdict["verdict"], result["seconds"], verdict["errors"][:2], f"${meter.usd:.3f}", flush=True)
    print(json.dumps(dict(packets=done, tally=tally, median_s=statistics.median(secs) if secs else None, usd=round(meter.usd, 4), usd_per_packet=round(meter.usd / max(done, 1), 4), bytes_sent=meter.bytes_sent)))


if __name__ == "__main__":
    main()
