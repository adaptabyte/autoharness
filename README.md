# Auto-Harness: one agent that learns to play any game

A smart, slow model explores a game and builds a streamlined harness for
it; a small, fast model then plays in near-realtime using that harness.
The same three tiers generalize beyond games to any UI/world: explore
once with intelligence, compile what was learned into cheap machinery,
then act fast forever.

## The three tiers

| Tier | Model | Job |
| --- | --- | --- |
| 1. Explorer | Muse Wonder (multimodal) | Slowly probes the UI/world, reads the manual, records screens, controls, and transitions into a `GameKnowledge` file |
| 2. Synthesis | (deterministic code) | Compiles knowledge into a `GameSpec`: screen signatures, a transition graph, named macros, a goal detector |
| 3. Runtime | Muse Glimmer (local, NVFP4) | Per frame: classify state by cheap 32x32 signature (no LLM), BFS the graph toward the goal, execute the next macro. The LLM is consulted only on unknown states |

Key idea: perception and navigation are *compiled away* by synthesis.
The fast model never perceives from scratch — it decides among a handful
of named macros, which is what makes a small model reliable at speed.


## WebUI

A browser console for the whole system — configure both model tiers,
watch the game live while the agent explores/plays, and read the
synthesized harness as it is built.

```bash
python -m webui.server --port 8765   # then open http://localhost:8765
```

- **Smart tier**: Meta model API base URL + API key + model (e.g. a Muse
  Wonder endpoint). The key is held in server memory for the job only —
  never written to disk.
- **Fast tier**: your local Glimmer server base URL (default
  `http://localhost:8001/v1`, model `muse-glimmer`). Use
  "Test connection" on both tiers before running.
- **Targets**: the built-in demo game works anywhere. Real games use the
  X11 backend (Linux, needs `xdotool` + `ffmpeg`): enter the game
  window's title, explore once with the smart tier, then play.

### Run it on another computer (where the game is)

```bash
git clone https://github.com/adaptabyte/autoharness.git
cd autoharness
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m webui.server --port 8765
```

Only `numpy` and `pillow` are required; the WebUI itself uses the Python
standard library. To also serve Glimmer locally on that machine, see
"Serving Muse Glimmer NVFP4" below (NVIDIA Blackwell GPU required for
NVFP4; otherwise point the fast tier at any OpenAI-compatible endpoint).

## Quick start (no GPU needed)

```bash
uv venv .venv && uv pip install -p .venv/bin/python -e . pytest
.venv/bin/python -m autoharness.cli demo --manual games/demo_manual.txt --steps 4000
.venv/bin/python -m pytest tests/ -q
```

The demo explores the built-in game, synthesizes a harness, and wins a
fresh run of the game with zero LLM calls in the runtime loop.

## Playing a real game

1. Explore (smart tier): point `--smart-url` at a Wonder endpoint and use
   `X11Env` (ffmpeg x11grab + xdotool) against the game window; pass the
   manual with `--manual manual.txt`. Output: `game_kb.json`.
2. Synthesize + play (fast tier): serve Glimmer (below), then
   `autoharness play --kb game_kb.json --fast-url http://localhost:8001/v1`.

## Serving Muse Glimmer NVFP4 on this machine

Weights: `nvidia/Muse-Glimmer-30B-NVFP4` (24.7 GB, ModelOpt mixed
FP4/FP8) download to `models/Muse-Glimmer-30B-NVFP4` via
`logs/download_glimmer.log` (already running; re-run with
`huggingface_hub.snapshot_download` if needed).

Hardware fit: 24.7 GB does not fit one 16 GB RTX 5060 Ti, so the server
tensor-parallels across four Blackwell (sm_120) cards (~6.6 GB weights
each + KV cache), where NVFP4 runs on native FP4 tensor cores. vLLM
0.32+ supports `MuseGlimmerForConditionalGeneration` natively.

```bash
uv pip install -p .venv/bin/python "vllm>=0.11"
bash serve/serve_glimmer.sh          # picks the 2 freest Blackwell GPUs
.venv/bin/python serve/check_glimmer.py
```

The launcher refuses to start if the chosen cards lack ~10 GB free each
(it will not disturb other workloads). Free the RTX 5060 Ti cards first
if it refuses. Then play with the fast tier wired to it:

```bash
.venv/bin/python -m autoharness.cli play --fast-url http://localhost:8001/v1 --fast-model muse-glimmer
```

## Layout

- [autoharness/explorer.py](autoharness/explorer.py) — Tier 1 explorer
- [autoharness/synth.py](autoharness/synth.py) — Tier 2 synthesis
- [autoharness/runtime.py](autoharness/runtime.py) — Tier 3 fast runtime
- [autoharness/env.py](autoharness/env.py) — headless + X11 game backends
- [games/demo_game.py](games/demo_game.py) — built-in test game
- [serve/serve_glimmer.sh](serve/serve_glimmer.sh) — optimized vLLM launch
