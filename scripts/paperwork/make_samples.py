#!/usr/bin/env python3
"""The made-up stacks a visitor can try from the home page. Everyone here is invented; none of it is a real form, plan or person.
Writes samples/<id>/, and the members the fictional portal needs to scripts/priorauth/demo_members.json."""
from __future__ import annotations

import io
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from make_other import CSS as OTHER_CSS, invoice_packet  # noqa: E402
from make_packets import CSS, DAMAGE, FACES, Render  # noqa: E402

SAMPLES = ROOT / "samples"
TRIALS = [dict(drug="Sertraline 100 mg", start="2024-01-08", end="2024-08-19", outcome="Inadequate response"), dict(drug="Bupropion XL 300 mg", start="2024-09-03", end="2025-05-12", outcome="Intolerance")]
PEOPLE = {
    "clean": dict(first="Nadia", last="Whitlock", dob="1981-04-22", member_id="MBR-418207", problem="Major depressive disorder, recurrent, moderate", icd10="F33.1", drug="Vortioxetine", strength="10 mg", quantity=30, days=30, trials=TRIALS),
    "digit": dict(first="Theo", last="Rasmussen", dob="1972-06-21", member_id="MBR-493186", problem="Bipolar II disorder", icd10="F31.81", drug="Lurasidone", strength="60 mg", quantity=30, days=30,
                  trials=[dict(drug="Lamotrigine 200 mg", start="2023-07-10", end="2024-08-22", outcome="Inadequate response"), dict(drug="Quetiapine 200 mg", start="2024-08-26", end="2025-09-09", outcome="Intolerance")], member_order="MBR-493188"),
    "stray": dict(first="Zainab", last="Fairweather", dob="1990-11-03", member_id="XJH77120458", problem="ADHD, inattentive presentation", icd10="F90.0", drug="Viloxazine", strength="200 mg", quantity=30, days=30,
                  trials=[dict(drug="Atomoxetine 80 mg", start="2024-02-12", end="2024-09-30", outcome="Inadequate response"), dict(drug="Citalopram 40 mg", start="2024-10-14", end="2025-06-02", outcome="Intolerance")]),
    "gap": dict(first="Corbin", last="Ostrowski", dob="1967-02-28", member_id="W558014623", problem="Generalized anxiety disorder", icd10="F41.1", drug="Vilazodone", strength="20 mg", quantity=30, days=30,
                trials=[dict(drug="Escitalopram 20 mg", start="2024-03-18", end="2024-11-05", outcome="Intolerance"), dict(drug="Duloxetine 60 mg", start="2025-01-13", end="", outcome="Inadequate response")]),
}
OTHER = dict(first="Marisol", last="Dragomir", dob="1955-09-17", member_id="MBR-771940", problem="Generalized anxiety disorder", icd10="F41.1", drug="Vilazodone", strength="10 mg", quantity=30, days=30, trials=TRIALS)
for person in [*PEOPLE.values(), OTHER]:
    person.update(name=f"{person['first']} {person['last']}", group="GRP-40112", npi="1447203981", phone="(555) 314-2267", other="Metformin 500 mg", other_since="2019-05-14")
META = {
    "clean": dict(order=1, title="A clean stack", blurb="Nothing wrong. Approve it and watch a small model fill a made-up portal, then stop for a signature.", plan="clinic"),
    "digit": dict(order=2, title="One wrong digit", blurb="The order form's member ID differs from the chart by one digit.", plan="clinic"),
    "stray": dict(order=3, title="Someone else's page", blurb="A page from another patient's chart slipped into the stack.", plan="clinic"),
    "gap": dict(order=4, title="A missing date", blurb="The handwritten history leaves out when a medication stopped.", plan="clinic"),
}


def main() -> None:
    random_seed = 41
    with sync_playwright() as pw:
        br = pw.chromium.launch(args=["--no-sandbox"])
        pg = br.new_page(viewport={"width": 850, "height": 1100}, device_scale_factor=1.6)

        def write(sample: str, pages: list[str], css: str, condition: str, faces: bool = False) -> list[str]:
            out = SAMPLES / sample
            out.mkdir(parents=True, exist_ok=True)
            noise = np.random.default_rng(random_seed + len(sample))
            names = []
            for n, html in enumerate(pages):
                pg.set_content(f"<!doctype html><style>{FACES if faces else ''}{css}</style><body>{html}</body>", wait_until="load")
                pg.evaluate("document.fonts.ready")
                im = np.asarray(Image.open(io.BytesIO(pg.screenshot())).convert("RGB"))
                name = f"page{n + 1}.jpg"
                Image.fromarray(DAMAGE[condition](im, noise)).save(out / name, quality=88)
                names.append(name)
            return names

        settings = {"clean": ("fax", None, "us"), "digit": ("hand_photo", "Caveat", "us"), "stray": ("typed_scan", None, "long"), "gap": ("hand_scan", "Kalam-Regular", "short")}
        for key, person in PEOPLE.items():
            condition, hand, dates = settings[key]
            rng = random.Random(key)
            r = Render(person, rng, hand, dates)
            pages = [r.intake(), r.history(), r.order()]
            if key == "stray":
                pages.insert(1, Render(OTHER, rng, hand, dates).intake())
            css = CSS % {"font": "Georgia,serif", "hand": hand or "serif", "hsize": 25 if hand == "Caveat" else 19}
            files = write(key, pages, css, condition, faces=bool(hand))
            (SAMPLES / key / "meta.json").write_text(json.dumps({**META[key], "files": files}, indent=1))
        pages, _, _ = invoice_packet(random.Random(1234), "bank_changed")
        files = write("invoice", pages, OTHER_CSS % "Arial,sans-serif", "typed_scan")
        (SAMPLES / "invoice" / "meta.json").write_text(json.dumps(dict(order=5, title="An invoice with a new bank account", blurb="Not medical at all: the invoice asks to pay an account that isn't the one on file.", plan="invoice", files=files), indent=1))
        br.close()
    members = {p["member_id"]: {k: p[k] for k in ("first", "last", "dob", "member_id")} for p in [PEOPLE["clean"], PEOPLE["gap"], PEOPLE["stray"], PEOPLE["digit"]]}
    (ROOT / "scripts" / "priorauth" / "demo_members.json").write_text(json.dumps(list(members.values()), indent=1))


if __name__ == "__main__":
    main()
