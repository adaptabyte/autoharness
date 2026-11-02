#!/usr/bin/env python3
"""Generate made-up clinic paperwork, with the truth kept beside it. Every person, ID and plan here is invented.
  make_packets.py <out dir> [--count 30] [--seed 2026]
Pages are full letter size and vary by layout, date style and damage: typed scans, handwriting-style fills, faxes and phone photos.
Each packet is clean or has one planted defect. Handwriting fonts are from Google Fonts (see fonts/README)."""
from __future__ import annotations

import argparse
import base64
import json
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
FONTS = {p.stem: base64.b64encode(p.read_bytes()).decode() for p in sorted((HERE / "fonts").glob("*.ttf"))}
FACES = "".join(f"@font-face{{font-family:'{n}';src:url(data:font/ttf;base64,{d})}}" for n, d in FONTS.items())
FIRST = "Odalys Bram Zainab Tobias Henrike Kwame Lucinda Mateus Saoirse Dmitri Farah Ansel Yuki Corbin Thandiwe Ignacio Beatrix Omari Linnea Rohan Giselle Tadeo Marisol Ewan Nadia Cyrus Philippa Jomo Vera Aurelio Mirela Kenji Delphine".split()
LAST = "Halvorsen Nwosu Pemberton Achterberg Delacroix Mbeki Sorrentino Wainwright Yilmaz Fairweather Kapoor Lindqvist Ostrowski Tanaka Valderrama Ellingson Haddad Prescott Rosenthal Ibekwe Marchand Thorvald Quintero Bellweather Dragomir Ainsley Moreau Okonkwo Stavros Whitlock Zielinski Carmichael Fontaine".split()
ORDERS = [("Generalized anxiety disorder", "F41.1", "Buspirone", "15 mg", 60, 30), ("Post-traumatic stress disorder", "F43.10", "Prazosin", "2 mg", 30, 30), ("Schizoaffective disorder, bipolar type", "F25.0", "Lumateperone", "42 mg", 30, 30),
          ("Obsessive-compulsive disorder", "F42.2", "Clomipramine", "75 mg", 90, 90), ("ADHD, inattentive presentation", "F90.0", "Viloxazine", "200 mg", 30, 30), ("Major depressive disorder, recurrent, moderate", "F33.1", "Vortioxetine", "10 mg", 30, 30),
          ("Bipolar II disorder", "F31.81", "Lurasidone", "60 mg", 30, 30), ("Insomnia disorder", "F51.01", "Daridorexant", "50 mg", 30, 30), ("Panic disorder", "F41.0", "Vilazodone", "20 mg", 30, 30), ("Major depressive disorder, recurrent, severe", "F33.2", "Cariprazine", "1.5 mg", 30, 30)]
MEDS = ["Sertraline 100 mg", "Escitalopram 20 mg", "Fluoxetine 40 mg", "Paroxetine 30 mg", "Venlafaxine XR 150 mg", "Duloxetine 60 mg", "Bupropion XL 300 mg", "Mirtazapine 30 mg", "Trazodone 100 mg", "Quetiapine 200 mg", "Aripiprazole 10 mg", "Lamotrigine 200 mg", "Citalopram 40 mg", "Atomoxetine 80 mg", "Zolpidem 10 mg", "Hydroxyzine 50 mg"]
UNRELATED = ["Metformin 500 mg", "Lisinopril 10 mg", "Atorvastatin 20 mg", "Levothyroxine 50 mcg", "Omeprazole 20 mg"]
OUTCOMES = ["Inadequate response", "Intolerance"]
MEMBER_LABELS = ["Insurance member number", "Member ID #", "Subscriber ID", "Policy / ID No."]
CONDITIONS = ["typed_scan", "hand_scan", "fax", "phone_photo", "hand_photo"]
DEFECTS = ["clean"] * 18 + ["gap_date", "gap_outcome", "gap_quantity", "conflict_member", "conflict_dob", "conflict_dose", "wrong_patient", "wrong_patient", "wrong_patient", "date_order", "date_order", "date_order"]


def date_style(iso: str, style: str) -> str:
    if not iso:
        return ""
    y, m, d = (int(x) for x in iso.split("-"))
    month = "January February March April May June July August September October November December".split()[m - 1]
    return {"us": f"{m:02d}/{d:02d}/{y}", "short": f"{m}/{d}/{str(y)[2:]}", "long": f"{month} {d}, {y}", "abbr": f"{d:02d}-{month[:3]}-{y}"}[style]


def iso_day(rng: random.Random, start: int, end: int) -> str:
    return f"{rng.randint(start, end)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"


def member_id(rng: random.Random) -> str:
    n = rng.randint(100000, 999999)
    return rng.choice([f"MBR-{n}", f"XJH{n}{rng.randint(10, 99)}", f"W{n}{rng.randint(100, 999)}", f"{n}-{rng.randint(10, 99)}A"])


def make_person(rng: random.Random, used: set) -> dict:
    while True:
        first, last = rng.choice(FIRST), rng.choice(LAST)
        if last not in used:
            used.add(last)
            break
    problem, icd, drug, strength, qty, days = rng.choice(ORDERS)
    meds = rng.sample(MEDS, 2)
    year = rng.randint(2022, 2024)
    a = f"{year}-{rng.randint(1, 6):02d}-{rng.randint(1, 28):02d}"
    b = f"{year}-{rng.randint(8, 12):02d}-{rng.randint(1, 28):02d}"
    c = f"{year + 1}-{rng.randint(1, 3):02d}-{rng.randint(1, 28):02d}"
    d = f"{year + 1}-{rng.randint(6, 12):02d}-{rng.randint(1, 28):02d}"
    return dict(first=first, last=last, name=f"{first} {last}", dob=iso_day(rng, 1950, 2004), member_id=member_id(rng), problem=problem, icd10=icd, drug=drug, strength=strength,
                quantity=qty, days=days, trials=[dict(drug=meds[0], start=a, end=b, outcome=rng.choice(OUTCOMES)), dict(drug=meds[1], start=c, end=d, outcome=rng.choice(OUTCOMES))],
                group=f"GRP-{rng.randint(10000, 99999)}", npi=str(rng.randint(1000000000, 1999999999)), phone=f"(555) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}", other=rng.choice(UNRELATED), other_since=iso_day(rng, 2015, 2021))


CSS = """@page{size:letter}body{margin:54px 60px;color:#141414;font:15px/1.5 %(font)s}h2{font-size:21px;margin:0 0 4px}h3{font-size:16px;margin:20px 0 6px}.head{display:flex;justify-content:space-between;border-bottom:2px solid #333;padding-bottom:6px;margin-bottom:14px}
.small{font-size:12px;color:#444}table{border-collapse:collapse;width:100%%}td,th{padding:6px 8px;text-align:left;vertical-align:top}table.grid td,table.grid th{border:1px solid #555}table.form td{border-bottom:1px solid #888}table.form td:first-child{width:38%%;font-size:13px;color:#333}
.h{display:inline-block;font-family:'%(hand)s';font-size:%(hsize)spx;line-height:1.1;color:#16204f}.foot{position:fixed;bottom:34px;left:60px;right:60px;font-size:11.5px;color:#555;border-top:1px solid #999;padding-top:4px}.cols{display:flex;gap:26px}.cols>div{flex:1}"""


class Render:
    """Turns one person's facts into pages. `hand` makes the filled-in values look handwritten."""

    def __init__(self, p: dict, rng: random.Random, hand: str | None, dates: str):
        self.p, self.rng, self.hand, self.dates = p, rng, hand, dates

    def v(self, value) -> str:
        if not self.hand:
            return str(value)
        return f"<span class=h style='transform:rotate({self.rng.uniform(-1.6, 1.6):.2f}deg)'>{value}</span>" if value != "" else ""

    def d(self, iso: str) -> str:
        return self.v(date_style(iso, self.dates))

    def cover(self, pages: int) -> str:
        return (f"<h2>FAX</h2><table class=form><tr><td>To</td><td>Utilization Management</td></tr><tr><td>From</td><td>Brookline Behavioral Clinic</td></tr><tr><td>Pages</td><td>{pages}</td></tr><tr><td>Re</td><td>Medication request</td></tr></table>"
                "<p style='margin-top:60px' class=small>CONFIDENTIAL. This fax is intended only for the addressee. If you received it in error, destroy it and notify the sender.</p>")

    def intake(self) -> str:
        p, r = self.p, self.rng
        label = r.choice(MEMBER_LABELS)
        return (f"<div class=head><b>Brookline Behavioral Clinic</b><span class=small>Patient summary</span></div><table class=form><tr><td>Patient name</td><td>{self.v(p['last'] + ', ' + p['first'])}</td></tr>"
                f"<tr><td>Date of birth</td><td>{self.d(p['dob'])}</td></tr><tr><td>Phone</td><td>{self.v(p['phone'])}</td></tr><tr><td>{label}</td><td>{self.v(p['member_id'])}</td></tr><tr><td>Group number</td><td>{self.v(p['group'])}</td></tr>"
                f"<tr><td>Diagnosis being treated</td><td>{self.v(p['problem'] + ' (' + p['icd10'] + ')')}</td></tr><tr><td>Other conditions</td><td>{self.v('Type 2 diabetes (E11.9)')}</td></tr><tr><td>Allergies</td><td>{self.v('NKDA')}</td></tr></table>")

    def history(self, foot: bool = True) -> str:
        p = self.p
        rows = "".join(f"<tr><td>{self.v(t['drug'])}</td><td>{self.d(t['start'])}</td><td>{self.d(t['end'])}</td><td>{self.v(t['outcome'])}</td></tr>" for t in p["trials"])
        request = f"<p>Now requesting: {self.v(p['drug'] + ' ' + p['strength'])}</p>" if foot else ""
        return (f"<div class=head><b>Medication history</b><span class=small>{p['first']} {p['last']}</span></div><h3>Stopped medications</h3><table class=grid><tr><th>Medication</th><th>Started</th><th>Stopped</th><th>Result</th></tr>{rows}</table>"
                f"<h3>Current, unrelated to this request</h3><p>{self.v(p['other'])}, since {self.d(p['other_since'])}</p>{request}")

    def letter(self) -> str:
        p = self.p
        t1, t2 = p["trials"]

        def ends(t):
            parts = f"from {self.d(t['start'])}" + (f" until {self.d(t['end'])}" if t["end"] else ", and the stop date isn't recorded")
            how = {"Inadequate response": "it was stopped for inadequate response", "Intolerance": "it was stopped for intolerance", "": "the reason for stopping isn't recorded"}[t["outcome"]]
            return parts, how
        a, b = ends(t1), ends(t2)
        return (f"<div class=head><b>Brookline Behavioral Clinic</b><span class=small>Letter of medical necessity</span></div><p>To whom it may concern,</p><p>I am treating {self.v(p['first'] + ' ' + p['last'])} for {self.v(p['problem'])}. They have tried two prior medications for this condition.</p>"
                f"<p>They took {self.v(t1['drug'])} {a[0]}; {a[1]}. They then took {self.v(t2['drug'])} {b[0]}; {b[1]}.</p><p>They also take {p['other']} for an unrelated condition.</p><p>I am now requesting {self.v(p['drug'] + ' ' + p['strength'])}.</p><p style='margin-top:40px'>Sincerely,<br>Attending psychiatrist</p>")

    def order(self) -> str:
        p, r = self.p, self.rng
        return (f"<div class=head><b>Pharmacy order form</b><span class=small>Form RX-12</span></div><table class=grid><tr><td style='width:34%'>Patient</td><td>{self.v(p['first'] + ' ' + p['last'])}</td></tr><tr><td>DOB</td><td>{self.d(p['dob_order'] if 'dob_order' in p else p['dob'])}</td></tr>"
                f"<tr><td>{r.choice(MEMBER_LABELS)}</td><td>{self.v(p.get('member_order', p['member_id']))}</td></tr><tr><td>Drug</td><td>{self.v(p['drug'])}</td></tr><tr><td>Strength</td><td>{self.v(p.get('strength_order', p['strength']))}</td></tr><tr><td>Quantity</td><td>{self.v(p['quantity_shown'] if 'quantity_shown' in p else p['quantity'])}</td></tr>"
                f"<tr><td>Days supply</td><td>{self.v(p['days'])}</td></tr><tr><td>Refills</td><td>{self.v(r.randint(0, 5))}</td></tr><tr><td>Prescriber NPI</td><td>{self.v(p['npi'])}</td></tr></table><p class=small style='margin-top:30px'>Prescriber signature: ____________________</p>")


def fax(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    small = cv2.resize(g, (int(w * .72), int(h * .72)), interpolation=cv2.INTER_AREA)
    small = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32) + rng.normal(0, 14, g.shape)
    out = (small > 150).astype(np.uint8) * 255
    out[rng.random(g.shape) < .0016] = 0  # speckle
    for y in rng.integers(0, h, 3):  # dropped scan lines
        out[y:y + 1] = 255
    cv2.putText(out, f"FAX  PAGE {rng.integers(1, 9)}  {rng.integers(10, 12)}/{rng.integers(1, 28)}/2026", (24, 22), cv2.FONT_HERSHEY_PLAIN, 1.0, 0, 1)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), float(rng.uniform(-1.4, 1.4)), 1)
    out = cv2.warpAffine(out, M, (w, h), borderValue=255)
    return cv2.cvtColor(out, cv2.COLOR_GRAY2RGB)


def scan(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), float(rng.uniform(-2, 2)), 1)
    g = cv2.warpAffine(g, M, (w, h), borderValue=235)
    g = cv2.GaussianBlur(g, (0, 0), float(rng.uniform(.5, .9))).astype(np.float32) + rng.normal(0, 8, g.shape)
    return cv2.cvtColor(np.clip(g, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2RGB)


def photo(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A sheet on a desk, shot at an angle: keystone, desk showing, a shadow across the page, warm light, soft focus."""
    h, w = img.shape[:2]
    W, H = int(w * 1.16), int(h * 1.13)
    desk = np.zeros((H, W, 3), np.uint8)
    desk[:] = rng.integers(55, 110), rng.integers(45, 85), rng.integers(35, 70)
    j = lambda m: float(rng.uniform(-m, m))
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[W * .07 + j(30), H * .05 + j(22)], [W * .93 + j(30), H * .05 + j(22)], [W * .95 + j(26), H * .95 + j(22)], [W * .05 + j(26), H * .95 + j(22)]])
    out = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (W, H), dst=desk.copy(), borderMode=cv2.BORDER_TRANSPARENT).astype(np.float32)
    xx, yy = np.meshgrid(np.linspace(0, 1, W), np.linspace(0, 1, H))
    angle = rng.uniform(0, 6.28)
    light = .74 + .24 * (np.cos(angle) * xx + np.sin(angle) * yy + 1) / 2
    out *= light[..., None] * np.array([1.0, .96, .88])
    out = cv2.GaussianBlur(out, (0, 0), float(rng.uniform(.6, 1.1))) + rng.normal(0, 5, out.shape)
    ok, jpg = cv2.imencode(".jpg", np.clip(out, 0, 255).astype(np.uint8)[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(60, 82))])
    return cv2.imdecode(jpg, cv2.IMREAD_COLOR)[..., ::-1]


DAMAGE = {"typed_scan": scan, "hand_scan": scan, "fax": fax, "phone_photo": photo, "hand_photo": photo}


def build_packet(i: int, defect: str, condition: str, seed: int, used: set) -> tuple[dict, list[str]]:
    rng = random.Random(seed * 1000 + i)
    p = make_person(rng, used)
    truth = {k: p[k] for k in ("name", "dob", "member_id", "icd10", "drug", "strength", "quantity", "days")}
    truth["trials"] = [dict(t) for t in p["trials"]]
    expect = {"route": defect != "clean", "defect": defect}
    other = None
    if defect == "gap_date":
        p["trials"][1]["end"] = ""
        expect["why"] = ["gap"]
    elif defect == "gap_outcome":
        p["trials"][0]["outcome"] = ""
        expect["why"] = ["gap"]
    elif defect == "gap_quantity":
        p["quantity_shown"] = ""
        expect["why"] = ["quantity"]
    elif defect == "conflict_member":
        mid = p["member_id"]
        at = max(n for n, ch in enumerate(mid) if ch.isdigit())
        p["member_order"] = mid[:at] + str((int(mid[at]) + 3) % 10) + mid[at + 1:]
        expect["why"] = ["member_id"]
    elif defect == "conflict_dob":
        y, m, d = p["dob"].split("-")
        p["dob_order"] = f"{y}-{m}-{(int(d) % 28) + 1:02d}"
        expect["why"] = ["dob"]
    elif defect == "conflict_dose":
        p["strength_order"] = {"mg": str(float(p["strength"].split()[0]) * 2).rstrip("0").rstrip(".") + " mg"}["mg"]
        expect["why"] = ["strength"]
    elif defect == "wrong_patient":
        other = make_person(rng, used)
        expect["why"] = ["patient_name", "dob", "member_id"]
    elif defect == "date_order":
        t = p["trials"][rng.randint(0, 1)]
        t["end"] = f"{int(t['start'][:4]) - 1}{t['end'][4:]}"
        expect["why"] = ["date_order"]
    hand = rng.choice(list(FONTS)) if condition.startswith("hand") else None
    dates = rng.choice(["us", "short", "long", "abbr"])
    r = Render(p, rng, hand, dates)
    use_letter = rng.random() < .35 and defect not in ("conflict_dose",)
    if defect == "wrong_patient":  # a page from someone else's chart slipped into the stack: their full summary, in place of this patient's second page
        rest = [r.intake(), Render(other, rng, hand, dates).intake(), r.history(), r.order()]
    else:
        rest = [r.intake(), r.letter() if use_letter else r.history(), r.order()]
    if rng.random() < .5:
        rest.insert(0, r.cover(len(rest) + 1))
    font = rng.choice(["Georgia,serif", "Arial,sans-serif", "'Courier New',monospace", "'Times New Roman',serif"])
    css = CSS % {"font": font, "hand": hand or "serif", "hsize": {"Caveat": 25, "HomemadeApple": 16, "ReenieBeanie": 26, "NothingYouCouldDo": 18, "Kalam": 19, "ShadowsIntoLight": 22}.get(hand or "", 20)}
    info = dict(id=f"packet{i:02d}", condition=condition, defect=defect, hand=hand, dates=dates, letter=use_letter, truth=truth, expect=expect, other=other and other["name"])
    return info, [f"<!doctype html><style>{FACES if hand else ''}{css}</style><body>{html}</body>" for html in rest]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    plan_rng = random.Random(a.seed)
    defects = (DEFECTS * (a.count // len(DEFECTS) + 1))[:a.count]
    plan_rng.shuffle(defects)
    used: set = set()
    manifest = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(args=["--no-sandbox"])
        pg = br.new_page(viewport={"width": 850, "height": 1100}, device_scale_factor=1.6)
        for i, defect in enumerate(defects):
            condition = CONDITIONS[i % len(CONDITIONS)]
            info, pages = build_packet(i, defect, condition, a.seed, used)
            noise = np.random.default_rng(a.seed * 7 + i)
            info["pages"] = []
            for n, html in enumerate(pages):
                pg.set_content(html, wait_until="load")
                pg.evaluate("document.fonts.ready")
                buf = pg.screenshot(full_page=False)
                import io
                img = np.asarray(Image.open(io.BytesIO(buf)).convert("RGB"))
                out = DAMAGE[condition](img, noise)
                name = f"{info['id']}_{n}.jpg"
                Image.fromarray(out).save(a.out / name, quality=90)
                info["pages"].append(name)
            manifest.append(info)
            print(info["id"], condition, defect, len(pages), "pages", flush=True)
        br.close()
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
