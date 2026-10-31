"""What Autoharness can drive. A target is anything that draws on the virtual screen: a Linux desktop
app, a website in a real browser, or whatever a command starts. Reset gives a fresh instance so every
trial starts clean."""
from __future__ import annotations

import glob
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from . import config
from .desktop import Display, die_with_parent, find_tool

CATALOG_DIR = config.REPO / "targets"


def chromium_path() -> str:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found and "snap" not in found:
            return found
    hits = sorted(glob.glob(str(Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    if hits:
        return hits[-1]
    raise RuntimeError("no browser found: run scripts/setup_desktop.sh")


def catalog() -> list[dict]:
    out = []
    for f in sorted(CATALOG_DIR.glob("*.json")):
        spec = json.loads(f.read_text())
        spec.setdefault("id", f.stem)
        out.append(spec)
    return out


def get_spec(target_id: str) -> dict:
    for spec in catalog():
        if spec["id"] == target_id:
            return spec
    raise KeyError(f"unknown target: {target_id}")


def spec_from_text(text: str) -> dict:
    """Build a target from what a user typed: a URL or a command line."""
    text = text.strip()
    if text.startswith(("http://", "https://")):
        return {"id": "custom", "name": text.split("//", 1)[1].split("/")[0], "kind": "web", "url": text}
    if "." in text and " " not in text and "/" not in text.split(".")[0] and not shutil.which(text):
        return {"id": "custom", "name": text, "kind": "web", "url": "https://" + text}
    return {"id": "custom", "name": text.split()[0], "kind": "desktop", "command": text.split()}


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Target:
    def __init__(self, spec: dict, display: Display):
        self.spec = spec
        self.display = display
        self.proc: subprocess.Popen | None = None
        self.profile: str | None = None
        self._server: ThreadingHTTPServer | None = None

    @property
    def name(self) -> str:
        return self.spec.get("name", self.spec.get("id", "app"))

    def describe(self) -> str:
        s = self.spec
        return s.get("url") or " ".join(s.get("command", [])) or self.name

    def _url(self) -> str:
        s = self.spec
        if s.get("serve"):
            if not self._server:
                root = config.REPO / s["serve"]
                if not root.exists():
                    raise RuntimeError(f"missing {root}: run scripts/setup_targets.sh")
                self._server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(root)))
                threading.Thread(target=self._server.serve_forever, daemon=True).start()
            return f"http://127.0.0.1:{self._server.server_port}/{s.get('path', '')}"
        return s["url"]

    def _command(self) -> list[str]:
        s = self.spec
        if s["kind"] == "web":
            w, h = self.display.width, self.display.height
            return [chromium_path(), "--no-sandbox", "--no-first-run", "--no-default-browser-check",
                    "--disable-gpu", "--disable-infobars", "--disable-translate", "--password-store=basic",
                    "--disable-features=Translate,InfiniteSessionRestore", f"--window-size={w},{h}",
                    "--window-position=0,0", f"--user-data-dir={self.profile}", f"--app={self._url()}"]
        cmd = list(s["command"])
        exe = find_tool(cmd[0]) or cmd[0]
        return ["dbus-run-session", "--", exe, *cmd[1:]]

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _kill(self) -> None:
        if self.proc is not None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.wait(3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                    self.proc.wait(2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            self.proc = None
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = None

    def reset(self, settle: float | None = None) -> np.ndarray:
        """Start a fresh instance with an empty profile and return its first steady frame."""
        self._kill()
        self.profile = tempfile.mkdtemp(prefix="autoharness-app-")
        env = dict(self.display.env)
        # A fresh home each time, so the app has no saved game or login from the last run.
        env.update(HOME=self.profile, XDG_CONFIG_HOME=self.profile + "/config",
                   XDG_CACHE_HOME=self.profile + "/cache", XDG_RUNTIME_DIR=self.profile,
                   XDG_DATA_HOME=self.profile + "/data")
        env.update(self.spec.get("env", {}))
        log = open(self.profile + "/app.log", "wb")
        self.proc = subprocess.Popen(self._command(), env=env, stdout=log, stderr=log, start_new_session=True,
                                     cwd=self.profile, preexec_fn=die_with_parent)
        settle = settle if settle is not None else self.spec.get("settle", 1.0)
        deadline = time.time() + self.spec.get("start_timeout", 25)
        while time.time() < deadline:
            frame = self.display.shot()
            if frame.std() > 4:
                break
            if self.proc.poll() is not None:
                tail = open(self.profile + "/app.log", "rb").read()[-400:].decode("utf8", "replace")
                raise RuntimeError(f"{self.name} exited immediately: {tail}")
            time.sleep(0.1)
        else:
            raise RuntimeError(f"{self.name} never drew anything on screen")
        self.display.wait_stable(timeout=self.spec.get("start_timeout", 25) / 2, quiet=settle)
        return self.display.shot()

    def stop(self) -> None:
        self._kill()
        if self._server:
            self._server.shutdown()
            self._server = None
