"""WebUI: full auto-harness run over HTTP with mock tiers, incl. live frame."""
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

from webui.server import Handler


def _req(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read()


def test_webui_demo_job_end_to_end():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        status, body = _req(base, "/")
        assert status == 200 and b"AUTO" in body

        cfg = {"smart": {"mock": True}, "fast": {"base_url": "", "model": "m"},
               "game_name": "webui-test", "target": "demo",
               "manual_text": "Goal: reach the green square.",
               "steps": 4000, "seconds": 2, "kb_path": ""}
        _, body = _req(base, "/api/jobs/demo", cfg)
        job_id = json.loads(body)["job_id"]

        deadline = time.time() + 120
        view = {}
        while time.time() < deadline:
            _, body = _req(base, f"/api/jobs/{job_id}")
            view = json.loads(body)
            if view["phase"] in ("played", "error"):
                break
            time.sleep(0.5)
        assert view["phase"] == "played", view.get("error")
        assert view["result"]["decisions"] > 0

        status, png = _req(base, f"/api/jobs/{job_id}/frame.png")
        assert status == 200 and png[:4] == b"\x89PNG"

        _, body = _req(base, "/api/kbs")
        assert "webui-test.json" in json.loads(body)["kbs"]
    finally:
        srv.shutdown()


def test_frame_url_with_cache_buster():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        cfg = {"smart": {"mock": True}, "fast": {"base_url": "", "model": "m"},
               "game_name": "webui-frame", "target": "demo",
               "manual_text": "", "steps": 50, "seconds": 1, "kb_path": ""}
        _, body = _req(base, "/api/jobs/explore", cfg)
        job_id = json.loads(body)["job_id"]
        deadline = time.time() + 60
        png = b""
        import urllib.error
        while time.time() < deadline:
            try:
                status, png = _req(base, f"/api/jobs/{job_id}/frame.png?t=12345")
            except urllib.error.HTTPError:
                time.sleep(0.3); continue
            if status == 200 and png[:4] == b"\x89PNG":
                break
            time.sleep(0.3)
        assert png[:4] == b"\x89PNG", "frame.png?t= must return a PNG, not JSON"
    finally:
        srv.shutdown()
