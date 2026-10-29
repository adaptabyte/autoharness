"""What the explorer learns about a game, persisted as JSON.

This is the contract between the slow smart tier and synthesis: screens
(frame signature -> meaning), controls that did something, and transitions
(screen + action -> screen). Synthesis compiles this into a GameSpec.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image


def frame_signature(frame: Image.Image) -> list[float]:
    """16x16 grayscale signature: cheap, robust screen identity."""
    small = frame.convert("L").resize((32, 32))
    return (np.asarray(small, dtype=np.float32) / 255.0).ravel().round(3).tolist()


def signature_distance(a: list[float], b: list[float]) -> float:
    return float(np.mean(np.abs(np.array(a) - np.array(b))))


@dataclass
class Screen:
    signature: list
    description: str = ""
    visits: int = 0


@dataclass
class Transition:
    from_sig: list
    action: dict
    to_sig: list
    effect: str = ""


@dataclass
class GameKnowledge:
    game: str
    screens: list = field(default_factory=list)       # list[Screen]
    transitions: list = field(default_factory=list)   # list[Transition]
    controls: dict = field(default_factory=dict)      # key -> observed effect
    manual_facts: list = field(default_factory=list)  # facts pulled from docs

    def find_screen(self, sig: list, tol: float = 0.003) -> Screen | None:
        best, best_d = None, tol
        for s in self.screens:
            d = signature_distance(sig, s.signature)
            if d < best_d:
                best, best_d = s, d
        return best

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=1))

    @staticmethod
    def load(path: str | Path) -> "GameKnowledge":
        raw = json.loads(Path(path).read_text())
        raw["screens"] = [Screen(**s) for s in raw["screens"]]
        raw["transitions"] = [Transition(**t) for t in raw["transitions"]]
        return GameKnowledge(**raw)
