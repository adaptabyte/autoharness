#!/usr/bin/env python3
"""Ask for something in plain words, and let a model do it through the interfaces compiled on this computer.
  ask.py "Has order ORD-10530 shipped? What's its total?"
  ask.py --server http://127.0.0.1:4140/mcp/ui/backoffice "..."

The asking model only chooses a job and its inputs from the tool list, the same list any MCP client gets from /mcp/ui.
The job itself runs on this computer: Muse Glimmer operates the real interface and code checks every step.
The asking model sees the request and the verified answer, never a screenshot, and never a login kept on this computer.
It's Muse Spark here, through the same budgeted client as everything else, so every cent is in the ledger."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoharness import config  # noqa: E402
from autoharness.cloud import Cloud, Meter, response_text  # noqa: E402

GREY, BOLD, GREEN, AMBER, END = "\033[90m", "\033[1m", "\033[32m", "\033[33m", "\033[0m"


def rpc(server: str, method: str, params: dict | None = None, caller: str = "Muse Spark") -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": int(time.time() * 1000), "method": method, "params": params or {}}).encode()
    # This client waits as long as a job takes, so it asks the server not to hand back a job id after 50 s.
    url = server + ("&" if "?" in server else "?") + "wait=1800"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "X-Caller": caller})
    with urllib.request.urlopen(req, timeout=1900) as r:
        reply = json.load(r)
    if "error" in reply:
        raise RuntimeError(reply["error"]["message"])
    return reply["result"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--server", default="http://127.0.0.1:4140/mcp/ui")
    ap.add_argument("--model", default=config.SPARK_MODEL)
    ap.add_argument("--limit", type=float, default=0.25, help="most this request may spend on the asking model, in dollars")
    a = ap.parse_args()

    tools = rpc(a.server, "tools/list")["tools"]
    print(f"{GREY}{len(tools)} jobs offered by {a.server}: {', '.join(t['name'] for t in tools)}{END}\n")
    print(f"{BOLD}You:{END} {a.request}\n")
    meter = Meter()
    cloud = Cloud(meter=meter, limit_usd=a.limit)
    functions = [{"type": "function", "name": t["name"], "description": t["description"][:1000], "parameters": t["inputSchema"]} for t in tools]
    instructions = ("You help a person get things done in software on their own computer. Each tool is a whole job in one interface, "
                    "compiled in advance and run locally with every step checked. Use a tool when the request needs one, with inputs taken "
                    "only from the request; never invent a value. If a tool stops or refuses, say so plainly and why. Answer briefly.")
    prev, items = None, [{"role": "user", "content": a.request}]
    for _ in range(6):
        body = dict(model=a.model, input=items, tools=functions, instructions=instructions, reasoning={"effort": "low"}, store=True)
        if prev:
            body["previous_response_id"] = prev
        out = cloud.respond(**body)
        prev, items = out["id"], []
        calls = [i for i in out.get("output", []) if i.get("type") == "function_call"]
        if not calls:
            print(f"{BOLD}{a.model}:{END} {response_text(out)}\n")
            break
        for call in calls:
            args = json.loads(call.get("arguments") or "{}")
            print(f"{GREY}{a.model} calls{END} {BOLD}{call['name']}{END} {json.dumps(args)}")
            print(f"{GREY}  running on this computer; watch it at http://127.0.0.1:4140{END}")
            t0 = time.time()
            result = rpc(a.server, "tools/call", {"name": call["name"], "arguments": args})
            data = result.get("structuredContent") or result["content"][0]["text"]
            colour = AMBER if result.get("isError") else GREEN
            shown = json.dumps(data.get("outputs") if isinstance(data, dict) and data.get("ok") else data)
            print(f"{colour}  {'stopped' if result.get('isError') else 'verified'} in {time.time() - t0:.0f} s{END}: {shown[:400]}\n")
            items.append({"type": "function_call_output", "call_id": call["call_id"], "output": result["content"][0]["text"][:4000]})
    print(f"{GREY}The asking model cost ${meter.usd:.4f} in the cloud. The interface ran on this computer, for $0.{END}")


if __name__ == "__main__":
    main()
