"""Other computers: which ones Autoharness can reach, which are sharing their screen, and how to turn sharing on.

A screen is shared over VNC, the screen-sharing standard that Windows, Mac and Linux all speak: it's built into every Mac,
and a free download on Windows and Linux. Nothing is installed on the other computer except that.
"""
from __future__ import annotations

import json
import shutil
import socket
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor

HOW = {
    "macOS": ("System Settings > General > Sharing: turn on Screen Sharing, click (i) next to it, and turn on "
              "\"VNC viewers may control screen with password\". Pick a password of up to 8 characters."),
    "windows": ("Install TightVNC, which is free (tightvnc.com). Choose the server, and set a password of up to 8 characters "
                "when the installer asks. Let it through the firewall. Games: use windowed or borderless mode, since some "
                "full-screen games show black to any screen sharing."),
    "linux": ("On an X11 desktop: x11vnc -usepw -forever -shared. KDE: turn on Desktop Sharing (krfb). Sway and other wlroots "
              "desktops: wayvnc. GNOME on Wayland shares over RDP, not VNC: log in with \"Ubuntu on Xorg\" and use x11vnc."),
}
NO_SCREEN = {"iOS": "Phones and tablets can't share a screen for control this way.", "android": "Phones and tablets can't share a screen for control this way."}


def how_to_share(os_name: str) -> str:
    key = {"macos": "macOS", "darwin": "macOS", "windows": "windows", "linux": "linux"}.get(str(os_name).lower(), "")
    return HOW.get(key) or NO_SCREEN.get(os_name) or "Turn on a VNC server there: built into Mac, TightVNC on Windows, x11vnc on Linux."


def probe(host: str, port: int = 5900, timeout: float = 1.5) -> dict:
    """Says whether a VNC screen answers and what sign-in it asks for, without signing in."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return {"open": False, "says": "not sharing"}
    try:
        s.settimeout(timeout)
        hello = s.recv(12)
        if not hello.startswith(b"RFB "):
            return {"open": True, "says": "something else answers on that port"}
        major, minor = int(hello[4:7]), int(hello[8:11])
        if (major, minor) < (3, 7):
            s.sendall(b"RFB 003.003\n")
            offered = [struct.unpack(">I", s.recv(4))[0]]
        else:
            s.sendall(b"RFB 003.008\n")
            n = s.recv(1)[0]
            offered = list(s.recv(n)) if n else []
        if 1 in offered:
            says = "sharing, no password"
        elif 2 in offered:
            says = "sharing, with a VNC password"
        elif 30 in offered:
            says = "sharing, but only for Apple sign-in: turn on the VNC password in Screen Sharing's settings"
        else:
            says = f"sharing, with a sign-in this doesn't speak ({offered})"
        return {"open": True, "says": says, "ready": 1 in offered or 2 in offered}
    except (OSError, IndexError, struct.error, ValueError):
        return {"open": True, "says": "something answers, but not like a VNC screen"}
    finally:
        s.close()


def tailscale_peers() -> list[dict]:
    """The computers on this one's Tailscale network, if it has one."""
    exe = shutil.which("tailscale")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=8)
        data = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    magic = bool((data.get("CurrentTailnet") or {}).get("MagicDNSEnabled"))
    peers = []
    for p in (data.get("Peer") or {}).values():
        ips = p.get("TailscaleIPs") or []
        short = str(p.get("DNSName") or "").split(".")[0]
        peers.append({"name": short or p.get("HostName"), "os": p.get("OS") or "", "online": bool(p.get("Online")),
                      "address": short if magic and short else (ips[0] if ips else ""), "ip": ips[0] if ips else ""})
    return sorted(peers, key=lambda p: (not p["online"], p["name"].lower()))


def survey() -> list[dict]:
    """Every Tailscale computer, with whether its screen is shared, checked at the same time."""
    peers = tailscale_peers()

    def check(p):
        if not p["online"]:
            return {**p, "says": "offline", "ready": False}
        if p["os"] in NO_SCREEN:
            return {**p, "says": NO_SCREEN[p["os"]], "ready": False}
        return {**p, **probe(p["ip"] or p["address"])}
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(check, peers))
