"""A stand-in for another computer, so the vnc:// path can be tried on one machine: a screen with one app open, shared
over VNC by x11vnc, a standard VNC server. Autoharness then reaches it exactly as it would a Windows PC or a Mac.

    python scripts/vnc_box.py gnome-mines                      # then: autoharness teach vnc://127.0.0.1:5905 "..."
    python scripts/vnc_box.py --password playtime gnome-mines  # then: autoharness teach vnc://:playtime@127.0.0.1:5905 "..."

Ctrl+C closes it. x11vnc comes with scripts/setup_desktop.sh.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoharness.desktop import Display, find_tool  # noqa: E402


def stop(*_) -> None:
    raise KeyboardInterrupt  # closed like Ctrl+C, so the screen and the server close with it


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", nargs="+", help="the app to open, like gnome-mines")
    ap.add_argument("--port", type=int, default=5905)
    ap.add_argument("--password", help="ask viewers for this VNC password")
    ap.add_argument("--size", default="1600x1000", help="the screen's size; bigger than 1280 x 800 gets scaled down for the models")
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, stop)
    server = find_tool("x11vnc")
    if not server:
        sys.exit("x11vnc is missing: run bash scripts/setup_desktop.sh")
    w, h = (int(v) for v in args.size.split("x"))
    screen = Display(w, h).start()
    app = subprocess.Popen(["dbus-run-session", "--", find_tool(args.command[0]) or args.command[0], *args.command[1:]], env=screen.env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    share = [server, "-display", f":{screen.number}", "-rfbport", str(args.port), "-forever", "-shared", "-localhost", "-quiet"]
    with tempfile.TemporaryDirectory() as tmp:
        if args.password:
            subprocess.run([server, "-storepasswd", args.password, f"{tmp}/passwd"], env=screen.env, check=True, capture_output=True)
            share += ["-rfbauth", f"{tmp}/passwd"]
        else:
            share += ["-nopw"]
        vnc = subprocess.Popen(share, env=screen.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        login = f":{args.password}@" if args.password else ""
        print(f"{' '.join(args.command)} is open on a {w} x {h} screen, shared at vnc://{login}127.0.0.1:{args.port}", flush=True)
        print("It only listens on this machine. Ctrl+C closes it.", flush=True)
        try:
            while app.poll() is None and vnc.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            vnc.terminate()
            try:
                os.killpg(app.pid, 15)
            except OSError:
                pass
            screen.stop()


if __name__ == "__main__":
    main()
