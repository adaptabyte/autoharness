#!/usr/bin/env python3
"""Made-up paperwork from outside medicine, to test whether a team designed by Muse Wonder works on documents it has never seen.
  make_other.py invoice|rental <out dir> [--count 12] [--seed 77]
Each packet is clean or has one planted defect. The truth is a flat list of values, because the plan's field names are Wonder's to choose.
A packet numbered "example" is what Wonder is shown: it never appears in the test."""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from make_packets import DAMAGE, FACES, FIRST, LAST, date_style  # noqa: E402

CSS = """body{margin:54px 60px;color:#151515;font:15px/1.5 %s}h2{font-size:22px;margin:0 0 2px}.head{display:flex;justify-content:space-between;border-bottom:2px solid #333;padding-bottom:8px;margin-bottom:16px}.small{font-size:12px;color:#444}
table{border-collapse:collapse;width:100%%;margin:10px 0}td,th{border:1px solid #666;padding:6px 9px;text-align:left}.plain td{border:0;padding:3px 0}.r{text-align:right}.h{font-family:'Caveat';font-size:25px;color:#16204f;line-height:1.05}"""
COMPANIES = "Northgate Fabrication|Halden Office Supply|Corvid Logistics|Tamarack Electric|Bluefield Packaging|Sable Point Marine|Ironwood Tool Works|Larkspur Print Co.|Meridian Fasteners|Oakline Janitorial|Ridgeway Pipe & Valve|Sunbeam Coatings".split("|")
ITEMS = [("Hex bolts, box of 100", 18.5), ("Copper fittings, 3/4 in", 6.75), ("Safety gloves, pair", 4.2), ("Copy paper, case", 41.0), ("Nitrile hose, 25 ft", 63.0), ("LED panel, 2x4", 88.5), ("Packing tape, roll", 3.15), ("Solvent cleaner, gallon", 27.9), ("Cable ties, bag", 9.4), ("Pallet wrap, roll", 22.6)]
EMPLOYERS = "Harbor Medical Group|Delphi Robotics|Cedar Valley Schools|Pine & Main Bakery|Westlake Freight|Aurora Solar|Fenwick & Dale LLP|City of Marlow|Quarry Hill Dental|Sable Coffee Roasters".split("|")


def money(x: float) -> str:
    return f"${x:,.2f}"


def table(rows, head) -> str:
    return "<table><tr>" + "".join(f"<th>{c}</th>" for c in head) + "</tr>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>"


def invoice_packet(rng: random.Random, defect: str) -> tuple[list[str], dict, list[str]]:
    vendor = rng.choice(COMPANIES)
    po = f"PO-{rng.randint(10000, 99999)}"
    inv = f"INV-{rng.randint(100000, 999999)}"
    account, routing = str(rng.randint(10000000, 99999999)), f"0{rng.randint(10000000, 99999999)}"
    items = [(name, rng.randint(2, 40), price) for name, price in rng.sample(ITEMS, 3)]
    rows = [(n, q, p, round(q * p, 2)) for n, q, p in items]
    total = round(sum(r[3] for r in rows), 2)
    style = rng.choice(["us", "long", "abbr"])
    day = f"2026-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}"
    inv_rows, inv_total, inv_account, inv_po, received = [list(r) for r in rows], total, account, po, [r[1] for r in rows]
    why = []
    if defect == "bank_changed":
        inv_account = str(rng.randint(10000000, 99999999))
        why = ["account"]
    elif defect == "total_mismatch":
        inv_total = round(total + rng.choice([100, 250, 90]), 2)
        why = ["total"]
    elif defect == "bad_sum":
        inv_rows[1][3] = round(inv_rows[1][3] + 40, 2)
        inv_total = round(sum(r[3] for r in inv_rows), 2)
        why = ["total", "amount"]
    elif defect == "po_mismatch":
        inv_po = po[:-1] + str((int(po[-1]) + 4) % 10)
        why = ["po"]
    elif defect == "short_delivery":
        received[0] = max(1, received[0] - 2)
        why = ["quantity", "qty"]
    fmt = lambda rr: [(n, q, money(p), money(a)) for n, q, p, a in rr]
    order = (f"<div class=head><h2>Purchase order</h2><span class=small>Harlow Manufacturing, Accounts Payable</span></div><table class=plain><tr><td><b>PO number</b></td><td>{po}</td></tr><tr><td><b>Date</b></td><td>{date_style(day, style)}</td></tr><tr><td><b>Vendor</b></td><td>{vendor}</td></tr>"
             f"<tr><td><b>Vendor bank account on file</b></td><td>{account}</td></tr><tr><td><b>Routing number on file</b></td><td>{routing}</td></tr></table>{table(fmt(rows), ['Item', 'Qty', 'Unit price', 'Amount'])}<p class=r><b>Order total: {money(total)}</b></p>")
    invoice = (f"<div class=head><h2>{vendor}</h2><span class=small>Invoice {inv}</span></div><table class=plain><tr><td><b>Bill to</b></td><td>Harlow Manufacturing</td></tr><tr><td><b>Invoice date</b></td><td>{date_style(day, style)}</td></tr><tr><td><b>Your PO</b></td><td>{inv_po}</td></tr></table>{table(fmt(inv_rows), ['Description', 'Qty', 'Price', 'Line total'])}"
               f"<p class=r><b>Amount due: {money(inv_total)}</b></p><p><b>Remit payment to</b><br>Account: {inv_account}<br>Routing: {routing}</p>")
    slip = (f"<div class=head><h2>Receiving report</h2><span class=small>Harlow Manufacturing, Dock 2</span></div><table class=plain><tr><td><b>Against PO</b></td><td>{po}</td></tr><tr><td><b>Vendor</b></td><td>{vendor}</td></tr></table>"
            + table([(r[0], q, "OK") for r, q in zip(rows, received)], ["Item", "Qty received", "Condition"]) + "<p class=small>Received by: dock staff</p>")
    truth = [vendor, po, account, routing, f"{total:.2f}"] + [r[0] for r in rows]
    return [order, invoice, slip], {"values": truth}, why


def rental_packet(rng: random.Random, defect: str) -> tuple[list[str], dict, list[str]]:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    employer = rng.choice(EMPLOYERS)
    gross = rng.randint(32, 95) * 100
    dob = f"{rng.randint(1965, 2002)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    start = f"{rng.randint(2018, 2024)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    style = rng.choice(["us", "long", "short"])
    stated, stub_gross, stub_name, letter_employer, letter_name = gross, gross, f"{first} {last}", employer, f"{first} {last}"
    why = []
    if defect == "income_inflated":
        stated = gross + rng.choice([800, 1200, 1500])
        why = ["income", "gross", "pay"]
    elif defect == "wrong_employer":
        letter_employer = rng.choice([e for e in EMPLOYERS if e != employer])
        why = ["employer"]
    elif defect == "other_person_stub":
        stub_name = f"{rng.choice([f for f in FIRST if f != first])} {last}"
        why = ["name", "applicant", "employee"]
    elif defect == "missing_start":
        start = ""
        why = ["start", "hire", "date"]
    application = (f"<div class=head><h2>Rental application</h2><span class=small>Linden Court Apartments</span></div><table><tr><td>Applicant</td><td class=h>{first} {last}</td></tr><tr><td>Date of birth</td><td class=h>{date_style(dob, style)}</td></tr><tr><td>Current employer</td><td class=h>{employer}</td></tr>"
                   f"<tr><td>Employment start date</td><td class=h>{date_style(start, style)}</td></tr><tr><td>Gross monthly income</td><td class=h>{money(stated)}</td></tr><tr><td>Unit applied for</td><td class=h>{rng.randint(1, 4)}{rng.choice('ABCD')}</td></tr></table>")
    stub = (f"<div class=head><h2>{employer}</h2><span class=small>Earnings statement</span></div><table class=plain><tr><td><b>Employee</b></td><td>{stub_name}</td></tr><tr><td><b>Pay period</b></td><td>October 2026</td></tr></table>"
            + table([("Regular pay", money(stub_gross)), ("Federal tax", money(-round(stub_gross * .14, 2))), ("Net pay", money(round(stub_gross * .86, 2)))], ["Description", "This period"]) + f"<p><b>Gross pay this month: {money(stub_gross)}</b></p>")
    letter = (f"<div class=head><h2>{letter_employer}</h2><span class=small>Human Resources</span></div><p>To whom it may concern,</p><p>This letter confirms that {letter_name} has been employed here since {date_style(start, style) or 'a date not available in our records'}, with gross monthly pay of {money(gross)}.</p><p style=margin-top:40px>Regards,<br>Human Resources</p>")
    truth = [f"{first} {last}", employer, f"{gross:.2f}", dob]
    return [application, stub, letter], {"values": truth}, why


KINDS = {"invoice": (invoice_packet, ["clean"] * 6 + ["bank_changed", "bank_changed", "total_mismatch", "bad_sum", "po_mismatch", "short_delivery"], "Check invoices against the purchase order and receiving report before paying."),
         "rental": (rental_packet, ["clean"] * 6 + ["income_inflated", "income_inflated", "wrong_employer", "other_person_stub", "other_person_stub", "missing_start"], "Check that a rental applicant's application, pay stub and employment letter agree.")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=KINDS)
    ap.add_argument("out", type=Path)
    ap.add_argument("--seed", type=int, default=77)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    make, defects, note = KINDS[a.kind]
    rng = random.Random(a.seed)
    shuffled = list(defects)
    rng.shuffle(shuffled)
    manifest = []
    conditions = ["typed_scan", "fax", "phone_photo"]
    with sync_playwright() as pw:
        br = pw.chromium.launch(args=["--no-sandbox"])
        pg = br.new_page(viewport={"width": 850, "height": 1100}, device_scale_factor=1.6)

        def render(pages, base, condition, seed):
            noise = np.random.default_rng(seed)
            font = rng.choice(["Georgia,serif", "Arial,sans-serif", "'Times New Roman',serif"])
            names = []
            for n, html in enumerate(pages):
                pg.set_content(f"<!doctype html><style>{FACES}{CSS % font}</style><body>{html}</body>", wait_until="load")
                pg.evaluate("document.fonts.ready")
                im = np.asarray(Image.open(io.BytesIO(pg.screenshot())).convert("RGB"))
                name = f"{base}_{n}.jpg"
                Image.fromarray(DAMAGE[condition](im, noise)).save(a.out / name, quality=90)
                names.append(name)
            return names

        (a.out / "example").mkdir(exist_ok=True)
        pages, _, _ = make(random.Random(a.seed + 999), "clean")
        render(pages, "example/page", "typed_scan", a.seed + 999)
        for i, defect in enumerate(shuffled):
            pages, truth, why = make(rng, defect)
            condition = conditions[i % 3]
            names = render(pages, f"packet{i:02d}", condition, a.seed * 3 + i)
            manifest.append(dict(id=f"packet{i:02d}", condition=condition, defect=defect, truth=truth, expect=dict(route=defect != "clean", defect=defect, why=why), pages=names))
            print(i, condition, defect, flush=True)
        br.close()
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (a.out / "note.txt").write_text(note)


if __name__ == "__main__":
    main()
