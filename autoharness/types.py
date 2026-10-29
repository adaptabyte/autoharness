"""Core types shared by the explorer, the synthesizer, and the fast runtime."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Observation:
    """One frame of game state as seen by an agent."""

    frame: object  # PIL.Image.Image, kept untyped to avoid import cycles
    step: int = 0
    meta: dict = field(default_factory=dict)


@dataclass
class Action:
    """A single input action. kind: key|key_down|key_up|click|move|wait|macro."""

    kind: str
    args: dict = field(default_factory=dict)

    @staticmethod
    def key(name: str) -> "Action":
        return Action("key", {"key": name})

    @staticmethod
    def click(x: int, y: int) -> "Action":
        return Action("click", {"x": x, "y": y})

    @staticmethod
    def wait(seconds: float = 0.1) -> "Action":
        return Action("wait", {"seconds": seconds})


@dataclass
class Probe:
    """A cheap perception check the fast runtime can run every frame."""

    name: str
    kind: str  # pixel|region_mean|template|text
    params: dict = field(default_factory=dict)


@dataclass
class Macro:
    """A named, parameterized action sequence synthesized for one game."""

    name: str
    actions: list = field(default_factory=list)  # list[Action-as-dict]
    purpose: str = ""


@dataclass
class GameSpec:
    """The synthesized per-game harness: everything the fast model needs."""

    game: str
    probes: list = field(default_factory=list)   # list[Probe-as-dict]
    macros: list = field(default_factory=list)   # list[Macro-as-dict]
    states: list = field(default_factory=list)   # recognized UI/world states
    goals: list = field(default_factory=list)    # goal detectors
    policy_notes: str = ""                        # short instructions for the small model
