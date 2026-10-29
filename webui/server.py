"""Auto-Harness WebUI backend — stdlib only, no extra dependencies.

Wraps the three tiers behind a small JSON API so the system can be driven
from a browser on the machine that runs the actual game:

  smart tier (explore): a high-intelligence Meta model endpoint + API key
  fast tier (play):     a local Glimmer endpoint (OpenAI-compatible)

API keys live only in server memory for the duration of a job. They are
never written to disk, logged, or returned to the browser.

Run:  python -m webui.server [--port 8765] [--host 127.0.0.1]
"""
from __future__ import annotations

import argparse
import io
import json
import threading
import time
import traceback
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
KB_DIR = ROOT / "data" / "kbs"
KB_DIR.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


def _log(job: dict, msg: str) -> None:
    job["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")


class FrameRecorder:
    """Env proxy that keeps the latest frame for the browser viewport."""

    def __init__(self, env, job: dict):
        self._env = env
        self._job = job

    def observe(self):
        obs = self._env.observe()
        try:
            buf = io.BytesIO()
            obs.frame.convert("RGB").save(buf, format="PNG")
            self._job["frame_png"] = buf.getvalue()
        except Exception:
            pass
        return obs

    def act(self, action):
        self._job["last_action"] = f"{action.kind} {action.args}"
        return self._env.act(action)


def _llm(cfg: dict):
    from autoharness.llm import MockLLM, OpenAICompatLLM
    url = (cfg or {}).get("base_url", "").strip()
    if not url or cfg.get("mock"):
        return MockLLM()
    return OpenAICompatLLM(url, cfg.get("model") or "default",
                           api_key=cfg.get("api_key") or "EMPTY")


def _make_env(job: dict, cfg: dict):
    from autoharness.env import HeadlessEnv, X11Env
    target = cfg.get("target", "demo")
    if target == "x11":
        title = cfg.get("window_title", "").strip()
        if not title:
            raise ValueError("X11 target needs a window title")
        return FrameRecorder(X11Env(title, cfg.get("display") or ":0"), job)
    from games.demo_game import DemoGame
    return FrameRecorder(HeadlessEnv(DemoGame()), job)


def _run_explore(job_id: str, cfg: dict) -> None:
    job = JOBS[job_id]
    try:
        from autoharness.explorer import Explorer
        job["phase"] = "exploring"
        _log(job, f"Smart tier: {cfg['smart'].get('base_url') or 'mock'} "
                  f"model={cfg['smart'].get('model')}")
        chunks = []
        if cfg.get("manual_text"):
            from autoharness.manual import load_manual  # noqa: F401
            import re
            chunks = [c.strip() for c in
                      re.split(r"\n\s*\n", cfg["manual_text"]) if c.strip()]
        explorer = Explorer(_make_env(job, cfg), _llm(cfg["smart"]),
                            cfg.get("game_name") or "game", chunks)
        job["explorer"] = explorer
        kb = explorer.explore(steps=int(cfg.get("steps") or 300))
        name = (cfg.get("game_name") or "game").replace("/", "_")
        path = KB_DIR / f"{name}.json"
        kb.save(path)
        job["kb_path"] = str(path)
        job["result"] = {"screens": len(kb.screens),
                         "controls": kb.controls,
                         "transitions": len(kb.transitions),
                         "kb_file": path.name}
        job["phase"] = "explored"
        _log(job, f"Exploration done: {len(kb.screens)} screens, "
                  f"{len(kb.transitions)} transitions -> {path.name}")
    except Exception:
        job["phase"] = "error"
        job["error"] = traceback.format_exc(limit=5)
        _log(job, "ERROR: " + job["error"].splitlines()[-1])


def _run_play(job_id: str, cfg: dict) -> None:
    job = JOBS[job_id]
    try:
        from autoharness.knowledge import GameKnowledge
        from autoharness.runtime import FastRuntime
        from autoharness.synth import synthesize
        job["phase"] = "synthesizing"
        kb_path = Path(cfg["kb_path"])
        if not kb_path.is_absolute():
            kb_path = KB_DIR / kb_path.name
        kb = GameKnowledge.load(kb_path)
        spec = synthesize(kb)
        job["spec"] = {"macros": len(spec.macros), "states": len(spec.states),
                       "goal": spec.goals, "policy_notes": spec.policy_notes[:400]}
        _log(job, f"Synthesized harness: {len(spec.macros)} macros, "
                  f"{len(spec.states)} states, goal={spec.goals}")
        job["phase"] = "playing"
        _log(job, f"Fast tier: {cfg['fast'].get('base_url') or 'mock'} "
                  f"model={cfg['fast'].get('model')}")
        runtime = FastRuntime(_make_env(job, cfg), spec, _llm(cfg["fast"]))
        job["runtime"] = runtime
        result = runtime.run(seconds=float(cfg.get("seconds") or 10))
        job["result"] = result
        job["phase"] = "played"
        _log(job, f"Play done: {result['decisions']} decisions at "
                  f"{result['decisions_per_sec']}/s, "
                  f"{result['llm_calls']} LLM calls")
    except Exception:
        job["phase"] = "error"
        job["error"] = traceback.format_exc(limit=5)
        _log(job, "ERROR: " + job["error"].splitlines()[-1])


def _run_demo(job_id: str, cfg: dict) -> None:
    _run_explore(job_id, cfg)
    if JOBS[job_id]["phase"] == "error":
        return
    cfg = dict(cfg, kb_path=JOBS[job_id]["kb_path"])
    _run_play(job_id, cfg)


def test_endpoint(cfg: dict) -> dict:
    """Probe an OpenAI-compatible endpoint: GET /models, then one chat call."""
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "base_url is empty"}
    key = cfg.get("api_key") or "EMPTY"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    out = {"ok": False, "base_url": base}
    try:
        t0 = time.time()
        req = urllib.request.Request(base + "/models", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            models = [m.get("id") for m in json.loads(resp.read()).get("data", [])]
        out["models"] = models
        out["models_ms"] = round((time.time() - t0) * 1000)
        model = cfg.get("model") or (models[0] if models else "default")
        body = json.dumps({"model": model, "max_tokens": 256, "messages": [
            {"role": "user", "content": "Reply with exactly: OK"}]}).encode()
        t0 = time.time()
        req = urllib.request.Request(base + "/chat/completions", data=body,
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        # Reasoning models may return content=None (budget spent thinking)
        # or put text in reasoning_content; both still prove the endpoint.
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        reply = msg.get("content") or msg.get("reasoning_content") or ""
        if not reply and data.get("output_text"):
            reply = data["output_text"]
        out.update(ok=True, model=model,
                   reply=(reply.strip() or "(empty reply — endpoint OK)")[:120],
                   chat_ms=round((time.time() - t0) * 1000))
    except Exception as exc:
        out["error"] = str(exc)[:300]
    return out


def _job_view(job: dict) -> dict:
    view = {k: job.get(k) for k in
            ("id", "kind", "phase", "result", "spec", "error", "last_action")}
    explorer = job.get("explorer")
    if explorer is not None:
        kb = explorer.kb
        view["progress"] = {"screens": len(kb.screens),
                            "transitions": len(kb.transitions),
                            "controls": kb.controls}
    runtime = job.get("runtime")
    if runtime is not None:
        view["progress"] = {"decisions": runtime.decisions,
                            "llm_calls": runtime.llm_calls}
    view["log"] = job["log"][-80:]
    return view


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep console clean
        pass

    def _json(self, obj, status=200):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        self.path = self.path.split("?")[0]  # frame URLs carry ?t= cache-busters
        if self.path in ("/", "/index.html"):
            data = (STATIC / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/api/kbs":
            self._json({"kbs": sorted(p.name for p in KB_DIR.glob("*.json"))})
        elif self.path.startswith("/api/jobs/"):
            job = JOBS.get(self.path.split("/")[3].split("?")[0])
            if job is None:
                self._json({"error": "no such job"}, 404)
            elif self.path.endswith("/frame.png"):
                png = job.get("frame_png")
                if not png:
                    self._json({"error": "no frame yet"}, 404)
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(png)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(png)
            else:
                self._json(_job_view(job))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        cfg = self._body()
        if self.path == "/api/test-endpoint":
            self._json(test_endpoint(cfg))
            return
        kinds = {"/api/jobs/explore": ("explore", _run_explore),
                 "/api/jobs/play": ("play", _run_play),
                 "/api/jobs/demo": ("demo", _run_demo)}
        if self.path not in kinds:
            self._json({"error": "not found"}, 404)
            return
        kind, fn = kinds[self.path]
        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "kind": kind, "phase": "queued", "log": [],
               "frame_png": None, "last_action": None}
        with JOBS_LOCK:
            JOBS[job_id] = job
        _log(job, f"{kind} job queued")
        threading.Thread(target=fn, args=(job_id, cfg), daemon=True).start()
        self._json({"job_id": job_id})


def main() -> None:
    ap = argparse.ArgumentParser(prog="webui")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    print(f"Auto-Harness WebUI: http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
