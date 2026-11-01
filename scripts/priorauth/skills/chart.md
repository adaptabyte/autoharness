# OpenEMR — Read-Only Chart Extraction

## 1. Log in
- On the login page, enter `admin` for Username and `pass` for Password, click blue **Login**.
- Dismiss popups: Product Registration → **Ask again later**; Save password → **Not now**; Clinical Reminders → **OK**; any Issues and Encounters modal → **Cancel**.

## 2. Find the patient
- Main screen: click top-right global search (“Search by any demographics”), type the input patient's full name, press **Enter**.
- Correct: **Patient Finder** table: Full Name (“Last, First”), Home Phone, SSN, Date of Birth, External ID.
- **Trap:** per-column “Search by Name” fails. Use right-side DataTables **Search:** with the last name.
- Similar names exist and rows can shift. Wait for the exact row to stabilize, note its DOB and External ID, then click its blue name.
- **Verify:** opened header must show that patient, same External ID in parentheses, and same DOB. On mismatch, return to Finder and retry; never read a wrong chart.

## 3. Open Issues
- Click **Issues** in the patient sub-navigation.
- Correct: sections Medical Problems, Health Concerns, Allergies, Medications, Medical Devices, Surgeries, Dental Issues; rows end `(Active)`/`(Inactive)`.

## 4. Read rows
- Click the `>` expander beside every Medical Problems and Medications row. Scroll down; keep expanding until all are open — lower medications start off-screen.
- Expanded rows show labeled dates and Comments. Don't mistake **Last Modified** for Start; use labeled Start/End only.
- Plan member ID = header/Finder External ID; also record DOB.
- Medical problem: ICD-10 is the parenthesized code at the end of its title.
- Requested: the **Active** medication whose Comment says “New order”. Strength = dose ending its title; take quantity and days supply from the comment.
- Priors: every **Inactive** medication — exact title including dose, Start, End, and outcome after “Stopped:” in its Comment.

## 5. Finish
- Read-only: search, expand, scroll only; never edit, add, save, or delete.
- Recheck the header belongs to the requested patient, then report everything. If a value is unrecorded, leave it empty and list it under `missing`; never invent.
