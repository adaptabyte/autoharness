#!/usr/bin/env python3
"""A printable blank packet with a made-up patient to copy in by hand, for testing the team on real pen, paper and a phone camera.
  print_form.py <out.pdf>
Never write a real patient's details on these."""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CSS = """@page{size:letter;margin:0.7in}body{font:15px/1.5 Georgia,serif;color:#111}.head{display:flex;justify-content:space-between;border-bottom:2px solid #333;padding-bottom:6px;margin-bottom:18px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #555;padding:0 9px;height:44px;text-align:left}td:first-child{width:34%}.page{break-after:page}.copy{background:#f2f2f2;border:1px dashed #777;padding:14px 18px;margin-bottom:18px;font-size:14px}"""
BLOCK = """<div class=copy><b>Copy these made-up details in by pen.</b> Patient: Ada Quillfeather. Born 03/14/1978. Member ID MBR-260417. Group GRP-40112. Diagnosis: Major depressive disorder, recurrent, moderate (F33.1).
Stopped: Sertraline 100 mg, 01/08/2024 to 08/19/2024, Inadequate response. Bupropion XL 300 mg, 09/03/2024 to 05/12/2025, Intolerance. Requesting: Vortioxetine 10 mg, quantity 30, 30 days.
To see it catch a mistake, change one digit of the member ID on the order form.</div>"""
ROWS = lambda rows: "".join(f"<tr><td>{r}</td><td></td></tr>" for r in rows)
PAGES = [BLOCK + f"<div class=head><b>Clinic intake</b><span>Patient summary</span></div><table>{ROWS(['Patient name', 'Date of birth', 'Phone', 'Member ID #', 'Group number', 'Diagnosis being treated', 'Allergies'])}</table>",
         "<div class=head><b>Medication history</b><span>Patient: ____________________</span></div><h3>Stopped medications</h3><table><tr><th>Medication</th><th>Started</th><th>Stopped</th><th>Result</th></tr>" + "<tr><td></td><td></td><td></td><td></td></tr>" * 3 + "</table><p style='margin-top:30px'>Now requesting: ________________________________</p>",
         f"<div class=head><b>Pharmacy order form</b><span>Form RX-12</span></div><table>{ROWS(['Patient', 'DOB', 'Member ID #', 'Drug', 'Strength', 'Quantity', 'Days supply', 'Refills'])}</table><p style='margin-top:30px'>Prescriber signature: ______________</p>"]


def main() -> None:
    out = Path(sys.argv[1])
    with sync_playwright() as pw:
        br = pw.chromium.launch(args=["--no-sandbox"])
        pg = br.new_page()
        pg.set_content(f"<!doctype html><style>{CSS}</style>" + "".join(f"<div class=page>{p}</div>" for p in PAGES))
        pg.pdf(path=str(out), format="Letter", print_background=True)
        br.close()


if __name__ == "__main__":
    main()
