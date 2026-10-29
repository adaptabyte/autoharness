"""Game environment abstraction.

Two backends share one interface so the same explorer/runtime code drives
both: `HeadlessEnv` wraps any in-process game exposing frame()/act() (used
for tests and the built-in demo game); `X11Env` captures a real window with
ffmpeg x11grab and injects input with xdotool (install: apt install xdotool).
"""
from __future__ import annotations

import shutil
import subprocess

from PIL import Image

from .types import Action, Observation


class HeadlessEnv:
    """Wraps an in-process game: frame() -> PIL.Image, act(Action) -> None."""

    def __init__(self, game):
        self.game = game
        self._step = 0

    def observe(self) -> Observation:
        self._step += 1
        return Observation(frame=self.game.frame(), step=self._step)

    def act(self, action: Action) -> None:
        self.game.act(action)


class X11Env:
    """Drives a real game window on an X display (default :0)."""

    def __init__(self, window_title: str, display: str = ":0"):
        if shutil.which("xdotool") is None:
            raise RuntimeError("X11Env needs xdotool: sudo apt install xdotool")
        self.display = display
        self.wid = subprocess.run(
            ["xdotool", "search", "--name", window_title],
            capture_output=True, text=True,
            env={"DISPLAY": display, "PATH": "/usr/bin:/bin"},
        ).stdout.split()[0]

    def observe(self) -> Observation:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "x11grab", "-i", f"{self.display}",
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True,
            env={"DISPLAY": self.display, "PATH": "/usr/bin:/bin"},
        ).stdout
        import io
        return Observation(frame=Image.open(io.BytesIO(raw)).convert("RGB"))

    def act(self, action: Action) -> None:
        env = {"DISPLAY": self.display, "PATH": "/usr/bin:/bin"}
        if action.kind == "key":
            subprocess.run(["xdotool", "key", action.args["key"]], env=env)
        elif action.kind == "click":
            subprocess.run(["xdotool", "mousemove", str(action.args["x"]),
                            str(action.args["y"]), "click", "1"], env=env)
