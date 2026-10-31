# Autoharness

**Stop paying a genius to click buttons.**

Every app on earth was built for human eyes and hands, and nobody is going to rebuild them all. Today's AI agents
cope by sending a frontier model a screenshot at nearly every step, which is slow, expensive, and sends everything on
your screen to the cloud.

Autoharness has the model learn an app once and build the interface it wishes the app had. After that, the app runs
on your own computer, with no cloud at all.

> Computer use becomes the compiler, not the runtime. For the models, by the models.

## How it works

| | Who | What happens | Cost |
|---|---|---|---|
| **Explore** | Muse Spark, SAM 3.1 | Uses the app through computer use, with no instructions and no API, and works out how it behaves | Cloud, once |
| **Compile** | Muse Spark | Writes a program that gives models the app as compact state and typed verbs, tests it on recordings and on the live app | Cloud, once |
| **Verify** | The program alone, then an independent judge | Must pass on fresh copies with no cloud. A separate model call that never saw the code judges each final screen | Cloud, once |
| **Prove the interface** | Glimmer alone, then the judge | Glimmer must reach the goal using only the state and verbs, with no screenshot, and the judge checks the real screen | Local, plus the judge |
| **Run** | Code, then Muse Glimmer | Code does the routine steps. Glimmer, on your machine, makes judgment calls and clears surprises | Local, no cloud |
| **Repair** | Muse Spark, only if needed | If the app changes and local recovery fails, the teacher is called back once to fix the program | Cloud, rarely, and can be switched off |

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
  or delete. This relies on the harness doing so: review the code before trusting it with anything that matters.
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

Results are in [docs/RESULTS.md](docs/RESULTS.md): the measured numbers, including the failures.

## Built during the hackathon

Everything in this repository was written during the Meta Global AI Developer Hackathon (Oct 27 to Nov 4, 2026), as the
commit history shows. It started from a small prototype written with Muse Code on Oct 28, and the rebuild was written
with Claude Code, directed by the author. Harnesses themselves are written by Muse Spark at runtime.

Things found by testing that differ from the docs at the time: `muse-wonder-1.0` rejected the computer tool, so Spark
does the learning. Computer-use conversations accept images only in their first request, so compiling is a separate
conversation. They were also refused after about 30 turns (the docs give a 29-pair limit for stateless replay), so
exploring is capped below that and the comparison baseline starts a new conversation when it happens. Stored responses
can expire mid-chain, so the teacher can rebuild a conversation from disk. Spark can
believe the computer tool uses a 0 to 1000 grid. It uses pixels, as the docs say, so the prompts now say so outright.

## License

Apache-2.0.
