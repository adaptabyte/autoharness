"""Tier 1 — the explorer harness (high-intelligence multimodal model).

Slow and deliberate by design: observe a frame, identify the screen, ask
the smart model what it is and what to try, execute candidate actions one
at a time, and record every transition. Manual facts are folded in first
so exploration starts from the docs instead of from zero. Output is a
GameKnowledge file that synthesis compiles into the fast harness.
"""
from __future__ import annotations

from .knowledge import GameKnowledge, Screen, Transition, frame_signature
from .manual import relevant_chunks
from .types import Action

CANDIDATE_KEYS = ["Return", "space", "Up", "Down", "Left", "Right",
                  "w", "a", "s", "d", "e", "q", "Escape", "Tab"]


class Explorer:
    def __init__(self, env, llm, game: str, manual_chunks: list[str] | None = None):
        self.env = env
        self.llm = llm
        self.kb = GameKnowledge(game=game)
        self.manual_chunks = manual_chunks or []

    def _describe(self, obs) -> str:
        facts = relevant_chunks(self.manual_chunks, "controls goal objective")
        prompt = (
            f"Game: {self.kb.game}. You are exploring its UI. Manual facts: "
            f"{facts}. Frame size: {obs.frame.size}. In one sentence, what "
            "screen is this and what is the likely goal here?"
        )
        try:
            return self.llm.complete(prompt)[:300]
        except Exception as exc:  # smart tier is advisory; never block learning
            return f"(no description: {exc})"

    def explore(self, steps: int = 300) -> GameKnowledge:
        """One action per step, cycling untried keys per screen.

        Pressing every key in a row cancels itself out (Up then Down), so
        each step tries the next untried key for the current screen and
        records what that single action did. Screens are re-visited until
        every key has been tried from each of them.
        """
        import random
        rng = random.Random(1234)
        tried: dict[int, set] = {}
        for _ in range(steps):
            obs = self.env.observe()
            sig = frame_signature(obs.frame)
            screen = self.kb.find_screen(sig)
            if screen is None:
                screen = Screen(signature=sig, description=self._describe(obs))
                self.kb.screens.append(screen)
            screen.visits += 1
            idx = self.kb.screens.index(screen)
            done = tried.setdefault(idx, set())
            if idx != 0 and len(done) >= len(CANDIDATE_KEYS):
                # Terminal = every key tried, none changed the frame
                # (win / game over). Record it and stop exploring.
                from .knowledge import signature_distance as _sd
                has_out = any(_sd(t.from_sig, screen.signature) < 0.003
                              for t in self.kb.transitions)
                if not has_out:
                    self.kb.manual_facts.append(f"terminal screen index {idx}")
                    break
            untried = [k for k in CANDIDATE_KEYS if k not in done]
            key = rng.choice(untried) if untried else rng.choice(CANDIDATE_KEYS)
            done.add(key)
            self.env.act(Action.key(key))
            after = frame_signature(self.env.observe().frame)
            from .knowledge import signature_distance
            if signature_distance(sig, after) > 0.002:
                self.kb.controls[key] = "changes the frame"
                self.kb.transitions.append(Transition(
                    from_sig=sig, action={"kind": "key", "args": {"key": key}},
                    to_sig=after, effect=f"{key} changed the frame"))
        return self.kb
