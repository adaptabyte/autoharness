"""CLI: autoharness demo | explore | play.

Tier wiring: --smart-url/--fast-url point at OpenAI-compatible endpoints
(Muse Wonder API for explore, your local vLLM Glimmer server for play).
With no URL, a MockLLM stands in so the pipeline runs anywhere.
"""
from __future__ import annotations

import argparse
import json

from .env import HeadlessEnv
from .explorer import Explorer
from .knowledge import GameKnowledge
from .llm import MockLLM, OpenAICompatLLM
from .manual import load_manual
from .runtime import FastRuntime
from .synth import synthesize


def _llm(url: str | None, model: str):
    return OpenAICompatLLM(url, model) if url else MockLLM()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="autoharness")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("demo", "explore", "play"):
        sp = sub.add_parser(name)
        sp.add_argument("--manual", default=None)
        sp.add_argument("--smart-url", default=None)
        sp.add_argument("--smart-model", default="muse-wonder")
        sp.add_argument("--fast-url", default=None)
        sp.add_argument("--fast-model", default="muse-glimmer")
        sp.add_argument("--steps", type=int, default=40)
        sp.add_argument("--seconds", type=float, default=5.0)
        sp.add_argument("--kb", default="game_kb.json")
    args = p.parse_args(argv)

    from games.demo_game import DemoGame
    env = HeadlessEnv(DemoGame())
    chunks = load_manual(args.manual) if args.manual else []

    if args.cmd in ("demo", "explore"):
        kb = Explorer(env, _llm(args.smart_url, args.smart_model),
                      "demo-quest", chunks).explore(steps=args.steps)
        kb.save(args.kb)
        print(json.dumps({"screens": len(kb.screens), "controls": kb.controls,
                          "transitions": len(kb.transitions)}, indent=1))
        if args.cmd == "explore":
            return
    else:
        kb = GameKnowledge.load(args.kb)

    spec = synthesize(kb)
    result = FastRuntime(HeadlessEnv(DemoGame()),
                         spec, _llm(args.fast_url, args.fast_model)).run(args.seconds)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
