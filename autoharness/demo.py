"""The live demo for judges: a second, locked-down Autoharness on this machine, reached through a Cloudflare Tunnel.

    autoharness demo setup     # its own home, the interfaces you've vetted, a judge login, its own API key
    autoharness demo tunnel    # once, after `cloudflared tunnel login`: the public address
    autoharness demo up        # start it, and the tunnel
    autoharness demo status    # what it has spent, and whether it's answering
    autoharness demo down

It shares Muse Glimmer and the made-up demo apps with your own Autoharness, and nothing else: it has its own folder, its
own budget, its own API key, and a login on every request. Its browser and apps run jailed (jail.py), and their only way
out is a proxy that refuses private addresses (egress.py).
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

HOME = Path(os.environ.get("AUTOHARNESS_DEMO_HOME", Path.home() / ".autoharness-demo")).expanduser()
SETTINGS = HOME / "demo_settings.json"
DEFAULTS = {"port": 4141, "budget_usd": 25.0, "lesson_usd": 1.5, "hostname": "demo.adaptabyte.com", "user": "judge", "tunnel": "autoharness-demo"}
WORDS = ("amber", "basil", "cedar", "delta", "ember", "fjord", "garnet", "harbor", "indigo", "juniper", "kelp", "lumen", "maple", "nectar",
         "orbit", "pebble", "quartz", "rivet", "saffron", "tundra", "umber", "velvet", "willow", "zephyr")


def settings() -> dict:
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def _save(d: dict) -> None:
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(d, indent=1))


def _private_write(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(path, 0o600)


def new_password() -> str:
    """Easy to read out and type, hard to guess: three words and four digits."""
    return "-".join(secrets.choice(WORDS) for _ in range(3)) + f"-{secrets.randbelow(10000):04d}"


def set_login(user: str, password: str) -> None:
    """Only a salted hash is kept (the same scheme the server checks), so the password can be replaced, never read back."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_write(HOME / "demo.json", json.dumps({"user": user, "salt": salt.hex(), "hash": digest.hex()}))


def copy_interfaces() -> list[str]:
    """What you've taught and vetted, so judges can run it straight away. The demo works on copies: nothing a judge
    teaches or changes reaches your own library."""
    src = config.HOME
    copied = []
    for plan in sorted((src / "uiteam").glob("*/plan.json")):
        dest = HOME / "uiteam" / plan.parent.name
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan, dest / "plan.json")
        copied.append(plan.parent.name)
    for manifest in sorted((src / "library").glob("*/manifest.json")):
        m = json.loads(manifest.read_text())
        if m.get("status") != "ready" or not m.get("tool_id"):
            continue
        dest = HOME / "library" / manifest.parent.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(manifest.parent, dest, ignore=shutil.ignore_patterns("frames", "refused.jsonl"))
        copied.append(m["tool_id"])
    if (src / "guides").exists():
        shutil.copytree(src / "guides", HOME / "guides", dirs_exist_ok=True, ignore=shutil.ignore_patterns("share.json"))
    # Logins only for what was copied: the made-up demo apps' and the stand-in game screen's.
    try:
        kept = json.loads((src / "logins.json").read_text())
    except (OSError, ValueError):
        kept = {}
    wanted = {k: v for k, v in kept.items() if k in copied or k.startswith("vnc://127.0.0.1:")}
    _private_write(HOME / "logins.json", json.dumps(wanted, indent=1))
    return copied


def setup(ask_key: bool = True) -> int:
    s = settings()
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    _save(s)
    copied = copy_interfaces()
    print(f"The demo lives in {HOME}, apart from your own Autoharness.")
    print(f"  Copied for judges to run: {', '.join(copied) or 'nothing yet'}")
    if not (HOME / "demo.json").exists():
        password = new_password()
        set_login(s["user"], password)
        print(f"  Judges sign in as {s['user']} with password {password}")
        print("  Put both in the submission's private notes for judges only. Only a hash is kept here, so note it now.")
    else:
        print("  The judge login is already set. A new password: autoharness demo password")
    if ask_key:
        key_prompt()
    print(f"  Budget for new lessons: ${s['budget_usd']:.2f}, at most ${s['lesson_usd']:.2f} each. Running what's learned is free.")
    print("\nNext, once: cloudflared tunnel login   (it opens Cloudflare in your browser: pick adaptabyte.com)")
    print("Then: autoharness demo tunnel && autoharness demo up")
    return 0


def key_prompt() -> None:
    have = (HOME / "api_key").exists()
    try:
        key = getpass.getpass(f"  Paste the demo's own Meta API key ({'Enter keeps the one set' if have else 'it stays hidden; Enter skips'}): ").strip()
    except (EOFError, KeyboardInterrupt):
        key = ""
    if key:
        old_home, config.HOME = config.HOME, HOME
        try:
            config.save_api_key(key)
        finally:
            config.HOME = old_home
        print("  Saved, readable by you only. It's never shown again, and the demo's jailed apps can't read it.")
    elif not have:
        print("  No key yet, so judges can run what's learned but can't teach. Add one later: autoharness demo key")


def password() -> int:
    p = new_password()
    set_login(settings()["user"], p)
    print(f"Judges now sign in as {settings()['user']} with password {p}. Anyone signed in with the old one stays signed in "
          "until the demo restarts: run autoharness demo down && autoharness demo up")
    return 0


def _cloudflared() -> str | None:
    return shutil.which("cloudflared") or (str(Path.home() / ".local/bin/cloudflared") if (Path.home() / ".local/bin/cloudflared").exists() else None)


def tunnel() -> int:
    """The public address, once: a named Cloudflare Tunnel and its DNS record. Needs `cloudflared tunnel login` first."""
    exe = _cloudflared()
    s = settings()
    if not exe:
        print("cloudflared isn't installed. Get it: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
        return 1
    if not (Path.home() / ".cloudflared/cert.pem").exists():
        print(f"First sign in to Cloudflare, once: {exe} tunnel login   (pick adaptabyte.com in the page it opens)")
        return 1
    info = subprocess.run([exe, "tunnel", "info", "--output", "json", s["tunnel"]], capture_output=True, text=True)
    if info.returncode != 0:
        made = subprocess.run([exe, "tunnel", "create", s["tunnel"]], capture_output=True, text=True)
        if made.returncode != 0:
            print(made.stderr.strip()[-400:])
            return 1
        info = subprocess.run([exe, "tunnel", "info", "--output", "json", s["tunnel"]], capture_output=True, text=True)
    tunnel_id = json.loads(info.stdout or "{}").get("id")
    if not tunnel_id:
        print("Couldn't read the tunnel's id:", info.stderr.strip()[-300:])
        return 1
    route = subprocess.run([exe, "tunnel", "route", "dns", "--overwrite-dns", s["tunnel"], s["hostname"]], capture_output=True, text=True)
    if route.returncode != 0:
        print(route.stderr.strip()[-400:])
        return 1
    creds = Path.home() / ".cloudflared" / f"{tunnel_id}.json"
    (HOME / "cloudflared.yml").write_text(
        f"tunnel: {tunnel_id}\ncredentials-file: {creds}\nno-autoupdate: true\ningress:\n"
        f"  - hostname: {s['hostname']}\n    service: http://127.0.0.1:{s['port']}\n  - service: http_status:404\n")
    s["tunnel_id"] = tunnel_id
    _save(s)
    print(f"https://{s['hostname']} now leads to this machine's demo, port {s['port']}, through the tunnel. Start it: autoharness demo up")
    return 0


def _pids() -> dict:
    try:
        return json.loads((HOME / "up.json").read_text())
    except (OSError, ValueError):
        return {}


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _answering(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True  # it asks for a login, so it's up
    except (urllib.error.URLError, OSError):
        return False


def up() -> int:
    s = settings()
    if not (HOME / "demo.json").exists():
        print("Set it up first: autoharness demo setup")
        return 1
    pids = _pids()
    logs = HOME / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    if not _alive(pids.get("app")):
        env = {k: v for k, v in os.environ.items() if k not in ("MODEL_API_KEY", "AUTOHARNESS_BUDGET")}
        env.update(AUTOHARNESS_DEMO="1", AUTOHARNESS_HOME=str(HOME), AUTOHARNESS_BUDGET=str(s["budget_usd"]),
                   AUTOHARNESS_DEMO_LESSON_USD=str(s["lesson_usd"]))
        proc = subprocess.Popen([sys.executable, "-m", "autoharness", "serve", "--port", str(s["port"])], env=env, cwd=str(config.REPO),
                                stdout=open(logs / "app.log", "ab"), stderr=subprocess.STDOUT, start_new_session=True)
        pids["app"] = proc.pid
        for _ in range(40):
            if _answering(s["port"]) or proc.poll() is not None:
                break
            time.sleep(0.5)
        if not _answering(s["port"]):
            print(f"The demo app didn't start: see {logs / 'app.log'}")
            return 1
    exe = _cloudflared()
    if (HOME / "cloudflared.yml").exists() and exe and not _alive(pids.get("tunnel")):
        proc = subprocess.Popen([exe, "tunnel", "--config", str(HOME / "cloudflared.yml"), "run"], stdout=open(logs / "tunnel.log", "ab"),
                                stderr=subprocess.STDOUT, start_new_session=True)
        pids["tunnel"] = proc.pid
    (HOME / "up.json").write_text(json.dumps(pids))
    where = f"https://{s['hostname']}" if (HOME / "cloudflared.yml").exists() else f"http://127.0.0.1:{s['port']} (no tunnel yet: autoharness demo tunnel)"
    print(f"The demo is up: {where}")
    return status()


def down() -> int:
    pids = _pids()
    for name in ("tunnel", "app"):
        pid = pids.get(name)
        if _alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                os.kill(pid, signal.SIGTERM)
            print(f"Stopped the demo's {name}.")
    (HOME / "up.json").unlink(missing_ok=True)
    return 0


def status() -> int:
    s = settings()
    pids = _pids()
    try:
        spent = json.loads((HOME / "ledger.json").read_text())["spent_usd"]
    except (OSError, ValueError, KeyError):
        spent = 0.0
    print(f"  app     {'answering' if _answering(s['port']) else 'not running'} on port {s['port']}")
    print(f"  tunnel  {'running' if _alive(pids.get('tunnel')) else 'not running'}: https://{s['hostname']}")
    print(f"  key     {'set' if (HOME / 'api_key').exists() else 'not set, so judges can only run what is learned'}")
    print(f"  spent   ${spent:.2f} of ${s['budget_usd']:.2f} on new lessons")
    return 0
