"""Autoharness against the alternatives a skeptic would name, on the same jobs with inputs nobody has seen.

    spark              Muse Spark and the native computer tool, a screenshot at every step.
    spark_skill        The same, plus a markdown skill: everything the lesson learned, as written guidance.
    glimmer_screens    Muse Glimmer on this machine, working from screenshots.
    glimmer_skill      The same, plus the same markdown skill.
    harness            The generated program alone, with no model.
    glimmer_interface  Glimmer using only observe() and the verbs, with no screenshot.

A run counts only if it claimed success and the evidence agrees. OpenEMR is checked by logging in separately and
reading the saved record. Calculator's answer is checked by arithmetic. Spark judges every final screen. Results are
appended to docs/benchmark.jsonl, so an interrupted benchmark resumes. `report` writes docs/BENCHMARK.md from that file.
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from autoharness import cloud as cloudmod, library, targets  # noqa: E402
from autoharness.desktop import Display  # noqa: E402
from autoharness.local import Glimmer, LocalModelError  # noqa: E402
from autoharness.runtime import Runner  # noqa: E402
from autoharness.session import Session, operate  # noqa: E402
from autoharness.teacher import app_notes, baseline, goal_with_inputs, judge_final_screen  # noqa: E402

OUT = ROOT / "docs" / "benchmark.jsonl"
CAP_USD = 4.00
GLIMMER_STEPS, GLIMMER_SECONDS = 150, 1200
LOCK = threading.Lock()
FIRST = "Ada Bram Cora Dmitri Esme Farid Greta Hugo Imani Jonas Keiko Luca Mina Nils Odile Pavel Quinn Rosa Soren Tala Uri Vera Wes Xenia Yara Zane Alma Boris Celia Dov".split()
LAST = "Abara Brandt Castell Dupont Elkins Fontaine Grady Holm Ibarra Jansen Kovacs Lindqvist Moreau Novak Okafor Petrov Quigley Rinaldi Sandoval Tanaka Ulrich Varga Weiss Xiang Yilmaz Zapata Ashby Bellamy Corrigan Drummond".split()
CONTESTANTS = ["spark", "spark_skill", "glimmer_screens", "glimmer_skill", "harness", "glimmer_interface"]
CLOUD = ("spark", "spark_skill")
LABELS = {"spark": "Spark, screenshots", "spark_skill": "Spark, screenshots + markdown skill", "glimmer_screens": "Glimmer, screenshots",
          "glimmer_skill": "Glimmer, screenshots + markdown skill", "harness": "Harness code, no model", "glimmer_interface": "Glimmer + harness interface"}
CALC = ["(48 + 19) * 6", "7 * 13 - 29", "(81 - 17) * 4", "125 * 8 + 33", "(64 + 36) * 12"]
APPS = {
    "openemr": {"package": "openemr", "n": 5, "cloud_usd": 0.60, "seconds": 600},
    "calculator": {"package": "calculator", "n": 5, "cloud_usd": 0.10, "seconds": 180},
    "minesweeper": {"package": "minesweeper-6", "n": 5, "cloud_n": 2, "cloud_usd": 0.40, "seconds": 900},
}
UNSEEN = [
    ("read_dob", "Log in with username admin and password pass. Find the patient Marcus Oyelaran and report their date of birth."),
    ("set_phone", "Log in with username admin and password pass. Open the patient Priya Nakamura and set their home phone number to {phone}, then save."),
    ("count", "Log in with username admin and password pass. Report how many patient records have the last name Synthetic."),
]
GLIMMER_RULES = """You control a computer to reach a goal. Coordinates are on a 0 to 1000 grid over the screenshot, whatever its size: (0, 0) is the top left and (1000, 1000) the bottom right.

Goal: {goal}
{skill}
What you've done so far:
{history}

Look at the screenshot and choose the single next action. Reply with only JSON, one of:
{{"action": "click", "x": 500, "y": 500}}
{{"action": "double_click", "x": 500, "y": 500}}
{{"action": "right_click", "x": 500, "y": 500}}
{{"action": "type", "text": "..."}}
{{"action": "key", "keys": "Return"}}
{{"action": "scroll", "x": 500, "y": 500, "dy": 3}}
{{"action": "wait"}}
{{"finished": "what you achieved, including any answer you were asked for"}}"""


def skill_for(pkg) -> str:
    """Everything the lesson learned, as a person or model would write it down. It has no code in it."""
    m = pkg.manifest
    notes = "\n".join(f"- {n}" for n in m.get("notes", []))
    return f"{app_notes(pkg)}\n\nHow it gets done: {m.get('how', '')}\n\nThings learned the hard way:\n{notes}".strip()


def patient(contestant: str, i: int) -> dict:
    k = CONTESTANTS.index(contestant) * 5 + i
    return {"first_name": FIRST[k], "last_name": LAST[k], "date_of_birth": f"{1950 + k}-{k % 12 + 1:02d}-{k % 27 + 1:02d}", "sex": "Female" if k % 2 else "Male"}


def inputs(app: str, contestant: str, i: int) -> dict | None:
    if app == "openemr":
        return patient(contestant, i)
    if app == "calculator":
        return {"expression": CALC[i % len(CALC)]}
    return None


def oracle_process(request: dict) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto("http://127.0.0.1:8300/interface/login/login.php?site=default")
        page.fill("#authUser", "admin")
        page.fill("#clearPass", "pass")
        page.keyboard.press("Enter")
        page.wait_for_timeout(4000)
        page.goto("http://127.0.0.1:8300/interface/main/finder/dynamic_finder.php")
        page.wait_for_timeout(2500)
        page.fill("input[type=search]", request["last_name"])
        page.wait_for_timeout(2500)
        rows = [[c.strip() for c in r.split("\t")] for r in page.locator("table tbody tr").all_inner_texts()]
        rows = [r for r in rows if r and r[0].lower().startswith(request["last_name"].lower() + ",")]
        info = page.locator(".dataTables_info").first.inner_text()
        total = re.search(r"of ([\d,]+) entries", info)
        out = {"rows": len(rows), "total": int(total.group(1).replace(",", "")) if total else len(rows), "records": []}
        for row in rows[:5]:
            page.goto(f"http://127.0.0.1:8300/interface/patient_file/summary/demographics_full.php?set_pid={row[-1]}")
            page.wait_for_timeout(1500)
            out["records"].append(page.evaluate("""() => { const v = n => { const e = document.querySelector(`[name="${n}"]`);
                return e ? (e.tagName === 'SELECT' ? e.options[e.selectedIndex].text : e.value) : null };
                return {first: v('form_fname'), last: v('form_lname'), dob: v('form_DOB'), sex: v('form_sex'), phone: v('form_phone_home')} }"""))
        browser.close()
    return out


def read_records(last_name: str) -> dict:
    done = subprocess.run([sys.executable, __file__, "oracle", json.dumps({"last_name": last_name})], capture_output=True, text=True, timeout=120)
    if done.returncode:
        return {"error": done.stderr[-300:], "rows": 0, "records": []}
    return json.loads(done.stdout.strip().splitlines()[-1])


def check_patient(params: dict) -> tuple[bool, str]:
    found = read_records(params["last_name"])
    match = [r for r in found["records"] if r["first"] == params["first_name"] and r["last"] == params["last_name"]]
    if len(match) != 1:
        return False, f"{len(match)} matching records, expected exactly 1"
    r = match[0]
    if r["dob"] != params["date_of_birth"] or r["sex"] != params["sex"]:
        return False, f"saved wrong: {r}"
    return True, "the saved record is correct"


def check_answer(expression: str, text: str) -> tuple[bool, str]:
    want = eval(expression, {"__builtins__": {}})  # noqa: S307 - the constants above
    found = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    ok = any(float(x) == want for x in found)
    return ok, f"expected {want}"


def glimmer_screens(display, target, goal: str, skill: str, seconds: float, max_steps: int = 40) -> dict:
    glimmer = Glimmer()
    target.reset()
    t0 = time.time()
    history: list[str] = []
    answer, steps, prompt_tokens = None, 0, 0
    status = "ran out of steps"
    guide = f"\nA guide to this app, written by someone who has already learned it:\n{skill}\n" if skill else ""
    while steps < max_steps:
        if time.time() - t0 > seconds:
            status = "ran out of time"
            break
        frame = display.shot()
        prompt = GLIMMER_RULES.format(w=display.width, h=display.height, goal=goal, skill=guide, history="\n".join(history[-15:]) or "(nothing yet)")
        try:
            a = glimmer.ask(prompt, image=frame, schema={"action": "see above", "finished": "or this"}, max_tokens=2500, strength="low")
        except LocalModelError as e:
            history.append(f"That reply couldn't be read: {str(e)[:100]}")
            steps += 1
            continue
        steps += 1
        prompt_tokens += glimmer.last_prompt_tokens or 0
        if a.get("finished"):
            answer, status = str(a["finished"]), "finished"
            break
        kind = a.get("action")
        try:
            px = lambda: (round(float(a["x"]) * display.width / 1000), round(float(a["y"]) * display.height / 1000))  # Glimmer's own grid
            if kind == "click":
                display.click(*px())
            elif kind == "double_click":
                display.click(*px(), "left", 2)
            elif kind == "right_click":
                display.click(*px(), "right")
            elif kind == "type":
                display.type(str(a.get("text", "")))
            elif kind == "key":
                display.press(str(a.get("keys", "")))
            elif kind == "scroll":
                display.scroll(*px(), 0, int(a.get("dy", 3)))
            elif kind == "wait":
                time.sleep(1)
            history.append(json.dumps(a))
        except (KeyError, TypeError, ValueError, RuntimeError) as e:
            history.append(f"{json.dumps(a)} failed: {e}")
        display.wait_stable(1.5)
    return {"claimed": answer is not None, "answer": answer or "", "status": status, "seconds": round(time.time() - t0, 1), "steps": steps, "prompt_tokens": prompt_tokens}


def one_run(app: str, contestant: str, i: int, goal_override: str | None = None, params: dict | None = None) -> dict:
    cfg = APPS[app] if app in APPS else APPS["openemr"]
    pkg = library.get(cfg["package"])
    spec = pkg.manifest["target"]
    params = params if params is not None else inputs(app, contestant, i)
    goal = goal_override or goal_with_inputs(pkg.manifest["goal"], params)
    notes = app_notes(pkg)
    skill = skill_for(pkg)
    display = Display(*spec.get("size", (1280, 800))).start()
    target = targets.Target(spec, display)
    judge_cloud = cloudmod.Cloud(limit_usd=0.05)
    rec = {"app": app, "contestant": contestant, "i": i, "params": params, "at": time.time()}
    try:
        if contestant in CLOUD:
            stop = threading.Event()
            timer = threading.Timer(cfg["seconds"], stop.set)
            timer.start()
            said: list[str] = []
            out = baseline(display, target, goal, lambda e: said.append(e["text"]) if e.get("type") == "say" else None, stop, limit_usd=cfg["cloud_usd"],
                           notes=notes, skill=skill if contestant == "spark_skill" else "")
            timer.cancel()
            rec.update(claimed=out["status"] == "finished", answer=" ".join(said[-3:])[:600], status=out["status"], seconds=out["seconds"], usd=out.get("usd", 0),
                       bytes_sent=out.get("bytes_sent", 0), steps=out["turns"], actions=out["actions"], judge=out["achieved"], why=out["why"])
        else:
            if contestant in ("glimmer_screens", "glimmer_skill"):
                out = glimmer_screens(display, target, goal, skill if contestant == "glimmer_skill" else "", GLIMMER_SECONDS, GLIMMER_STEPS)
            elif contestant == "harness":
                target.reset()
                r = Runner(pkg, display, None, params, max_seconds=cfg["seconds"]).execute(local_only=True)
                out = {"claimed": r.status == "done", "answer": f"{r.summary} {json.dumps(r.result, default=str)}", "status": r.status if r.status == "done" else f"{r.status}: {r.reason}"[:200],
                       "seconds": r.seconds, "steps": r.actions, "prompt_tokens": 0}
            else:
                target.reset()
                session = Session(pkg, display, target, None)
                session.interface = pkg.manifest.get("interface") or {}
                o = operate(session, goal, lambda e: None, max_steps=25)
                out = {"claimed": o["finished"], "answer": o["answer"], "status": "finished" if o["finished"] else "stopped", "seconds": o["seconds"], "steps": o["steps"], "prompt_tokens": o["prompt_tokens"]}
            rec.update(out, usd=0.0, bytes_sent=0)
            verdict = judge_final_screen(judge_cloud, goal, display.shot(), out["answer"], notes) if out["claimed"] else {"achieved": False, "why": out["status"]}
            rec.update(judge=verdict["achieved"], why=verdict["why"], judge_usd=round(judge_cloud.meter.usd, 5))
        oracle, detail = rec["judge"], "the judge read the final screen"
        if goal_override is None and app == "openemr":
            oracle, detail = check_patient(params)
        elif goal_override is None and app == "calculator":
            oracle, detail = check_answer(params["expression"], rec.get("answer", ""))
        rec.update(oracle=oracle, oracle_detail=detail, ok=bool(rec["claimed"] and rec["judge"] and oracle))
    except Exception as e:  # noqa: BLE001 - one bad run is a data point, not the end of the benchmark
        rec.update(claimed=False, ok=False, judge=False, oracle=False, status=f"crashed: {type(e).__name__}: {e}"[:300], seconds=round(time.time() - rec["at"], 1), usd=rec.get("usd", 0), bytes_sent=rec.get("bytes_sent", 0))
    finally:
        target.stop()
        display.stop()
    return rec


def load() -> list[dict]:
    return [json.loads(x) for x in OUT.read_text().splitlines()] if OUT.exists() else []


def save(rec: dict) -> None:
    with LOCK, OUT.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"{rec['app']} {rec['contestant']} #{rec['i']}: {'PASS' if rec['ok'] else 'FAIL'} {rec.get('seconds')} s ${rec.get('usd', 0):.3f} {str(rec.get('oracle_detail') or rec.get('status'))[:110]}", flush=True)


def lane(contestant: str, apps: list[str], start_usd: float) -> None:
    done = {(r["app"], r["contestant"], r["i"]) for r in load()}
    for app in apps:
        cfg = APPS[app]
        n = cfg.get("cloud_n", cfg["n"]) if contestant in CLOUD else (cfg.get("local_model_n", cfg["n"]) if contestant.startswith("glimmer_s") else cfg["n"])
        losses = 0
        for i in range(n):
            if (app, contestant, i) in done:
                continue
            if contestant in CLOUD and cloudmod.Ledger.read()["spent_usd"] - start_usd + cfg["cloud_usd"] > CAP_USD:
                print(f"{app} {contestant} #{i}: skipped, the benchmark's ${CAP_USD} cap would be passed", flush=True)
                return
            rec = one_run(app, contestant, i)
            save(rec)
            losses = 0 if rec["ok"] else losses + 1
            if contestant.startswith("glimmer_s") and losses >= 3:
                print(f"{app} {contestant}: stopped after 3 failures in a row", flush=True)
                break


def unseen(start_usd: float) -> None:
    done = {(r["app"], r["contestant"], r["i"]) for r in load()}
    if not read_records("Nakamura")["rows"] or not read_records("Oyelaran")["rows"]:
        print("Untaught jobs need the patients Marcus Oyelaran and Priya Nakamura. Skipped.", flush=True)
        return
    for contestant, phone in (("glimmer_interface", "555-0177"), ("spark", "555-0142")):
        for i, (name, text) in enumerate(UNSEEN):
            app = f"unseen_{name}"
            if (app, contestant, i) in done:
                continue
            if contestant == "spark" and cloudmod.Ledger.read()["spent_usd"] - start_usd + 0.25 > CAP_USD:
                print(f"{app} {contestant}: skipped, the cap would be passed", flush=True)
                continue
            rec = one_run(app, contestant, i, goal_override=text.format(phone=phone), params={})
            answer = rec.get("answer", "")
            if name == "read_dob":
                rec["oracle"] = bool(re.search(r"1971-11-23|Nov\w*\.? 23,? 1971|23 Nov\w* 1971|11/23/1971", answer))
            elif name == "set_phone":
                records = read_records("Nakamura")["records"]
                rec["oracle"] = any(phone.replace("-", "") in re.sub(r"\D", "", r.get("phone") or "") for r in records)
            else:
                want = read_records("Synthetic")["total"]
                rec["oracle_detail"] = f"the patient list holds {want}"
                rec["oracle"] = str(want) in re.findall(r"\d+", answer)
            rec["ok"] = bool(rec.get("claimed") and rec["oracle"])
            save(rec)


def rescore_count() -> None:
    """The first version of the count check read only the list's first page, which holds 10 rows."""
    want = read_records("Synthetic")["total"]
    rows = load()
    for r in rows:
        if r["app"] == "unseen_count":
            r["oracle"] = str(want) in re.findall(r"\d+", r.get("answer", ""))
            r["oracle_detail"] = f"the patient list holds {want}"
            r["ok"] = bool(r.get("claimed") and r["oracle"])
            print(r["contestant"], r["ok"], r["oracle_detail"], r.get("answer", "")[-80:], flush=True)
    OUT.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))


def median(rows: list[dict], key: str):
    values = [r.get(key) or 0 for r in rows]
    return statistics.median(values) if values else 0


def report() -> None:
    rows = load()
    lines = ["# Benchmark", "", "Generated by `scripts/benchmark.py report` from `docs/benchmark.jsonl`. Nothing is typed in.", "",
             "Every run gets a fresh copy of the app and inputs that were not used in teaching. A run passes only if it claimed success and the evidence agrees:",
             "OpenEMR's saved record read through a separate login, Calculator's answer checked by arithmetic, and Spark's judgment of every final screen.",
             "Sample sizes are small, so treat these as a first measurement, not a final one.",
             "**A correction.** The first Glimmer-from-screenshots runs here went 0 of 24 because of a bug in this benchmark, not Glimmer: it clicks on a 0 to 1000 grid and the loop read those numbers as pixels, so nearly every click missed. Those runs are kept in `docs/benchmark-coordinate-bug.jsonl`. Every Glimmer screenshot run below was redone after the fix.",
             "Limits: Spark runs stop at $0.60 on OpenEMR, $0.10 on Calculator and $0.40 on Minesweeper. A run that hits its limit counts as a failure and is named below. Glimmer from screenshots gets 150 steps and 20 minutes per run, and stops after 3 failures in a row.", ""]
    for app, cfg in APPS.items():
        pkg = library.get(cfg["package"])
        teach = pkg.manifest.get("teach_usd", 0)
        lines += [f"## {pkg.manifest.get('name')}", "", f"Teaching cost ${teach:.2f}, written by {pkg.manifest.get('teacher', 'Spark')}.", "",
                  "| Contestant | Passed | Median time, all runs | Median time, passes | Cloud cost per run | Data sent per run | Lesson pays back after |", "|---|---|---|---|---|---|---|"]
        for c in CONTESTANTS:
            r = [x for x in rows if x["app"] == app and x["contestant"] == c]
            if not r:
                continue
            good = [x for x in r if x["ok"]]
            usd = median(r, "usd")
            spent_per_win = sum(x.get("usd", 0) for x in r) / len(good) if good else None
            payback = f"{teach / spent_per_win:.0f} runs" if spent_per_win else "—"
            lines.append(f"| {LABELS[c]} | {len(good)}/{len(r)} | {median(r, 'seconds'):.0f} s | {(str(round(median(good, 'seconds'))) + ' s') if good else '—'} | ${usd:.3f} | {median(r, 'bytes_sent') / 1e6:.1f} MB | {payback if c in CLOUD else '—'} |")
        lines.append("")
    extra = [x for x in rows if x["app"].startswith("unseen_")]
    if extra:
        lines += ["## OpenEMR: jobs the harness was never taught", "", "| Job | Contestant | Result | Time | Cloud cost | What it said |", "|---|---|---|---|---|---|"]
        for x in extra:
            said = re.sub(r"\s+", " ", str(x.get("answer", ""))).replace("|", "/")[:150]
            lines.append(f"| {x['app'][7:]} | {LABELS[x['contestant']]} | {'pass' if x['ok'] else 'fail'} | {x.get('seconds', 0):.0f} s | ${x.get('usd', 0):.3f} | {said} |")
        lines.append("")
    failures = [x for x in rows if not x["ok"] and x["app"] in APPS]
    if failures:
        lines += ["## Every failure", ""] + [f"- {x['app']}, {LABELS[x['contestant']]}, run {x['i'] + 1}: {str(x.get('status'))[:90]}. {str(x.get('oracle_detail') or x.get('why') or '')[:110]}" for x in failures] + [""]
    (ROOT / "docs" / "BENCHMARK.md").write_text("\n".join(lines))
    print("\n".join(lines))


def main() -> None:
    cmd = sys.argv[1]
    if cmd == "oracle":
        print(json.dumps(oracle_process(json.loads(sys.argv[2]))))
    elif cmd == "report":
        report()
    elif cmd == "rescore":
        rescore_count()
    elif cmd == "smoke":
        print(json.dumps(one_run("calculator", sys.argv[2], 0), default=str)[:900])
    elif cmd == "cloud":
        start = cloudmod.Ledger.read()["spent_usd"]
        apps = ["openemr", "calculator", "minesweeper"]
        threads = [threading.Thread(target=lane, args=(c, apps[:2], start)) for c in CLOUD]
        [t.start() for t in threads]
        [t.join() for t in threads]
        unseen(start)
        threads = [threading.Thread(target=lane, args=(c, apps[2:], start)) for c in CLOUD]
        [t.start() for t in threads]
        [t.join() for t in threads]
    elif cmd == "local":
        for c in ("harness", "glimmer_interface", "glimmer_screens", "glimmer_skill"):
            lane(c, ["openemr", "calculator", "minesweeper"], 0)
    if cmd in ("cloud", "local"):
        print("BENCHMARK LANE DONE", flush=True)


if __name__ == "__main__":
    main()
