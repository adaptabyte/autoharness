"""Finding other computers and checking their screens, against tiny fake servers: no network beyond this machine."""
import socket
import threading

import pytest

from autoharness import screens


def serve(greeting: bytes, offer: bytes):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)

    def run():
        c, _ = s.accept()
        try:
            c.sendall(greeting)
            c.recv(12)
            c.sendall(offer)
        except OSError:
            pass  # the probe may hang up first, as it does on anything that isn't a VNC screen
        finally:
            c.close()
            s.close()
    threading.Thread(target=run, daemon=True).start()
    return s.getsockname()[1]


@pytest.mark.parametrize("greeting,offer,says,ready", [
    (b"RFB 003.008\n", bytes([1, 1]), "sharing, no password", True),
    (b"RFB 003.008\n", bytes([2, 16, 2]), "sharing, with a VNC password", True),          # TightVNC offers its own type first
    (b"RFB 003.889\n", bytes([4, 30, 33, 36, 35]), "only for Apple sign-in", False),     # a Mac without the VNC password
    (b"RFB 003.889\n", bytes([5, 30, 33, 36, 35, 2]), "sharing, with a VNC password", True),
    (b"RFB 003.003\n", b"\x00\x00\x00\x02", "sharing, with a VNC password", True),
])
def test_what_a_screen_says_without_signing_in(greeting, offer, says, ready):
    r = screens.probe("127.0.0.1", serve(greeting, offer))
    assert r["open"] and says in r["says"] and r["ready"] is ready


def test_nothing_or_something_else_answering():
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    assert screens.probe("127.0.0.1", port, timeout=0.5) == {"open": False, "says": "not sharing"}
    assert "something else" in screens.probe("127.0.0.1", serve(b"HTTP/1.1 200\r\n", b""))["says"]


def test_each_system_gets_its_own_steps(monkeypatch):
    assert "VNC viewers may control screen with password" in screens.how_to_share("macOS")
    assert "TightVNC" in screens.how_to_share("windows") and "borderless" in screens.how_to_share("windows")
    assert "x11vnc" in screens.how_to_share("linux")
    assert "can't share" in screens.how_to_share("iOS")
    monkeypatch.setattr(screens, "tailscale_peers", lambda: [
        {"name": "gamepc", "os": "windows", "online": True, "address": "gamepc", "ip": "127.0.0.1"},
        {"name": "phone", "os": "iOS", "online": True, "address": "phone", "ip": "127.0.0.2"},
        {"name": "laptop", "os": "macOS", "online": False, "address": "laptop", "ip": "127.0.0.3"}])
    monkeypatch.setattr(screens, "probe", lambda host, port=5900, timeout=1.5: {"open": True, "says": "sharing, with a VNC password", "ready": True})
    got = {p["name"]: p for p in screens.survey()}
    assert got["gamepc"]["ready"] and got["laptop"]["says"] == "offline" and "can't share" in got["phone"]["says"]
