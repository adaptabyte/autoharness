"""Built-in demo game: proves explore -> synthesize -> play end-to-end.

A tiny PIL-rendered game with three screens (title, play, win) and a
grid world: move the blue square onto the green goal with WASD/arrows.
No display or GPU needed — frames are rendered in-process.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

W, H, CELL = 320, 240, 32


class DemoGame:
    def __init__(self):
        self.screen = "title"
        self.x, self.y = 1, 1
        self.goal = (8, 6)
        self.moves = 0

    def frame(self) -> Image.Image:
        img = Image.new("RGB", (W, H), (16, 16, 24))
        d = ImageDraw.Draw(img)
        if self.screen == "title":
            d.rectangle([90, 90, 230, 130], fill=(70, 70, 160))
            d.text((110, 105), "DEMO QUEST", fill=(255, 255, 255))
            d.text((95, 150), "press enter", fill=(200, 200, 200))
        elif self.screen == "win":
            d.rectangle([80, 90, 240, 140], fill=(30, 140, 60))
            d.text((120, 105), "YOU WIN", fill=(255, 255, 255))
        else:
            for gx in range(10):
                for gy in range(7):
                    d.rectangle([gx * CELL, gy * CELL, gx * CELL + CELL - 2,
                                 gy * CELL + CELL - 2], outline=(50, 50, 70))
            d.rectangle([self.goal[0] * CELL, self.goal[1] * CELL,
                         self.goal[0] * CELL + CELL - 2,
                         self.goal[1] * CELL + CELL - 2], fill=(40, 200, 80))
            d.rectangle([self.x * CELL, self.y * CELL, self.x * CELL + CELL - 2,
                         self.y * CELL + CELL - 2], fill=(60, 120, 255))
        return img

    def act(self, action) -> None:
        key = action.args.get("key", "")
        if self.screen == "title" and key in ("Return", "space"):
            self.screen = "play"
            return
        if self.screen != "play":
            return
        dx, dy = {"Left": (-1, 0), "a": (-1, 0), "Right": (1, 0), "d": (1, 0),
                  "Up": (0, -1), "w": (0, -1), "Down": (0, 1), "s": (0, 1)}.get(key, (0, 0))
        if dx or dy:
            self.x = min(9, max(0, self.x + dx))
            self.y = min(6, max(0, self.y + dy))
            self.moves += 1
            if (self.x, self.y) == self.goal:
                self.screen = "win"
