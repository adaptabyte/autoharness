"""A private virtual screen: Xvfb plus a small window manager, with screenshots and synthetic input.

Everything the agent does goes through here, so the app under control behaves as it would for a
person and the driver does not care what kind of app it is.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

import mss
import numpy as np
from Xlib import X, XK, display as xdisplay
from Xlib.ext import xtest

from . import config

_KEY_ALIASES = {
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape", "tab": "Tab",
    "space": "space", "backspace": "BackSpace", "delete": "Delete", "del": "Delete",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right", "arrowup": "Up",
    "arrowdown": "Down", "arrowleft": "Left", "arrowright": "Right", "home": "Home", "end": "End",
    "pageup": "Page_Up", "pagedown": "Page_Down", "pgup": "Page_Up", "pgdn": "Page_Down",
    "ctrl": "Control_L", "control": "Control_L", "shift": "Shift_L", "alt": "Alt_L",
    "meta": "Super_L", "super": "Super_L", "cmd": "Super_L", "win": "Super_L", "insert": "Insert",
}
_PUNCT = {"-": "minus", "=": "equal", "[": "bracketleft", "]": "bracketright", ";": "semicolon",
          "'": "apostrophe", ",": "comma", ".": "period", "/": "slash", "\\": "backslash", "`": "grave",
          "+": "plus", " ": "space", "\n": "Return", "\t": "Tab"}
_SEARCH = ["/usr/bin", "/usr/games", str(config.SYS_ROOT.parent / "patched"), str(config.SYS_ROOT / "usr/bin"),
           str(config.SYS_ROOT / "usr/games")]


def _ensure_rootless_links() -> None:
    """A no-root install patches games to find their art under /tmp/.ahs, which a reboot clears (setup_desktop.sh)."""
    links = config.SYS_ROOT.parent / "patched" / "links.txt"
    if not links.exists():
        return
    for line in links.read_text().splitlines():
        link, _, dest = line.partition(" ")
        if link and not Path(link).is_symlink():
            Path(link).parent.mkdir(parents=True, exist_ok=True)
            os.symlink(dest, link)


def die_with_parent() -> None:
    """Runs in a new child before exec: the kernel ends it if the parent dies, however the parent dies."""
    ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0)


def find_tool(name: str) -> str | None:
    return shutil.which(name, path=os.pathsep.join(_SEARCH + [os.environ.get("PATH", "")]))


def base_env(number: int) -> dict:
    """Environment for processes on this screen. Local-prefix installs work without root."""
    root = config.SYS_ROOT / "usr"
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "LANG", "LC_ALL", "TERM", "USER", "LOGNAME")}
    env.update(DISPLAY=f":{number}", NO_AT_BRIDGE="1", GDK_BACKEND="x11", LIBGL_ALWAYS_SOFTWARE="1",
               GSETTINGS_BACKEND="memory", PATH=os.pathsep.join(_SEARCH + [env.get("PATH", "")]))
    if root.exists():
        env.update(LD_LIBRARY_PATH=str(root / "lib/x86_64-linux-gnu"),
                   XDG_DATA_DIRS=f"{root}/share:/usr/local/share:/usr/share",
                   GSETTINGS_SCHEMA_DIR=str(root / "share/glib-2.0/schemas"),
                   GUILE_LOAD_PATH=str(root / "share/guile/3.0"),
                   GUILE_LOAD_COMPILED_PATH=str(root / "lib/x86_64-linux-gnu/guile/3.0/ccache"))
    return env


class Display:
    """One virtual screen. Thread-safe: a job and the live view can use it at the same time."""

    def __init__(self, width: int = 1280, height: int = 800, number: int | None = None):
        self.width, self.height = width, height
        self.number = number
        self.procs: list[subprocess.Popen] = []
        self.env: dict = {}
        self._input_lock = threading.Lock()
        self._local = threading.local()
        self._x = None
        self._spare_keycode = None
        self.pointer = (0, 0)
        self.actions = 0

    def start(self) -> "Display":
        _ensure_rootless_links()
        xvfb = find_tool("Xvfb")
        if not xvfb:
            raise RuntimeError("Xvfb is missing: run scripts/setup_desktop.sh")
        log = subprocess.DEVNULL
        # Xvfb picks a free display itself and reports it over a pipe, so two screens can never collide.
        read_fd, write_fd = os.pipe()
        self.procs.append(subprocess.Popen(
            [xvfb, "-displayfd", str(write_fd), "-screen", "0", f"{self.width}x{self.height}x24", "-nolisten", "tcp", "-ac"],
            env=base_env(0), stdout=log, stderr=log, start_new_session=True, pass_fds=(write_fd,), preexec_fn=die_with_parent))
        os.close(write_fd)
        with os.fdopen(read_fd) as pipe:
            line = pipe.readline().strip()
        if not line:
            raise RuntimeError("Xvfb did not start")
        n = int(line)
        self.number = n
        self.env = base_env(n)
        self._x = xdisplay.Display(f":{n}")
        wm = find_tool("openbox")
        if wm:
            self.procs.append(subprocess.Popen([wm], env=self.env, stdout=log, stderr=log,
                                               start_new_session=True, preexec_fn=die_with_parent))
            time.sleep(0.2)
        return self

    def stop(self) -> None:
        for p in reversed(self.procs):
            try:
                os.killpg(p.pid, 15)
            except OSError:
                pass
        for p in self.procs:
            try:
                p.wait(3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, 9)
                except OSError:
                    pass
        self.procs.clear()

    # -- screen ------------------------------------------------------------------------------

    def shot(self) -> np.ndarray:
        grabber = getattr(self._local, "grabber", None)
        if grabber is None:
            grabber = mss.MSS(display=f":{self.number}")
            self._local.grabber = grabber
        img = grabber.grab(grabber.monitors[1])
        return np.frombuffer(img.rgb, dtype=np.uint8).reshape(img.height, img.width, 3)

    def wait_stable(self, timeout: float = 3.0, quiet: float = 0.25, region=None) -> bool:
        """Block until the screen stops changing for `quiet` seconds. False if it never settles."""
        end = time.time() + timeout
        last = None
        still_since = time.time()
        while time.time() < end:
            f = self.shot()
            if region:
                x1, y1, x2, y2 = region
                f = f[y1:y2, x1:x2]
            if last is not None and f.shape == last.shape and np.array_equal(f, last):
                if time.time() - still_since >= quiet:
                    return True
            else:
                still_since = time.time()
            last = f
            time.sleep(0.04)
        return False

    # -- input -------------------------------------------------------------------------------

    def _sync(self):
        self._x.sync()

    def move(self, x: int, y: int) -> None:
        with self._input_lock:
            xtest.fake_input(self._x, X.MotionNotify, x=int(x), y=int(y))
            self._sync()
            self.pointer = (int(x), int(y))

    def click(self, x: int, y: int, button: str | int = "left", count: int = 1) -> None:
        b = {"left": 1, "wheel": 2, "middle": 2, "right": 3, "back": 8, "forward": 9}.get(button, button)
        self.move(x, y)
        time.sleep(0.03)
        with self._input_lock:
            for _ in range(count):
                xtest.fake_input(self._x, X.ButtonPress, b)
                self._sync()
                time.sleep(0.03)
                xtest.fake_input(self._x, X.ButtonRelease, b)
                self._sync()
                time.sleep(0.03)
        self.actions += 1

    def drag(self, path: list[tuple[int, int]]) -> None:
        self.move(*path[0])
        time.sleep(0.05)
        with self._input_lock:
            xtest.fake_input(self._x, X.ButtonPress, 1)
            self._sync()
        time.sleep(0.05)
        for a, b in zip(path, path[1:]):
            for t in np.linspace(0, 1, 6)[1:]:
                self.move(int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t))
                time.sleep(0.012)
        time.sleep(0.05)
        with self._input_lock:
            xtest.fake_input(self._x, X.ButtonRelease, 1)
            self._sync()
        self.actions += 1

    def scroll(self, x: int, y: int, dx: int = 0, dy: int = 0) -> None:
        self.move(x, y)
        steps = [(5 if dy > 0 else 4, abs(dy)), (7 if dx > 0 else 6, abs(dx))]
        with self._input_lock:
            for button, n in steps:
                for _ in range(int(n)):
                    xtest.fake_input(self._x, X.ButtonPress, button)
                    xtest.fake_input(self._x, X.ButtonRelease, button)
                    self._sync()
                    time.sleep(0.01)
        self.actions += 1

    def _keycode(self, name: str):
        """(keycode, needs_shift) for a key name or a single character."""
        key = _KEY_ALIASES.get(name.lower(), name)
        keysym = XK.string_to_keysym(_PUNCT.get(key, key))
        if not keysym and len(key) == 1:
            keysym = ord(key) if ord(key) < 256 else 0x01000000 + ord(key)
        if not keysym:
            keysym = XK.string_to_keysym(key.capitalize())
        if not keysym:
            raise ValueError(f"unknown key: {name}")
        code = self._x.keysym_to_keycode(keysym)
        if code:
            shift = self._x.keycode_to_keysym(code, 0) != keysym and self._x.keycode_to_keysym(code, 1) == keysym
            return code, shift
        # A character this keyboard map lacks: borrow an unused keycode for it.
        if self._spare_keycode is None:
            lo = self._x.display.info.min_keycode
            hi = self._x.display.info.max_keycode
            table = self._x.get_keyboard_mapping(lo, hi - lo + 1)
            for i, syms in enumerate(table):
                if not any(syms):
                    self._spare_keycode = lo + i
                    break
        if self._spare_keycode is None:
            raise ValueError(f"cannot type: {name}")
        self._x.change_keyboard_mapping(self._spare_keycode, [[keysym] * 4])
        self._sync()
        time.sleep(0.03)
        return self._spare_keycode, False

    def press(self, combo: str) -> None:
        """A key or chord: 'Return', 'ctrl+a', 'ctrl+shift+t'."""
        parts = [p for p in combo.replace(" ", "+").split("+") if p] if len(combo) > 1 else [combo]
        with self._input_lock:
            held = []
            for part in parts:
                code, shift = self._keycode(part)
                if shift:
                    s, _ = self._keycode("Shift_L")
                    xtest.fake_input(self._x, X.KeyPress, s)
                    held.append(s)
                xtest.fake_input(self._x, X.KeyPress, code)
                held.append(code)
                self._sync()
            time.sleep(0.02)
            for code in reversed(held):
                xtest.fake_input(self._x, X.KeyRelease, code)
            self._sync()
        self.actions += 1

    def type(self, text: str) -> None:
        with self._input_lock:
            for ch in text:
                code, shift = self._keycode(ch)
                s = None
                if shift:
                    s, _ = self._keycode("Shift_L")
                    xtest.fake_input(self._x, X.KeyPress, s)
                xtest.fake_input(self._x, X.KeyPress, code)
                xtest.fake_input(self._x, X.KeyRelease, code)
                if s:
                    xtest.fake_input(self._x, X.KeyRelease, s)
                self._sync()
                time.sleep(0.006)
        self.actions += 1
