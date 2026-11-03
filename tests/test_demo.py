"""The live demo for judges: its login, what it refuses, its jail and its proxy. Nothing here reaches the internet."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from autoharness import config, demo, egress, jail


@pytest.mark.parametrize("ip,public", [("93.184.215.14", True), ("2606:2800:21f:cb07:6820:80da:af6b:8b2c", True), ("127.0.0.1", False),
                                       ("10.1.2.3", False), ("192.168.1.1", False), ("172.20.0.5", False), ("100.101.102.103", False),
                                       ("169.254.169.254", False), ("::1", False), ("fd00::1", False), ("::ffff:127.0.0.1", False), ("224.0.0.1", False)])
def test_what_counts_as_public(ip, public):
    assert egress.public_ip(ip) is public


class Local(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def test_the_proxy_refuses_this_machine_unless_it_is_a_demo_app():
    app = ThreadingHTTPServer(("127.0.0.1", 0), Local)
    threading.Thread(target=app.serve_forever, daemon=True).start()
    port = app.server_address[1]
    try:
        with pytest.raises(urllib.error.HTTPError) as refused:
            egress.opener().open(f"http://127.0.0.1:{port}/", timeout=5)
        assert refused.value.code == 403 and b"private network" in refused.value.read()
        egress.allow_local(port)
        assert egress.opener().open(f"http://127.0.0.1:{port}/", timeout=5).read() == b"ok"
        assert egress.opener().open(f"http://localhost:{port}/", timeout=5).read() == b"ok"
        # HTTPS goes through CONNECT, and is refused the same way before anything is sent.
        s = socket.create_connection(("127.0.0.1", egress.start()), timeout=5)
        s.sendall(b"CONNECT 192.168.1.1:443 HTTP/1.1\r\nHost: 192.168.1.1:443\r\n\r\n")
        assert s.recv(100).startswith(b"HTTP/1.1 403")
        s.close()
    finally:
        egress._allowed_local.discard(port)
        app.shutdown()


def _landlock() -> int:
    import ctypes
    return ctypes.CDLL(None, use_errno=True).syscall(444, None, 0, 1)


@pytest.mark.skipif(sys.platform != "linux" or _landlock() < 4, reason="needs Landlock 4 or later")
def test_the_jail_keeps_a_program_away_from_files_and_ports(tmp_path):
    secret = tmp_path / "home" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("api key")
    allowed = tmp_path / "profile"
    allowed.mkdir()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    code = f"""
import socket
out = []
try: open({str(secret)!r}).read(); out.append("read secret")
except PermissionError: out.append("secret refused")
open({str(allowed / 'ok.txt')!r}, "w").write("x"); out.append("wrote profile")
try: socket.create_connection(("127.0.0.1", {port}), timeout=2); out.append("connected")
except OSError: out.append("port refused")
print(",".join(out))
"""
    prefixes = sorted({sys.prefix, sys.base_prefix, os.path.realpath(sys.executable).rsplit("/bin/", 1)[0]})
    cmd = jail.command(["/usr", "/lib", "/lib64", "/etc", *prefixes], [str(allowed)], [], [sys.executable, "-c", code])
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    listener.close()
    assert out.stdout.strip() == "secret refused,wrote profile,port refused", out.stderr


def test_the_demo_uses_only_its_own_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setattr(config, "HOME", tmp_path / "demo")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("MODEL_API_KEY=the-owners-key\n")
    monkeypatch.setattr(config, "REPO", repo)
    monkeypatch.setattr(config, "DEMO", False)
    assert config.api_key() == "the-owners-key"
    monkeypatch.setattr(config, "DEMO", True)
    assert config.api_key() is None  # never the owner's
    config.save_api_key("demo-key-123")
    assert config.api_key() == "demo-key-123"
    assert (config.HOME / "api_key").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        config.save_api_key("two words")


@pytest.fixture
def demo_server(tmp_path, monkeypatch):
    from autoharness import server
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(demo, "HOME", tmp_path)
    monkeypatch.setattr(server, "DEMO_SESSIONS", {})
    monkeypatch.setattr(server, "DEMO_FAILS", {})
    monkeypatch.setattr(server.guides, "find", lambda spec, names: [])
    demo.set_login("judge", "amber-basil-cedar-0001")
    httpd = server.Server(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(base, path, body=None, cookie=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers=headers,
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_judges_must_sign_in_and_get_only_what_is_safe(demo_server, monkeypatch):
    from autoharness import server
    status, body, _ = call(demo_server, "/")
    assert status == 200 and b"Autoharness, live" in body  # the login page, nothing else
    assert call(demo_server, "/api/team")[0] == 401
    assert call(demo_server, "/api/login", {"user": "judge", "password": "wrong"})[0] == 401
    assert call(demo_server, "/api/login", {"user": "judge", "password": "amber-basil-cedar-0001"}, origin="https://evil.example")[0] == 403
    status, _, headers = call(demo_server, "/api/login", {"user": "Judge", "password": "amber-basil-cedar-0001"})
    assert status == 200 and "HttpOnly" in headers["Set-Cookie"]
    cookie = headers["Set-Cookie"].split(";")[0]
    assert call(demo_server, "/api/health", cookie=cookie)[0] == 200
    for path in ("/api/import", "/api/teach", "/api/settings/key", "/api/guides/x/share", "/api/delete", "/mcp/ui", "/api/jobs/ab/input/main"):
        status, body, _ = call(demo_server, path, {}, cookie=cookie)
        assert (status, json.loads(body)["error"]) == (404, "not in the demo"), path
    assert call(demo_server, "/apps", cookie=cookie)[0] == 404
    for target, why in (("http://192.168.1.1/", "public websites"), ("bash -c id", "can't start programs"), ("vnc://10.0.0.5", "public address"),
                        ("file:///etc/passwd", "can't start programs")):
        status, body, _ = call(demo_server, "/api/ui/teach", {"target": target, "goal": "Do it"}, cookie=cookie)
        assert status == 400 and why in json.loads(body)["error"], target
    status, body, _ = call(demo_server, "/api/ui/teach", {"target": "gnome-robots", "goal": "x" * 1600}, cookie=cookie)
    assert "1,500 characters" in json.loads(body)["error"]
    assert call(demo_server, "/api/logout", {}, cookie=cookie)[0] == 200
    assert call(demo_server, "/api/team", cookie=cookie)[0] == 401
    server.DEMO_FAILS.clear()


def test_guessing_the_password_is_slowed_then_stopped(demo_server):
    for _ in range(8):
        call(demo_server, "/api/login", {"user": "judge", "password": "guess"})
    assert call(demo_server, "/api/login", {"user": "judge", "password": "amber-basil-cedar-0001"})[0] == 429


def test_setup_copies_only_vetted_interfaces_and_their_logins(tmp_path, monkeypatch):
    own = tmp_path / "own"
    (own / "uiteam" / "orders").mkdir(parents=True)
    (own / "uiteam" / "orders" / "plan.json").write_text("{}")
    for name, manifest in {"robots": {"status": "ready", "tool_id": "robots"}, "draft": {"status": "failed", "tool_id": "draft"}}.items():
        (own / "library" / name / "teach" / "frames").mkdir(parents=True)
        (own / "library" / name / "manifest.json").write_text(json.dumps(manifest))
        (own / "library" / name / "teach" / "frames" / "00001.png").write_bytes(b"x")
    (own / "logins.json").write_text(json.dumps({"orders": {"username": "manager"}, "my-bank": {"password": "real"}, "vnc://127.0.0.1:5912": {"password": "p"}}))
    monkeypatch.setattr(config, "HOME", own)
    monkeypatch.setattr(demo, "HOME", tmp_path / "demo")
    assert demo.copy_interfaces() == ["orders", "robots"]
    assert not (tmp_path / "demo" / "library" / "draft").exists()
    assert not (tmp_path / "demo" / "library" / "robots" / "teach" / "frames").exists()  # screenshots from teaching stay home
    kept = json.loads((tmp_path / "demo" / "logins.json").read_text())
    assert set(kept) == {"orders", "vnc://127.0.0.1:5912"}  # never a login for anything else
    assert (tmp_path / "demo" / "logins.json").stat().st_mode & 0o777 == 0o600
    p = demo.new_password()
    assert len(p.split("-")) == 4 and p.split("-")[-1].isdigit()
