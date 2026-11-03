"""A screen on another computer, over VNC, and the one front door that learns any job as a plan or a program.
Tested against a small fake VNC server, so no network, model or real screen is needed."""
import json
import socket
import struct
import threading
import zlib

import numpy as np
import pytest

from autoharness import config, library, targets, uiteam
from autoharness.vnc import VncError, VncScreen, parse_address


def test_addresses():
    assert parse_address("vnc://gamepc") == ("gamepc", 5900, None)
    assert parse_address("vnc://gamepc:1") == ("gamepc", 5901, None)
    assert parse_address("vnc://10.0.0.5:5905") == ("10.0.0.5", 5905, None)
    assert parse_address("vnc://:pa%20ss@mac.local:5900") == ("mac.local", 5900, "pa ss")
    with pytest.raises(ValueError):
        parse_address("http://gamepc")


def test_a_password_in_the_address_stays_out_of_the_target(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    spec = targets.spec_from_text("vnc://:hunter2@gamepc:1")
    assert spec == {"id": "custom", "name": "gamepc", "kind": "vnc", "url": "vnc://gamepc:5901"}
    assert "hunter2" not in json.dumps(spec)
    kept = tmp_path / "logins.json"
    assert json.loads(kept.read_text())["vnc://gamepc:5901"] == {"password": "hunter2"}
    assert kept.stat().st_mode & 0o777 == 0o600
    assert targets._secret("vnc://gamepc:5901") == "hunter2"


class FakeServer:
    """Speaks just enough RFB 3.8: no password, a 1600 x 1000 screen sent once raw and once through zlib, then records input."""

    def __init__(self, offer=(1,)):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.offer = offer
        self.got: list[tuple] = []
        self.done = threading.Event()
        threading.Thread(target=self.serve, daemon=True).start()

    def recv(self, c, n):
        buf = b""
        while len(buf) < n:
            chunk = c.recv(n - len(buf))
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    def serve(self):
        c, _ = self.sock.accept()
        try:
            c.sendall(b"RFB 003.008\n")
            assert self.recv(c, 12) == b"RFB 003.008\n"
            c.sendall(bytes([len(self.offer), *self.offer]))
            if self.recv(c, 1)[0] != 1:
                return
            c.sendall(struct.pack(">I", 0))
            self.got.append(("shared", self.recv(c, 1)[0]))
            name = b"fake"
            c.sendall(struct.pack(">HH", 1600, 1000) + bytes(16) + struct.pack(">I", len(name)) + name)
            requests = 0
            while True:
                kind = self.recv(c, 1)[0]
                if kind == 0:
                    self.recv(c, 19)
                elif kind == 2:
                    (n,) = struct.unpack(">xH", self.recv(c, 3))
                    self.got.append(("encodings", struct.unpack(f">{n}i", self.recv(c, 4 * n))))
                elif kind == 3:
                    incremental = self.recv(c, 9)[0]
                    requests += 1
                    if requests == 1:
                        # The whole screen, red, in raw pixels (blue, green, red, unused).
                        px = np.zeros((1000, 1600, 4), np.uint8)
                        px[..., 2] = 200
                        c.sendall(struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", 0, 0, 1600, 1000, 0) + px.tobytes())
                    elif requests == 2:
                        # A green square at the top left, through zlib.
                        sq = np.zeros((100, 100, 4), np.uint8)
                        sq[..., 1] = 180
                        data = zlib.compress(sq.tobytes())
                        c.sendall(struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", 0, 0, 100, 100, 6) + struct.pack(">I", len(data)) + data)
                elif kind == 4:
                    down, key = struct.unpack(">BxxI", self.recv(c, 7))
                    self.got.append(("key", down, key))
                elif kind == 5:
                    self.got.append(("pointer",) + struct.unpack(">BHH", self.recv(c, 5)))
        except (EOFError, OSError):
            pass
        finally:
            self.done.set()
            c.close()


def test_a_remote_screen_looks_and_clicks_like_the_virtual_one():
    server = FakeServer()
    s = VncScreen("127.0.0.1", server.port, max_size=(1280, 800)).start()
    try:
        assert (s.width, s.height) == (1280, 800)  # a 1600 x 1000 screen, scaled for the models
        assert ("shared", 1) in server.got  # anyone already watching stays connected
        assert next(g for g in server.got if g[0] == "encodings")[1][:3] == (6, 1, 0)
        s.wait_stable(2, 0.2)
        f = s.shot()
        assert f.shape == (800, 1280, 3)
        assert tuple(f[400, 640]) == (200, 0, 0)  # red, the right way round
        assert tuple(f[20, 20]) == (0, 180, 0)  # the zlib square arrived
        s.click(640, 400)
        s.press("ctrl+a")
        s.type("A!")
    finally:
        s.stop()
    server.done.wait(2)
    pointer = [g for g in server.got if g[0] == "pointer"]
    assert ("pointer", 1, 800, 500) in pointer and pointer[-1][1] == 0  # clicked where it was seen, then let go
    keys = [g[1:] for g in server.got if g[0] == "key"]
    assert keys == [(1, 0xFFE3), (1, ord("a")), (0, ord("a")), (0, 0xFFE3), (1, ord("A")), (0, ord("A")), (1, ord("!")), (0, ord("!"))]


def test_a_screen_that_wants_a_password_says_how_to_give_it():
    server = FakeServer(offer=(2,))
    with pytest.raises(VncError, match="vnc://:yourpassword@"):
        VncScreen("127.0.0.1", server.port).start()


def test_one_job_at_a_time_on_a_real_screen():
    server = FakeServer()
    s = VncScreen("127.0.0.1", server.port).start()
    try:
        with pytest.raises(VncError, match="already using"):
            VncScreen("127.0.0.1", server.port).start()
    finally:
        s.stop()


def test_nothing_answering_is_a_plain_error():
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    with pytest.raises(VncError, match="screen sharing"):
        VncScreen("127.0.0.1", port, timeout=2).start()


def test_a_learned_program_is_a_tool_like_a_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LIBRARY", tmp_path / "lib")
    monkeypatch.setattr(config, "HOME", tmp_path)
    pkg = library.create("Puzzle", "Win a game.", {"kind": "vnc", "url": "vnc://gamepc:5900"})
    assert "puzzle" not in uiteam.saved_plans()  # not until it has passed its trials
    pkg.update(status="ready", tool_id="puzzle", tool_job="win_game", params={})
    plans = uiteam.saved_plans()
    assert plans["puzzle"]["kind"] == "program"
    (tool,) = uiteam.plan_tools(plans["puzzle"])
    assert tool["name"] == "win_game" and "program written for this app" in tool["description"]
    assert tool["inputSchema"]["properties"] == {}
    assert uiteam.check_tool_call(plans["puzzle"], "win_game", {}) == {}
    with pytest.raises(ValueError, match="not inputs"):
        uiteam.check_tool_call(plans["puzzle"], "win_game", {"cheat": True})


@pytest.mark.parametrize("reply,way,job", [
    ('{"way": "program", "why": "Each move depends on the board.", "job": "Win Game!", "app": "Puzzle"}', "program", "win_game"),
    ('{"way": "plan", "why": "Same steps.", "job": "read_order", "app": "Orders"}', "plan", "read_order"),
    ("not json at all", "plan", "do_job"),
])
def test_spark_picks_the_way(monkeypatch, reply, way, job):
    monkeypatch.setattr(uiteam.Cloud, "respond", lambda self, **body: {"output": [{"type": "message", "content": [{"type": "output_text", "text": reply}]}]})
    chosen = uiteam.choose_way("vnc://gamepc:5900", "anything", uiteam.Meter())
    assert (chosen["way"], chosen["job"]) == (way, job)


def test_a_remote_app_is_alive_while_its_screen_is():
    class Screen:
        error = None
    screen = Screen()
    target = targets.Target({"kind": "vnc", "url": "vnc://gamepc:5900"}, screen)
    assert target.alive()  # nothing here started it, so there's no process to watch
    screen.error = "lost the screen"
    assert not target.alive()


def test_on_a_screen_that_isnt_reset_the_judge_sees_where_the_run_began():
    from autoharness.teacher import KEPT_SCREEN_NOTE, judge_final_screen, kept_screen
    sent = {}

    class Cloud:
        def respond(self, **body):
            sent.update(body)
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"achieved": false, "why": "left from before"}'}]}]}
    frame = np.zeros((8, 8, 3), np.uint8)
    verdict = judge_final_screen(Cloud(), "Win a game.", frame, "won", start=frame)
    content = sent["input"][0]["content"]
    assert [c["type"] for c in content].count("input_image") == 2
    assert any("doesn't count" in c.get("text", "") for c in content)
    assert verdict == {"achieved": False, "why": "left from before"}
    judge_final_screen(Cloud(), "Win a game.", frame, "won")
    assert [c["type"] for c in sent["input"][0]["content"]].count("input_image") == 1  # a fresh screen needs only the end
    assert kept_screen({"kind": "vnc"}) and not kept_screen({"kind": "desktop"}) and not kept_screen(None)
    assert "starting a new game" in KEPT_SCREEN_NOTE


def test_a_screen_that_never_stops_moving_a_little_can_still_settle():
    """Games animate: a few sprites change on every look. Opted in, small endless changes count as still; big ones never do."""
    from autoharness.desktop import Display

    class Moving(Display):
        def __init__(self, patch):
            self.patch, self.n = patch, 0

        def shot(self):
            self.n += 1
            f = np.zeros((100, 100, 3), np.uint8)
            f[: self.patch, : self.patch] = 255 * (self.n % 2)  # the same patch flickers forever
            return f
    sprite = Moving(4)  # 16 pixels of 10,000: under 0.2%
    assert not sprite.wait_stable(0.4, quiet=0.1) and sprite.small_unsettled == 1  # as before, unless asked
    assert sprite.wait_stable(0.4, quiet=0.1, ignore_small=True)
    assert not Moving(30).wait_stable(0.4, quiet=0.1, ignore_small=True)  # 9% of the screen is a real change
