"""The public demo's only way out: a small web proxy that refuses every address on a private network.

The demo's browser is jailed so that this proxy is the only thing it can connect to (see jail.py). The proxy resolves each
address itself and connects to the address it checked, so a name can't be pointed at this machine, the home network or
Tailscale after the check. The made-up demo apps on this machine are let through by port, and nothing else local is.
"""
from __future__ import annotations

import ipaddress
import select
import socket
import socketserver
import threading
import urllib.parse
import urllib.request

LOCAL = {"127.0.0.1", "localhost", "::1"}
_allowed_local: set[int] = set()
_server: socketserver.ThreadingTCPServer | None = None
_lock = threading.Lock()

REFUSED = ("<!doctype html><title>Not in the demo</title><body style=\"font:16px system-ui;margin:40px\"><h1>Not in the demo</h1>"
           "<p>The live demo only opens public websites. This address is on a private network, so it stays closed.</p>")


def public_ip(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%")[0])
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast


def addresses(host: str, port: int) -> list[str]:
    try:
        return list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    except (socket.gaierror, UnicodeError):
        return []


def public_host(host: str, port: int = 443) -> bool:
    """True only if every address the name has is on the public internet."""
    found = addresses(host, port)
    return bool(found) and all(public_ip(a) for a in found)


def allow_local(port: int) -> None:
    """A made-up demo app on this machine that the demo's browser may open."""
    _allowed_local.add(int(port))


def check(host: str, port: int) -> str:
    """The address to connect to, or PermissionError if it's private."""
    host = host.strip("[]").lower()
    if host in LOCAL and port in _allowed_local:
        return "127.0.0.1"
    found = addresses(host, port)
    if not found:
        raise PermissionError(f"{host} doesn't resolve")
    if not all(public_ip(a) for a in found):
        raise PermissionError(f"{host} is on a private network")
    return found[0]


def _pipe(a: socket.socket, b: socket.socket) -> None:
    socks = [a, b]
    try:
        while True:
            ready, _, broken = select.select(socks, [], socks, 120)
            if broken or not ready:
                return
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        conn = self.request
        conn.settimeout(30)
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(8192)
                if not chunk or len(data) > 65536:
                    return
                data += chunk
            head, rest = data.split(b"\r\n\r\n", 1)
            lines = head.decode("latin-1").split("\r\n")
            method, target, version = lines[0].split(" ", 2)
            if method.upper() == "CONNECT":
                host, _, port = target.rpartition(":")
                port_n = int(port)
                ip = check(host, port_n)
                up = socket.create_connection((ip, port_n), timeout=15)
                conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if rest:
                    up.sendall(rest)
            else:
                u = urllib.parse.urlsplit(target)
                if u.scheme != "http" or not u.hostname:
                    conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    return
                port_n = u.port or 80
                ip = check(u.hostname, port_n)
                up = socket.create_connection((ip, port_n), timeout=15)
                keep = [line for line in lines[1:] if not line.lower().startswith(("proxy-", "connection:", "keep-alive:"))]
                path = (u.path or "/") + (f"?{u.query}" if u.query else "")
                up.sendall(f"{method} {path} {version}\r\n".encode("latin-1") + "\r\n".join(keep + ["Connection: close"]).encode("latin-1")
                           + b"\r\n\r\n" + rest)
            up.settimeout(None)
            conn.settimeout(None)
            _pipe(conn, up)
            up.close()
        except PermissionError:
            body = REFUSED.encode()
            conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        except (OSError, ValueError):
            try:
                conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def start() -> int:
    """The proxy's port, starting it the first time."""
    global _server
    with _lock:
        if _server is None:
            _server = _Server(("127.0.0.1", 0), _Handler)
            threading.Thread(target=_server.serve_forever, daemon=True, name="egress").start()
        return _server.server_address[1]


def opener() -> urllib.request.OpenerDirector:
    """urllib through the proxy, for reading docs from the web in the demo."""
    port = start()
    proxy = f"http://127.0.0.1:{port}"
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
