# Autoharness

**Any interface, compiled for a small model.**

Meta's frontier models learn an app once. After that, each job is a tool any agent can call. A small open model runs it on your own computer, and code checks every step.

![Muse Glimmer, a small open model, filling a five-step insurer form on my own GPUs. Each line on the right is a check that passed.](docs/hero.gif)

<sub>A real run: Muse Glimmer on four 16 GB GPUs filling a made-up insurer's five-step form. Each line on the right is a check that passed. Cloud cost: $0.</sub>

> **The finding.** One small model, one job: reading a patient's chart in OpenEMR, a real medical-records system, with made-up patients. When Glimmer was given the whole job, it went **0 for 6**. When the job was compiled, it went **5 for 5** on patients it had never seen. The model was the same both times. The only change was that a frontier model did the thinking in advance.

## Why

Nearly every interface was built for human eyes and hands: records systems, insurer portals, back offices, desktop apps. Nobody is going to rebuild them all for AI. Today's agents work around this by sending a frontier model a screenshot at almost every step. That's slow, it costs money on every run, and everything on your screen goes to the cloud.

Autoharness uses computer use as a compiler instead of a runtime. A frontier model works the interface out once. A small model then runs what it compiled, as often as needed. The interface gets a model-facing version without anyone writing one: by the models, for the models.

## How it works

```mermaid
flowchart LR
    A["Any interface<br/>web, desktop or paper"] --> B["Muse Spark explores it<br/>(cloud, once)"]
    B --> C["Muse Wonder compiles a plan<br/>and repairs it until it holds<br/>(cloud, once)"]
    C --> D["Muse Glimmer + plain code<br/>run it, every step checked<br/>(your computer, every run)"]
    D --> E["A tool any agent can call<br/>(MCP)"]
```

| Step | Who | What happens | Where |
|---|---|---|---|
| **Explore** | Muse Spark | Uses the interface once through computer use. Everything it sees and does is recorded | Cloud, once |
| **Compile** | Muse Wonder | Turns the record into a plan made of small, general skills, with every decision made in advance | Cloud, once |
| **Prove and repair** | Glimmer, then Wonder | Glimmer has to run the plan alone on new inputs. Each failure goes back to Wonder with its screenshots | Cloud, once |
| **Run** | Muse Glimmer and plain code | Code walks the plan and holds all the memory. Glimmer answers one narrow question per screen | Your computer |
| **Call** | Any agent | Each job is a tool over MCP. The caller gets only verified results back, never your screen or your login | Your computer |

The key to making a small model reliable is to never ask it to plan or remember. Given a whole job and a screenshot, Glimmer gets lost. Given one narrow question at a time, like *where is the Save button?*, *is this the Review page?* or *what does this box say?*, it's fast and accurate. So Wonder does all the deciding ahead of time, and the plan it writes is data, not code:

```json
[{"do": "ensure", "question": "Is 'Medical Issues' heading showing?"},
 {"do": "read_list", "into": "medication_rows", "item": {"title": "the blue linked medication title text", "status": "the status word in parentheses"}, "where": "Only rows under the 'Medications' heading", "scroll": 3},
 {"do": "for_each", "list": "{medication_rows}", "as": "row", "steps": [
   {"do": "click", "target": "the small '>' expand arrow at the far left of the medication row titled '{row.title}'"},
   {"do": "read", "into": "medication_detail", "fields": {"start": "the date on the start date line in the expanded detail block"}, "types": {"start": "date"}}]}]
```

## Measured

Every job below ran on inputs that weren't used in teaching. Each result was checked against the app's own data, never the run's own claim. Pass bars were committed to git before the first run.

<!-- proof -->
| Job | Glimmer + compiled plan | Median time | Cloud per run | Muse Spark, a screenshot every step |
|---|---|---|---|---|
| A made-up insurer's portal: fill and save a five-step request | **5/5** | 157 s | $0 | 3/3, 556 s, $0.172 |
| OpenEMR: find a patient, read their birth date | **5/5** | 47 s | $0 | 3/3, 84 s, $0.036 |
| OpenEMR: change a patient's phone number | **5/5** | 76 s | $0 | 3/3, 293 s, $0.095 |
| OpenEMR: read a whole chart | **5/5** | 205 s | $0 | 3/3, 218 s, $0.091 |
| Django admin: mark an order shipped | **5/5** | 72 s | $0 | 3/3, 74 s, $0.024 |
| Django admin: read an order | **5/5** | 32 s | $0 | 3/3, 52 s, $0.016 |
| GNOME Calculator, a native desktop app | **5/5** | 15 s | $0 | 3/3, 24 s, $0.009 |
<!-- /proof -->

- **35 of 35** runs on the final code, across four very different interfaces, and **none saved a wrong result**.
- **No cloud at run time.** With the Meta API unreachable, the calculator and portal jobs still passed and the spend ledger didn't move.
- **Teaching is cheap and happens once:** from $0.12 for the calculator to about $4 for OpenEMR, including repairs that didn't work. Two Django jobs it had never seen were each learned from the app's own screen: one in 243 s for $0.15, one in 127 s for $0.13.
- **Earlier rounds failed, and they're all kept.** Every round is in [docs/PROOF.md](docs/PROOF.md), including the ones that missed the bar.

## Every interface becomes a tool

A compiled job is a function: named inputs in, verified outputs back. Autoharness serves every one over the [Model Context Protocol](https://modelcontextprotocol.io), so any agent can use apps that never had an API. The agent picks the job and its inputs. The job itself runs on your computer.

```bash
# All compiled interfaces, as one MCP server. Tested with the official MCP Python SDK.
http://127.0.0.1:4140/mcp/ui
# Or just one interface
http://127.0.0.1:4140/mcp/ui/backoffice
```

Here Muse Spark is the agent, in a real run from [`scripts/ask.py`](scripts/ask.py). It joins two apps that have no API between them. Outputs are shortened:

```text
You: Renata Ashby needs a prior authorization for vortioxetine 10 mg, 30 tablets for 30 days.
     Her chart is in OpenEMR. Read it, then file the request in the insurer's portal.

muse-spark-1.3 calls openemr-chart__read_patient_chart {"first": "Renata", "last": "Ashby"}
  verified in 142 s: {"identity": {"member_id": "MBR-20863", "dob": "1983-05-14"}, "problems": [{"title": "Major depressive disorder,
                     recurrent, moderate", "code": "F33.1", "status": "Active"}], "medication_rows": [...], ...}

muse-spark-1.3 calls portal__save_request {"member_id": "MBR-20863", "dob": "1983-05-14", "drug": "vortioxetine", "strength": "10 mg",
                                           "quantity": 30, "days": 30, "icd10": "F33.1", "trials": [...]}
  verified in 159 s: {"member_on_medication": {"member_name": "Renata Ashby"}, "med_readback": {"drug": "Vortioxetine", "strength": "10 mg",
                     "quantity": "30", "days": "30"}, "added_treatments": [...], ...}

muse-spark-1.3: Chart read for Renata Ashby: MBR-20863, DOB 1983-05-14, F33.1, with prior Sertraline (inadequate response)
and Bupropion XL (intolerance).

Prior auth filed and saved as PA-837691, Awaiting prescriber signature for Vortioxetine 10 mg, 30 / 30 days.
Stopped for prescriber to sign.

The asking model cost $0.0161 in the cloud. The interface ran on this computer, for $0.
```

Every field in the saved request matches the made-up chart. The small model did all the screen work, and the frontier model spent under two cents choosing jobs and inputs.

The agent's mistakes end in a stop, not a wrong save. On this run Spark first passed `"Renata Ashby"` as the first name. The plan didn't open the closest-looking patient: it stopped and said the exact name wasn't in the results, and Spark tried again correctly. On an earlier run, Spark sent `30.0` as a quantity, and the portal job stopped before saving anything. Whole numbers are now passed on as whole numbers. All four agent runs, including the failures, are in [docs/AGENT.md](docs/AGENT.md).

The caller never sees a screenshot. A login kept in `~/.autoharness/logins.json` is filled in on your computer, and it's left out of the tool's inputs entirely. A call with a missing or unexpected input is refused before anything opens.

## No silent errors

No model can promise to be error-free. Instead, the code enforces these rules, and `tests/test_uiteam.py` and `tests/test_team.py` check them:

- **Everything typed is read back** from a close-up of the box that was clicked. A mismatch gets one retry, then the run stops.
- **Everything read is read twice**, from two different views of the screen. If the reads disagree, there's one more look.
- **Before changing a record**, it reads who the record belongs to and compares that in plain code.
- **If it can't find something, it stops** rather than clicking somewhere nearby.
- **Anything only a person may do**, like signing, is a hard stop in the plan. The demo portal also enforces this on its server.

## Paperwork is an interface too

A stack of pages is a read-only interface, so the same idea applies. Wonder looks at one sample and writes a reading plan. Glimmer reads every page. Plain code merges the reads, compares the pages with each other, and sends every gap or contradiction to a person, side by side. Approved values then go into a compiled interface, so nobody writes a connector by hand.

I'm a psychiatrist, and this is the part of my week I'd like back. In the demo, a medication request where one page has a member ID off by one digit comes to me with both versions side by side. A clean stack fills the insurer's portal and stops at the signature.

On three unseen sets of made-up packets, it saved nothing wrong and caught 35 of 36 planted errors. The pages are typed scans, handwriting-style fonts, and simulated faxes and phone photos. They aren't real faxes or real handwriting. Full results are in [docs/PROOF.md](docs/PROOF.md).

## A swarm, on one small model

Each copy of the interface gets its own screen and its own memory, so several jobs can share one served Glimmer without mixing each other up. It works, but on my hardware it barely adds speed. One job already nearly fills what four 16 GB GPUs can serve, and reads level off at about 8 at once.

<!-- swarm -->
| At once | Finished and verified | Wrong saved | Time for all | Jobs an hour |
|---|---|---|---|---|
| 1 | 5/5 | 0 | 610 s in a row | 30 |
| 4 | 4/4 | 0 | 411 s | 35 |
| 8 | 6/8 | 0 | 630 s | 34 |
<!-- /swarm -->

## Honest answers

**Why not just use Muse Spark?** For one-off or unfamiliar jobs, do. Spark passed every job here too, and on small jobs it costs only cents. A plan only knows what it was taught. The compiled route is for work that repeats, runs long, or can't leave your machine. For that work, a small open model matched the frontier model's pass rate with no cloud at all. On the portal it was also 3.5 times faster: 157 s against 556 s. Teaching the portal cost $1.34 once, against $0.17 for each Spark run, so it pays for itself in about 8 runs.

**Couldn't this just be a markdown skill?** On simple form apps, largely. A written guide took Glimmer to 5 of 5 on registering a patient in OpenEMR. But guides went 0 of 6 on reading a chart, because a guide still asks the small model to plan and remember. A plan doesn't.

**Does it replace computer use?** No. Computer use is how it learns. What changes is that a frontier model only has to work out each job once.

**What if the app changes?** The run stops and says what it couldn't find. It doesn't click somewhere nearby. You then teach that job again.

## What failed

Keeping these is the point. Every run is in the logs.

- Patching a plan again and again made it worse. The chart plan bloated, overfit to one patient, and went 0 of 5 on new ones. Recompiling it and teaching on several patients fixed that.
- The first paperwork test failed its bar with a wrong save. My own code had skipped a date check whenever a date couldn't be parsed.
- One blank answer slot in my prompt made one-field reads come back empty 11 times in 15. It looked like random failures until I measured it.
- Rental applications still fail their bar: a missing employment date got through, because Wonder marked that field optional.
- More readers per page mattered less than I expected. On unseen paperwork, one reader did about as well as a team of four in half the time.
- My first design generated a Python harness with OCR. Its medication-request programs went 0 of 2. It's still in the repo as Program mode.

## Limits

- It isn't ready for real patients or real records. Nothing here has had clinical or legal review, and all test data is made up.
- Every app was tested on one machine, and the samples are small.
- Teaching sends screenshots to Meta's API, so don't teach it on real records. Runs don't send anything.
- A plan can't do a job that needs real reasoning at every step, like a game. For those, Program mode generates a program instead, and it went 5 of 5 on Minesweeper where guides went 0 of 3 ([docs/BENCHMARK.md](docs/BENCHMARK.md)).
- Real handwriting, real faxes and a real network-cable pull are untested.

## Run it

```bash
python3 -m venv .venv-app && .venv-app/bin/pip install -e '.[dev]'
.venv-app/bin/playwright install chromium
bash scripts/setup_desktop.sh                        # a virtual desktop, no root needed
bash serve/serve_glimmer.sh                          # Muse Glimmer on :8001, or set GLIMMER_URL
.venv-app/bin/python scripts/priorauth/portal.py &   # the made-up insurer's portal on :8310
.venv-app/bin/python -m autoharness serve            # http://127.0.0.1:4140
```

- **Optional test interfaces:** OpenEMR and the Django admin. See `scripts/openemr` and `scripts/backoffice/run.py`.
- **Logins for the test interfaces:** `cp plans/logins.example.json ~/.autoharness/logins.json`. Every login in it is made up. Logins taught from the screen are saved there automatically.
- **API key:** set `MODEL_API_KEY` to teach new interfaces. `AUTOHARNESS_BUDGET` is a hard cap on Meta API spend, enforced in code.
- **Agents:** point any MCP client at `http://127.0.0.1:4140/mcp/ui`, or run `scripts/ask.py "your request"`. Jobs take 15 to 220 seconds, so set your client's tool timeout to match.
- **Reproducing results:** use `scripts/uiteam/run.py` and `scripts/paperwork/evaluate.py`. `scripts/report.py` rebuilds every table from the raw logs.
- **Tests:** `.venv-app/bin/python -m pytest tests/`.

## Built with Meta's models

| Model | Role |
|---|---|
| **Muse Spark 1.3** | Explores each interface through computer use, and judges the final screen when teaching. It also acts as the example agent in `scripts/ask.py` |
| **Muse Wonder 1.0** | Compiles what Spark did into a plan, repairs the plan from failed runs, and designs reading plans for new paperwork |
| **Muse Glimmer**, open weights | Runs everything at run time on my own GPUs through vLLM, with no cloud |

## How this was built

Built during the Meta Global AI Developer Hackathon by one person, a psychiatrist, directing Claude Code, which wrote most of the code. The idea, the product decisions and the direction are mine. All the code in this repo was written during the event. Meta's models power the product, and no Claude model runs in it.
