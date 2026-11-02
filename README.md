# Autoharness

**Stop paying a genius to click buttons.**

Every interface on earth was built for human eyes and hands, and nobody is going to rebuild them all. Today's AI agents cope by sending a frontier model a screenshot at nearly every step, which is slow, expensive, and sends everything on your screen to the cloud.

Autoharness compiles an interface instead. Give it any app, website or stack of paperwork. Meta's strongest models learn it once and write a plan. After that, a small open model on your own computer runs the plan, with no cloud at all.

> Computer use becomes the compiler, not the runtime. For the models, by the models.

## Measured

Each job ran on inputs that weren't used in teaching. Results were checked against the app's own data, never the run's own claim. The pass bars were committed to git before the first run.

<!-- proof -->
| Job | Glimmer + compiled plan | Median time | Cloud per run | Muse Spark, a screenshot every step |
|---|---|---|---|---|
| A made-up insurer's portal: fill and save a five-step request | **5/5** | 122 s | $0 | 3/3, 556 s, $0.172 |
| OpenEMR: find a patient, read their birth date | **5/5** | 47 s | $0 | 3/3, 84 s, $0.036 |
| OpenEMR: change a patient's phone number | **5/5** | 83 s | $0 | 3/3, 293 s, $0.095 |
| OpenEMR: read a whole chart | **5/5** | 167 s | $0 | 3/3, 218 s, $0.091 |
| Django admin: mark an order shipped | **5/5** | 89 s | $0 | 3/3, 74 s, $0.024 |
| Django admin: read an order | **5/5** | 47 s | $0 | 3/3, 52 s, $0.016 |
| GNOME Calculator, a native desktop app | **5/5** | 15 s | $0 | 3/3, 24 s, $0.009 |
<!-- /proof -->

No run in this table saved a wrong result, though earlier plans did. A run either finished verified, or it stopped and asked for help. Samples are small. Every proof round, including the ones that missed the bar, is in [docs/PROOF.md](docs/PROOF.md).

## How it works

| | Who | What happens | Cost |
|---|---|---|---|
| **Explore** | Muse Spark | Uses the interface through computer use, once, and everything it sees and does is recorded | Cloud, once |
| **Compile** | Muse Wonder | Turns that record into a plan: general skills made of small steps | Cloud, once |
| **Prove and repair** | Muse Glimmer, then Muse Wonder | Glimmer has to run the plan alone on new inputs. Each failure goes back to Wonder with its screenshots | Cloud, once |
| **Run** | Muse Glimmer and plain code | Code walks the plan and holds all the memory. Glimmer answers one narrow question per screen | Your computer, no cloud |

The key finding is about how to use a small model. Given a whole job and a screenshot, Glimmer gets lost: it went 0 of 6 reading a chart this way. Given one narrow question at a time, the same model reads the whole chart. So the frontier model does all the deciding in advance, and the small model never has to plan or remember.

A plan is data, never code. Here's a real step sequence Wonder wrote:

```json
[{"do": "ensure", "question": "Is 'Medical Issues' heading showing?"},
 {"do": "read_list", "into": "medication_rows", "item": {"title": "the blue linked medication title text", "status": "the status word in parentheses"}, "where": "Only rows under the 'Medications' heading", "scroll": 3},
 {"do": "for_each", "list": "{medication_rows}", "as": "row", "steps": [
   {"do": "click", "target": "the small '>' expand arrow at the far left of the medication row titled '{row.title}'"},
   {"do": "read", "into": "medication_detail", "fields": {"start": "the date on the start date line in the expanded detail block"}, "types": {"start": "date"}}]}]
```

## No silent errors

"Error-free" isn't something any model can promise. This is what the code enforces instead, and `tests/test_uiteam.py` and `tests/test_team.py` check it:

- Everything typed is read back, from a close-up of the box that was clicked. A mismatch gets one retry, then the run stops.
- Everything read is read twice, from two different views of the screen, and a split gets one more look.
- Before changing a record, it reads who the record belongs to and compares that in plain code.
- If it can't find something, it stops rather than clicking somewhere nearby.
- Anything a person must do, like signing, is a hard stop in the plan. The demo portal also enforces this on its server.

## A swarm, on one small model

Each copy of the interface gets its own screen and its own memory, so several can run on one served Glimmer without confusing each other. It works, but on my hardware it barely adds speed: one job already nearly fills what four 16 GB GPUs can serve. Reads flatten at about 8 at once. A swarm needs more served capacity to pay off, which I couldn't test here.

<!-- swarm -->
| At once | Finished and verified | Wrong saved | Time for all | Jobs an hour |
|---|---|---|---|---|
| 1 | 5/5 | 0 | 610 s in a row | 30 |
| 8 | 6/8 | 0 | 630 s | 34 |
<!-- /swarm -->

## Paperwork is an interface too

A stack of pages is a read-only interface, so the same idea applies. Wonder sees one sample and writes the reading plan. Glimmer reads every page. Plain code merges the reads, compares the pages with each other, and sends every gap and contradiction to a person, side by side. Approved values then go to a compiled interface, so nothing needs a hand-written connector.

Results are in [docs/PROOF.md](docs/PROOF.md). The test pages are made up: typed scans, handwriting-style fonts, simulated faxes and phone photos. They are not real faxes or real handwriting.

One honest finding: more readers mattered less than I expected. On one 30-packet set, one reader per page matched the four-reader team. On the tuning set, one reader saved a wrong value and the team didn't. The code checks and the pages checking each other do most of the work.

## The questions you'd ask

**Couldn't this just be a markdown skill?** On simple form apps, largely. A written guide took Glimmer to 5 of 5 on registering a patient in OpenEMR. But the same guide approach went 0 of 6 reading a chart, because a guide still asks the small model to plan and remember. A plan doesn't.

**Why not just use Muse Spark?** On one-off or unfamiliar jobs, do. Spark passed every job here too, it costs only cents on small ones, and it was slightly faster on one of the Django jobs. A plan only knows what it was taught. The compiled route is for jobs that repeat, are long, or involve data that can't leave your machine: there, a small open model matched the frontier model's pass rate, with no cloud at all.

**What does teaching cost?** See the table in [docs/PROOF.md](docs/PROOF.md). The portal cost about $1.34 once, against about $0.17 for each Spark run, so it pays for itself in about 8 runs.

**Does it replace computer use?** No. The learning phase is computer use.

## What failed

Keeping these is the point. Every run is in the logs.

- Patching a plan again and again made it worse. The chart plan bloated, overfit to one patient, and went 0 of 5 on new ones. It needed recompiling and teaching on several patients.
- Interface repairs that teach on one input don't generalize. Rotating the teaching inputs did.
- The first paperwork test failed its bar with a wrong save, caused by my own code skipping a date check when a date couldn't be parsed. The first unseen run then missed my 30 s speed bar by 1.3 s, and passed it on a second unseen set only after a speed fix, at 29.9 s.
- My first design was a generated Python harness with OCR. It works and it's still here (see below), but it can't handle jobs it wasn't taught, and its medication-request programs went 0 of 2.
- A request to grow a harness with new verbs failed twice ([docs/GROW.md](docs/GROW.md)).

## Limits

- It isn't ready for real patients or real records, and nothing here has had clinical or legal review. All test data is made up.
- Every app tested is on one machine, and the samples are small.
- Teaching sends screenshots to Meta's API. Run time doesn't. Don't teach it on real records.
- A plan can't do a job that needs real reasoning at each step, like a game. For those, the generated program route below went 5 of 5 on Minesweeper where guides went 0 of 3 ([docs/BENCHMARK.md](docs/BENCHMARK.md)).

## Run it

```bash
python3 -m venv .venv-app && .venv-app/bin/pip install -e '.[dev]'
.venv-app/bin/playwright install chromium
bash scripts/setup_desktop.sh           # a virtual desktop, no root needed
bash serve/serve_glimmer.sh             # Muse Glimmer on :8001, or set GLIMMER_URL to your own server
.venv-app/bin/python scripts/priorauth/portal.py &   # the made-up portal on :8310
.venv-app/bin/python -m autoharness serve            # http://127.0.0.1:4140
```

Set `MODEL_API_KEY` to teach new interfaces. `AUTOHARNESS_BUDGET` is a hard stop on Meta API spend, enforced in code.

Reproduce the results with `scripts/uiteam/run.py` and `scripts/paperwork/evaluate.py`. `scripts/report.py` rebuilds the tables from the raw logs.

## Program mode

The first version of this idea generates a Python program for an app, with typed verbs and OCR. It's still in the app under "Program mode" and is the better tool for logic-heavy jobs. Its benchmark against plain computer use is in [docs/BENCHMARK.md](docs/BENCHMARK.md).

## How this was built

Built during the Meta Global AI Developer Hackathon by one person, a psychiatrist, directing Claude Code, which wrote most of the code. The idea, the product decisions and the direction are mine. All of the code in this repo is from the event. Meta's models power the product: Muse Spark, Muse Wonder and Muse Glimmer. No Claude model runs in the product.
