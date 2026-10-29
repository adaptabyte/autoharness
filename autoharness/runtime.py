"""Tier 3 — the fast runtime (small model, near-realtime).

Per frame: compute the cheap 16x16 signature, classify the state against
the synthesized spec (no LLM), then follow the transition graph toward
the goal state. The small model is consulted only when the state is
unknown — perception and navigation are already solved by the harness.
"""
from __future__ import annotations

import time
from collections import deque

from .knowledge import frame_signature, signature_distance
from .types import Action, GameSpec


class FastRuntime:
    def __init__(self, env, spec: GameSpec, llm=None, goal_state: int = -1):
        self.env = env
        self.spec = spec
        self.llm = llm
        self.goal = goal_state  # index into spec.states; -1 = last discovered
        self.decisions = 0
        self.llm_calls = 0

    def _classify(self, sig: list) -> int | None:
        best, best_d = None, 0.003
        for i, s in enumerate(self.spec.states):
            d = signature_distance(sig, s["signature"])
            if d < best_d:
                best, best_d = i, d
        return best

    def _next_macro(self, state: int) -> dict | None:
        """BFS over the synthesized transition graph toward the goal state."""
        goal = self.spec.goals[0]["state"] if self.spec.goals else len(self.spec.states) - 1
        if state == goal:
            return None
        edges: dict[int, list[dict]] = {}
        for m in self.spec.macros:
            if "from_state" in m:
                edges.setdefault(m["from_state"], []).append(m)
        prev: dict[int, dict | None] = {state: None}
        queue = deque([state])
        while queue:
            cur = queue.popleft()
            if cur == goal:
                break
            for m in edges.get(cur, []):
                if m["to_state"] not in prev:
                    prev[m["to_state"]] = m
                    queue.append(m["to_state"])
        if goal not in prev:
            return self.spec.macros[0] if self.spec.macros else None
        node, first = goal, None
        while prev[node] is not None:
            first = prev[node]
            node = first["from_state"]
        return first

    def step(self) -> dict:
        obs = self.env.observe()
        sig = frame_signature(obs.frame)
        state = self._classify(sig)
        self.decisions += 1
        if state is None and self.llm is not None:
            self.llm_calls += 1
            self.llm.complete(self.spec.policy_notes)
            self.env.act(Action.wait(0.05))
            return {"state": None, "acted": "wait(llm consulted)"}
        macro = self._next_macro(state or 0)
        if macro:
            for a in macro["actions"]:
                self.env.act(Action(a["kind"], a.get("args", {})))
            return {"state": state, "acted": macro["name"]}
        self.env.act(Action.wait(0.05))
        return {"state": state, "acted": "wait"}

    def run(self, seconds: float = 5.0) -> dict:
        start, log = time.time(), []
        while time.time() - start < seconds:
            log.append(self.step())
        elapsed = time.time() - start
        return {"decisions": self.decisions, "llm_calls": self.llm_calls,
                "decisions_per_sec": round(self.decisions / max(elapsed, 1e-9), 1),
                "log_tail": log[-5:]}
