# Autoharness

**Stop paying a genius to click buttons.**

Every app on earth was built for human eyes and hands, and nobody is going to rebuild them all. Today's AI agents
cope by sending a frontier model a screenshot at nearly every step, which is slow, expensive, and sends everything on
your screen to the cloud.

Autoharness has Meta's models learn an app once and build the interface they wish the app had. After that, the app runs
on your own computer, with no cloud at all.

> Computer use becomes the compiler, not the runtime. For the models, by the models.

## Measured against plain computer use

Same jobs, new inputs each run, with passes checked by evidence: OpenEMR's saved record read through a separate login, Calculator's answer checked by arithmetic, and a separate model judging every final screen. Runs passed, median time, cloud cost per run:

| | OpenEMR, a records system | Calculator | Minesweeper |
|---|---|---|---|
| Spark, a screenshot every step | 5/5, 286 s, $0.16 | 4/5, 24 s, $0.022 | 0/2, 422 s, $0.41 |
| Spark + written guide | 5/5, 253 s, $0.18 | 5/5, 13 s, $0.016 | 0/1, 583 s, $0.40 |
| Glimmer, screenshots | 3/5, 395 s, $0 | 4/5, 283 s, $0 | 0/3, 1203 s, $0 |
| Glimmer + written guide | 5/5, 165 s, $0 | 5/5, 82 s, $0 | 0/3, 1210 s, $0 |
| The program alone | 4/5, 81 s, $0 | 5/5, 3 s, $0 | 4/5, 46 s, $0 |
| **Glimmer + the program** | **5/5, 111 s, $0** | **5/5, 15 s, $0** | **5/5, 48 s, $0** |

Teaching cost $1.02, $1.04 and $1.56, once. These are small samples. Spark's Minesweeper runs were stopped at my $0.40 limit, and it has won with more money ($0.28 in one earlier race). Full report, including every failure: [docs/BENCHMARK.md](docs/BENCHMARK.md).

**Couldn't this just be a markdown skill?** On form apps, largely yes. A written guide took Glimmer to 5 of 5 on OpenEMR and Calculator, and it is far cheaper to make. The program is faster and handled the game that takes real logic, where the guide went 0 of 3. A program also gives any model a typed interface, and a place for a sandbox and proof runs.

## How it works

| | Who | What happens | Cost |
|---|---|---|---|
| **Explore** | Muse Spark, SAM 3.1 | Uses the app through computer use, with no instructions and no API, and works out how it behaves | Cloud, once |
| **Compile** | Muse Wonder | Writes a program that gives models the app as compact state and typed verbs, tests it on recordings and on the live app | Cloud, once |
| **Verify** | The program alone, then an independent judge | Must pass on fresh copies with no cloud. Muse Spark, a different model that never saw the code, judges each final screen | Cloud, once |
| **Prove the interface** | Glimmer alone, then the judge | Glimmer must reach the goal using only the state and verbs, with no screenshot, and the judge checks the real screen | Local, plus the judge |
| **Run** | Code, then Muse Glimmer | Code does the routine steps. Glimmer, on your machine, makes judgment calls and clears surprises | Local, no cloud |
| **Repair** | Muse Wonder, only if needed | If the app changes and local recovery fails, the teacher is called back once to fix the program | Cloud, rarely, and can be switched off |

The output is a plain folder that exports as one shareable `.harness` file:

```python
from sdk import verb

def observe(app) -> dict:
    """The app's state as compact JSON: the fewest tokens from which a model could decide what to do."""

@verb
def reveal_cell(app, row: int, col: int):
    """One whole operation, with typed arguments. Not a click."""

def run(app):
    """Reach the goal end to end, on top of the verbs."""
```

No person writes this, and the repo holds no code specific to any app. `tests/test_engine.py` fails the build if the
engine mentions one. The whole thing is a test of the idea that harnesses should be generated rather than crafted.

## Three ways to use what it learns

- **Run it.** The whole job, end to end, usually with no model at all.
- **Ask Glimmer.** In plain words. Glimmer works from `observe()` and the verbs, and never gets a screenshot.
- **Connect any agent.** Each app is an [MCP](https://modelcontextprotocol.io) server at `http://localhost:4140/mcp/<app>`.

## Quick start

Linux with X11 libraries. Glimmer needs a GPU, or an OpenAI-compatible endpoint elsewhere.

```bash
uv venv .venv-app --python 3.12 && uv pip install -p .venv-app/bin/python -e ".[dev]"
source .venv-app/bin/activate
scripts/setup_desktop.sh                     # the virtual screen, sample apps and a browser; sudo is optional
echo "MODEL_API_KEY=..." > .env              # from dev.meta.ai; a key stored by Muse Code also works
python -m autoharness serve                  # http://127.0.0.1:4140
```

Serve Glimmer with any of these, and point `GLIMMER_URL` at it if it isn't on `127.0.0.1:8001`:

```bash
bash serve/serve_glimmer.sh                                                  # vLLM, NVFP4, four 16 GB GPUs
llama serve -hf meta-models/Muse-Glimmer-30B-GGUF \
  --hf-file Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf -a muse-glimmer \
  -ngl 99 -c 131072 --port 8001                                              # llama.cpp, about 19 GB of VRAM
```

Scripted use: `python -m autoharness teach <target> "<goal>"`, `run <id>`, `baseline <id>`, `list`.
`python scripts/gauntlet.py` teaches every app in `targets/` from nothing and writes one table of results.

## Safety

The program that runs was written by a model, so it is treated as hostile. `tests/test_sandbox.py` attacks it from the inside.

- **Sandboxed by the kernel.** Landlock and seccomp, applied before generated code is imported. No network, no other
  files, no starting programs, no signalling other processes. If the lockdown fails, the code doesn't run.
- **No secrets, no display.** It runs with an empty environment and never holds the API key. It can only ask its parent
  process to act, over a pipe.
- **A person approves the irreversible.** Harnesses are told to call `app.confirm()` before anything like submit, send
  or delete. Nothing enforces this yet: the OpenEMR harness creates a patient without asking. Review the code before trusting
  it with anything that matters.
- **A failed repair can't replace proven code.** A repair only stays if it finishes the job. Otherwise the last proven
  version comes back, and a test holds it to that.
- **Treat what you teach it as public to the program.** Logins in a goal can end up inside the generated code, so teach
  with test accounts only.
- **Spending has a hard stop.** Every Meta API call goes through one module that keeps a ledger on disk: $4 per lesson,
  $25 overall, both configurable.
- **Local-only mode.** The one module that can reach the Meta API refuses every call during such a run.
- **The app binds to localhost.** On any other address it requires a generated token.
- **"Local" was measured, not assumed.** Watching the process's real sockets showed the OCR library's runtime (ONNX
  Runtime) connecting to Microsoft's telemetry service on its own, even with its off switch used. So OCR now runs in a
  process that gives up the ability to open sockets before that library loads, and a test holds it to that. vLLM's
  usage stats are off, and its GPU workers talk over loopback, so unplugging the network can't take the model down.

Learning sends screenshots to Meta's cloud, so **teach on synthetic data**. Nothing here has had clinical, legal or
compliance review, and it isn't intended for real patient data as it stands.

## What it can't do

It works for software that waits for you: games with turns, forms, records systems, and desktop tools. It isn't for
twitch games, since a harness reacts in tenths of a second at best. CAPTCHAs and anti-bot systems will stop it, and
you shouldn't automate software whose terms forbid it. Linux and X11 only so far. Teaching can fail, and when it does,
the app says so rather than shipping something unproven.

It only knows what it was taught. On OpenEMR jobs it was never taught, Glimmer + the program went 0 of 3 and said so, where Spark went 3 of 3. Two more things I tried and failed, with the runs kept:

- **A clinic job spanning two apps.** Reading a made-up chart and filling a fictional prior-authorization portal failed its bar, 0 of 6 with Glimmer and written guides. It got stuck holding facts across several screens. Nothing wrong was ever saved. [docs/PRIORAUTH.md](docs/PRIORAUTH.md)
- **Growing a program on request.** Two attempts to have the teacher add verbs for those untaught jobs added none. [docs/GROW.md](docs/GROW.md)

Lessons can also fail on their own. Solitaire, xcalc and 2048 haven't been proven. [docs/RESULTS.md](docs/RESULTS.md) has every app's numbers.

## Built during the hackathon

Everything in this repository was written during the Meta Global AI Developer Hackathon (Oct 27 to Nov 4, 2026), as the
commit history shows. It started from a small prototype written with Muse Code on Oct 28, and the rebuild was written
with Claude Code, directed by the author. Harnesses themselves are written by Meta's models at runtime.

Things found by testing that differ from the docs at the time: `muse-wonder-1.0` rejects the native computer tool, though it accepts
screenshots and function tools, so Spark explores and judges while Wonder writes and repairs the code. Minesweeper and Calculator were taught
before this split, with Spark doing all of it. Computer-use conversations accept images only in their first request, so compiling is a separate
conversation. They were also refused after exactly 29 turns, twice (the docs give that limit for stateless replay), so
exploring is capped below that and the comparison baseline starts a new conversation when it happens. Stored responses
can expire mid-chain, so the teacher can rebuild a conversation from disk. Spark can
believe the computer tool uses a 0 to 1000 grid. It uses pixels, as the docs say, so the prompts now say so outright. Glimmer is the opposite: it clicks on a 0 to 1000 grid even when told pixels. Missing that gave my benchmark a bug that made it look like Glimmer couldn't use a screen at all, and the report says so.

## License

Apache-2.0.
