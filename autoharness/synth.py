"""Tier 2 — auto-harness synthesis.

Compiles GameKnowledge into a GameSpec: the streamlined, per-game harness
the fast model runs. Design rule: everything the smart model figured out
slowly (screen identities, which keys work, how screens connect) becomes
cheap deterministic machinery here — signature matching, a transition
graph, named macros — so the small model only decides, never perceives
from scratch.
"""
from __future__ import annotations

from .knowledge import GameKnowledge, signature_distance
from .types import GameSpec


def _state_index(kb: GameKnowledge, sig: list) -> int:
    best, best_d = 0, float("inf")
    for i, s in enumerate(kb.screens):
        d = signature_distance(sig, s.signature)
        if d < best_d:
            best, best_d = i, d
    return best


def synthesize(kb: GameKnowledge) -> GameSpec:
    states = [
        {"index": i, "description": s.description, "signature": s.signature}
        for i, s in enumerate(kb.screens)
    ]
    macros, seen = [], set()
    for t in kb.transitions:
        frm, to = _state_index(kb, t.from_sig), _state_index(kb, t.to_sig)
        key = t.action.get("args", {}).get("key", "act")
        name = f"press_{key}_s{frm}_to_s{to}"
        if name in seen or frm == to:
            continue
        seen.add(name)
        macros.append({"name": name, "actions": [t.action],
                       "purpose": t.effect or f"press {key}",
                       "from_state": frm, "to_state": to})
    described = next((i for i, s in enumerate(kb.screens)
                      if "win" in s.description.lower()), None)
    for fact in kb.manual_facts:
        if fact.startswith("terminal screen index"):
            described = int(fact.rsplit(" ", 1)[1])
    # Fallback: a sink screen (no outgoing edges) is usually win/game-over.
    has_out = {m["from_state"] for m in macros}
    sinks = [i for i in range(len(states)) if i not in has_out and i != 0]
    goal = described if described is not None else (sinks[-1] if sinks else len(states) - 1)
    notes = (
        f"Game: {kb.game}. Known controls: {kb.controls}. "
        f"Goal state index: {goal}. Follow graph edges toward the goal; "
        "if the state is unknown, reply WAIT."
    )
    return GameSpec(game=kb.game, probes=[], macros=macros, states=states,
                    goals=[{"state": goal}], policy_notes=notes)
