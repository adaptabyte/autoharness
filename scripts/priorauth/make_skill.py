#!/usr/bin/env python3
"""Have Wonder write a markdown guide to an app from what a lesson already learned: one cheap, text-only call.
  make_skill.py <library package> <output file>"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from autoharness import cloud, config, library  # noqa: E402
from autoharness.teacher import app_notes, response_text  # noqa: E402

pkg = library.get(sys.argv[1])
code = (pkg.path / "harness.py").read_text()
prompt = f"""A lesson explored this app and wrote the program below to operate it. A small vision model that sees only screenshots and can click, type and press keys will now do the same job, using your guide.

The job: {pkg.manifest['goal']}

What the lesson wrote down about the app:
{app_notes(pkg) or '(nothing)'}

The program, which holds what was learned about layout and traps:
{code}

Write the guide in markdown, at most 400 words. Say in order what to do on each screen, what each screen looks like when things are right, and the traps. Give no pixel positions and no details of any one patient or request: it must work for every person. Tell it to check that the chart or request on screen belongs to the right person before reading or saving, and that names can look alike. Reply with only the guide."""
c = cloud.Cloud(limit_usd=0.20)
text = response_text(c.respond(model=config.TEACHER_MODEL, input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}]))
Path(sys.argv[2]).write_text(text.strip() + "\n")
print(f"{sys.argv[2]}: {len(text)} chars, ${c.meter.usd:.3f}")
