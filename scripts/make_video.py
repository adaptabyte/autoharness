#!/usr/bin/env python3
"""Cuts the real recordings in clips/ into a captioned draft of the 3-minute video, clips/draft.mp4.
Footage is sped up where noted, and the caption says so, because watching a run in real time isn't the point and hiding the speed-up would be."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIPS = ROOT / "clips"
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
SIZE = "1280:720"

# clip, seconds into the clip to start from (negative counts from the end), how long the result runs, how much it's sped up, caption
CUT = [
    ("swarm", 20, 13, 6, "One small open model on my desk, running 8 copies of an interface at once. No cloud. (sped up 6x)"),
    ("home", 1, 11, 1, "AI agents pay a genius to look at a screenshot and click a button.\nSo this compiles the interface instead."),
    ("teach", 1, 15, 1, "Point it at any interface. This Django admin is one it has never seen."),
    ("teach", 18, 18, 5, "Muse Spark uses it once, and everything is recorded. (sped up 5x)"),
    ("teach", -55, 18, 3, "Muse Wonder writes a plan: data, not code, with every decision made in advance. Glimmer has to pass alone. (sped up 3x)"),
    ("run", 6, 22, 4, "Muse Glimmer runs it on this machine, answering one narrow question per screen. Code holds the memory. (sped up 4x)"),
    ("run", 45, 15, 2, "What it types gets read back. What it reads gets read twice.\nA run ends verified, or it stops and asks. (sped up 2x)"),
    ("run", -12, 8, 1, "$0.00 in cloud. It keeps working with the internet unplugged."),
    ("table", 0, 23, 1, "Inputs it had never seen. Checked against each app's own data. Bars committed before the first run."),
    ("digit", 2, 12, 3, "Paper is an interface too. A stack is read on this computer, page against page. (sped up 3x)"),
    ("digit", -11, 9, 1, "One digit differs between pages. It doesn't pick one. It comes to a person."),
    ("clean", -60, 15, 4, "Approve a clean stack, and a compiled plan fills the portal. No connector was written by hand. (sped up 4x)"),
    ("clean", -7, 6, 1, "It stops at the signature. Only a person can sign."),
    ("failed", 0, 6, 1, "It isn't ready for real patients. Made-up records, small samples, and every failure is in the repo."),
    ("home", 1, 5, 1, "Computer use becomes the compiler, not the runtime.\nFor the models, by the models."),
]


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for n, (clip, start, length, speed, caption) in enumerate(CUT):
            source = CLIPS / f"{clip}.mp4"
            if not source.exists():
                sys.exit(f"missing {source}: run scripts/make_clips.py")
            total = duration(source)
            at = max(0.0, total + start if start < 0 else start)
            at = min(at, max(0.0, total - 1))
            need = length * speed
            text = Path(tmp) / f"{n}.txt"
            text.write_text(caption)
            part = Path(tmp) / f"{n}.mp4"
            filters = (f"setpts=PTS/{speed},scale={SIZE}:force_original_aspect_ratio=decrease,pad={SIZE}:(ow-iw)/2:(oh-ih)/2:white,tpad=stop_mode=clone:stop_duration={length},"
                       f"drawbox=y=ih-104:w=iw:h=104:color=black@0.78:t=fill,drawtext=fontfile={FONT}:textfile={text}:fontcolor=white:fontsize=25:line_spacing=8:x=(w-text_w)/2:y=h-92")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(at), "-t", str(need), "-i", str(source), "-vf", filters, "-t", str(length), "-r", "24", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", str(part)], check=True)
            parts.append(part)
        listing = Path(tmp) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        out = CLIPS / "draft.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)], check=True)
        print(out, round(duration(out)), "s")


if __name__ == "__main__":
    main()
