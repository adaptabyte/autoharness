#!/usr/bin/env python3
"""The fair comparison: Muse Spark does the same jobs through computer use, on the same proof inputs, judged by the same checker.
  spark_runs.py <app> <job> [--n 3] [--limit 0.6]
Spark's written answer is searched for the values, and saved records are read from the app's own store, exactly as for the plan.
Results go to docs/uiteam.jsonl with run spark."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "priorauth"), str(Path(__file__).parent)]
from autoharness import targets, uiteam  # noqa: E402
from autoharness.cloud import Meter  # noqa: E402
from autoharness.desktop import Display  # noqa: E402

import jobs as J  # noqa: E402

OUT = ROOT / "docs" / "uiteam.jsonl"
DATE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b[A-Z][a-z]{2,8}\.? \d{1,2},? \d{4}\b|\b\d{1,2}[ -][A-Z][a-z]{2,8}[ -]\d{4}\b")


def values_from_text(text: str) -> list[str]:
    """A written answer as a flat list of candidates: its dates, IDs, amounts and short phrases."""
    out = DATE.findall(text)
    out += re.findall(r"\b[A-Z]{1,4}-?\d[\w.-]*\b", text)
    out += re.findall(r"\$?\d[\d,]*\.\d\d\b", text)
    out += re.findall(r"\b\d+\b", text)
    for size in (2, 3, 4, 5):
        words = re.findall(r"[A-Za-z][\w-]*", text)
        out += [" ".join(words[i:i + size]) for i in range(len(words) - size + 1)]
        tokens = re.findall(r"[A-Za-z][\w-]*|\d+", text)
        out += [" ".join(tokens[i:i + size]) for i in range(len(tokens) - size + 1)]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("app")
    ap.add_argument("job")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--limit", type=float, default=0.6)
    a = ap.parse_args()
    info = J.APPS[a.app]["jobs"][a.job]
    for i in range(1, a.n + 1):
        inputs = info["inputs"](i)
        spec = J.APPS[a.app]["spec"]()
        display = Display(*spec.get("size", (1280, 800))).start()
        target = targets.Target(spec, display)
        try:
            before = info["before"](inputs) if info.get("before") else None
            meter = Meter()
            t0 = time.time()
            rec = uiteam.explore(display, target, info["goal"](inputs), meter, limit_usd=a.limit)
            seconds = round(time.time() - t0, 1)
            said = " ".join(r["said"] for r in rec["record"][-3:])
            finished = rec["status"] == "finished"
            result = {"status": "done" if finished else "needs_help", "reason": rec["status"], "outputs": {"answer": values_from_text(said)}, "scope": {}}
            ok, detail, wrong = info["judge"](result, inputs, before)
            row = dict(run="spark", app=a.app, job=a.job, i=i, ok=ok, wrong_saved=wrong, detail=detail[:300], status=rec["status"], seconds=seconds, turns=rec["turns"], usd=round(meter.usd, 4), bytes_sent=meter.bytes_sent, answer=said[-300:], at=time.time())
            with OUT.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
            print(f"{a.job} {i}: {'PASS' if ok else 'FAIL'} {seconds} s ${meter.usd:.3f} {rec['turns']} turns | {detail[:150]}", flush=True)
        finally:
            target.stop()
            display.stop()


if __name__ == "__main__":
    main()
