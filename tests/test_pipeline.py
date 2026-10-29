"""End-to-end: explore the demo game, synthesize a harness, win a fresh game."""
from autoharness.env import HeadlessEnv
from autoharness.explorer import Explorer
from autoharness.llm import MockLLM
from autoharness.runtime import FastRuntime
from autoharness.synth import synthesize
from games.demo_game import DemoGame


def test_explore_synthesize_play_wins():
    kb = Explorer(HeadlessEnv(DemoGame()), MockLLM(), "demo-quest").explore(steps=4000)
    assert len(kb.screens) > 10
    assert any(f.startswith("terminal screen") for f in kb.manual_facts)

    spec = synthesize(kb)
    assert spec.macros and spec.goals

    game = DemoGame()
    FastRuntime(HeadlessEnv(game), spec, MockLLM()).run(seconds=3.0)
    assert game.screen == "win"
