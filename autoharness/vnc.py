"""A screen on another computer, over VNC: the protocol that macOS Screen Sharing, Windows VNC servers and Linux x11vnc
all speak. To the rest of Autoharness it looks exactly like the private virtual screen: screenshots in, mouse and keys out.
So anything a person can see and click on that computer, a game included, can be taught the same way.

Only the parts of the protocol a screen reader and clicker needs: Raw, CopyRect and zlib pixels, no password or a VNC
password, and pointer and key events. The connection is shared, so a person watching in their own viewer stays connected.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
import zlib
from urllib.parse import unquote, urlsplit

import numpy as np
from PIL import Image

from .desktop import Display, keysym_for

RAW, COPYRECT, ZLIB, DESKTOP_SIZE = 0, 1, 6, -223
# The longest side the rest of Autoharness sees. A bigger screen is scaled down for the models and clicks are scaled back up.
MAX_SIZE = (1280, 800)


def parse_address(text: str) -> tuple[str, int, str | None]:
    """vnc://host, vnc://host:5901, vnc://host:1 (display 1, so port 5901), vnc://:password@host."""
    parts = urlsplit(text.strip())
    if parts.scheme != "vnc" or not parts.hostname:
        raise ValueError(f"not a VNC address: {text!r}. Write it as vnc://host or vnc://host:port")
    port = parts.port or 5900
    if port < 100:
        port += 5900
    return parts.hostname, port, unquote(parts.password) if parts.password else None


def address(host: str, port: int) -> str:
    """The address without any password, which is what gets saved in a plan."""
    return f"vnc://{host}:{port}"


class VncError(RuntimeError):
    pass


def _reverse_bits(b: int) -> int:
    return int(f"{b:08b}"[::-1], 2)


def vnc_auth_response(password: str, challenge: bytes) -> bytes:
    """VNC's password check: DES over the 16-byte challenge, keyed by the password with each byte's bits reversed."""
    try:
        from Cryptodome.Cipher import DES
    except ImportError as e:
        raise VncError("this screen asks for a VNC password, which needs one more package: pip install pycryptodomex") from e
    key = bytes(_reverse_bits(b) for b in password.encode("latin-1", "replace")[:8].ljust(8, b"\0"))
    return DES.new(key, DES.MODE_ECB).encrypt(challenge)


_in_use: set[str] = set()
_in_use_lock = threading.Lock()


class VncScreen(Display):
    """A remote screen. Thread-safe like Display: a job and the live view can both use it."""

    def __init__(self, host: str, port: int = 5900, password: str | None = None, max_size: tuple[int, int] = MAX_SIZE, timeout: float = 10):
        super().__init__(0, 0)
        self.host, self.port, self.password = host, port, password
        self.max_size, self.timeout = max_size, timeout
        self.sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self._updated = threading.Condition()
        self._closed = threading.Event()
        self._reader: threading.Thread | None = None
        self._zlib = zlib.decompressobj()
        self.error: str | None = None
        self.updates = 0
        self._cache = (-1, None)
        self._buttons = 0
        self._input_at = 0.0        # when the last click or key went out
        self._looked_at = 0.0       # the last input a screenshot has already waited out
        self._update_done_at = 0.0  # when the last screen update finished arriving
        self.fb: np.ndarray | None = None
        self.server_size = (0, 0)
        self.scale = 1.0
        self.name = ""

    def describe(self) -> str:
        return address(self.host, self.port)

    # -- connection ---------------------------------------------------------------------------

    def _recv(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise VncError("the screen closed the connection")
            buf += chunk
        return bytes(buf)

    def _send(self, data: bytes) -> None:
        with self._send_lock:
            self.sock.sendall(data)

    def _reason(self) -> str:
        (n,) = struct.unpack(">I", self._recv(4))
        return self._recv(n).decode("utf8", "replace")

    def start(self) -> "VncScreen":
        where = address(self.host, self.port)
        with _in_use_lock:
            if where in _in_use:
                raise VncError(f"another job here is already using the screen at {where}. One job at a time works a real screen")
            _in_use.add(where)
        self._claimed = True
        try:
            return self._connect(where)
        except BaseException:
            self.stop()
            raise

    def _connect(self, where: str) -> "VncScreen":
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise VncError(f"can't reach a screen at {where}: {e}. Is screen sharing (VNC) turned on there, and is the port open?") from e
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)  # a quiet screen is normal; a dead link shouldn't hang forever
        try:
            self._handshake(where)
        except (OSError, struct.error) as e:
            raise VncError(f"{where} doesn't answer like a VNC screen: {e}") from e
        self.sock.settimeout(None)
        self._reader = threading.Thread(target=self._read_loop, name="vnc-reader", daemon=True)
        self._reader.start()
        self._request(incremental=False)
        with self._updated:
            if not self._updated.wait_for(lambda: self.updates > 0 or self.error, self.timeout):
                raise VncError(f"{where} connected but never sent its screen")
        if self.error:
            raise VncError(self.error)
        return self

    def _handshake(self, where: str) -> None:
        hello = self._recv(12)
        if not hello.startswith(b"RFB "):
            raise VncError(f"{where} isn't a VNC screen (it said {hello[:12]!r})")
        major, minor = int(hello[4:7]), int(hello[8:11])
        minor = 8 if (major, minor) >= (3, 8) else 7 if (major, minor) >= (3, 7) else 3
        self._send(b"RFB 003.%03d\n" % minor)
        if minor == 3:
            (kind,) = struct.unpack(">I", self._recv(4))
            if kind == 0:
                raise VncError(f"{where} refused the connection: {self._reason()}")
            offered = [kind]
        else:
            (n,) = struct.unpack(">B", self._recv(1))
            if n == 0:
                raise VncError(f"{where} refused the connection: {self._reason()}")
            offered = list(self._recv(n))
        if 1 in offered and not (self.password and 2 in offered):
            kind = 1
        elif 2 in offered:
            if not self.password:
                raise VncError(f"{where} asks for a VNC password. Put it in the address once, like vnc://:yourpassword@{self.host}:{self.port}. "
                               "It's kept on this computer, out of every plan")
            kind = 2
        else:
            hint = (" A Mac shows this when only its own sign-in is on: in Screen Sharing's settings, turn on "
                    "'VNC viewers may control screen with password'." if 30 in offered else "")
            raise VncError(f"{where} only offers sign-in methods this client doesn't speak ({offered}).{hint}")
        if minor != 3:
            self._send(bytes([kind]))
        if kind == 2:
            self._send(vnc_auth_response(self.password, self._recv(16)))
        if kind == 2 or minor == 8:
            (ok,) = struct.unpack(">I", self._recv(4))
            if ok != 0:
                why = self._reason() if minor == 8 else "the password was wrong"
                raise VncError(f"{where} refused the sign-in: {why}")
        self._send(b"\x01")  # shared: anyone already watching stays connected
        w, h = struct.unpack(">HH", self._recv(4))
        self._recv(16)
        self.name = self._reason()
        # Ask for 32-bit little-endian pixels, so each one arrives as blue, green, red, unused.
        self._send(struct.pack(">B3xBBBBHHHBBB3x", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        encodings = [ZLIB, COPYRECT, RAW, DESKTOP_SIZE]
        self._send(struct.pack(">BxH", 2, len(encodings)) + b"".join(struct.pack(">i", e) for e in encodings))
        self._resize(w, h)

    def _resize(self, w: int, h: int) -> None:
        with self._frame_lock:
            self.server_size = (w, h)
            self.fb = np.zeros((h, w, 4), dtype=np.uint8)
            self.scale = min(1.0, self.max_size[0] / w, self.max_size[1] / h)
            self.width, self.height = round(w * self.scale), round(h * self.scale)

    def _request(self, incremental: bool = True) -> None:
        w, h = self.server_size
        self._send(struct.pack(">BBHHHH", 3, int(incremental), 0, 0, w, h))

    def _read_loop(self) -> None:
        last = 0.0
        try:
            while not self._closed.is_set():
                kind = self._recv(1)[0]
                if kind == 0:
                    self._read_update()
                    with self._updated:
                        self.updates += 1
                        self._update_done_at = time.time()
                        self._updated.notify_all()
                    # Keep asking for changes, about 30 times a second at most, so the copy here stays current.
                    wait = 1 / 30 - (time.time() - last)
                    if wait > 0:
                        time.sleep(wait)
                    last = time.time()
                    self._request()
                elif kind == 1:
                    _, n = struct.unpack(">xHH", self._recv(5))
                    self._recv(6 * n)
                elif kind == 2:
                    pass  # bell
                elif kind == 3:
                    (n,) = struct.unpack(">3xI", self._recv(7))
                    self._recv(n)
                else:
                    raise VncError(f"the screen sent a message this client doesn't know ({kind})")
        except (OSError, VncError, struct.error, zlib.error) as e:
            if not self._closed.is_set():
                self.error = f"lost the screen at {self.describe()}: {e}"
        finally:
            with self._updated:
                self._updated.notify_all()

    def _read_update(self) -> None:
        (n,) = struct.unpack(">xH", self._recv(3))
        for _ in range(n):
            x, y, w, h, enc = struct.unpack(">HHHHi", self._recv(12))
            if enc == DESKTOP_SIZE:
                self._resize(w, h)
                self._request(incremental=False)
                continue
            if enc == RAW:
                pixels = self._recv(w * h * 4)
            elif enc == ZLIB:
                (size,) = struct.unpack(">I", self._recv(4))
                pixels = self._zlib.decompress(self._recv(size))
            elif enc == COPYRECT:
                sx, sy = struct.unpack(">HH", self._recv(4))
                with self._frame_lock:
                    self.fb[y:y + h, x:x + w] = self.fb[sy:sy + h, sx:sx + w].copy()
                continue
            else:
                raise VncError(f"the screen sent pixels in an encoding that wasn't asked for ({enc})")
            if len(pixels) != w * h * 4:
                raise VncError("the screen sent a rectangle of the wrong size")
            with self._frame_lock:
                self.fb[y:y + h, x:x + w] = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4)

    def stop(self) -> None:
        self._closed.set()
        if getattr(self, "_claimed", False):
            self._claimed = False
            with _in_use_lock:
                _in_use.discard(address(self.host, self.port))
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(2)

    # -- screen -------------------------------------------------------------------------------

    def _catch_up(self, first: float = 0.3, quiet: float = 0.05, most: float = 0.6) -> None:
        """A remote screen lags its input by a network trip and the server's own polling. So after a click or key, a
        screenshot first waits for an update that left the server after it, then for updates to pause. Without this a
        program acts on the screen from before its own click, and clicks again."""
        since = self._input_at
        if since <= self._looked_at:
            return
        start = time.time()
        with self._updated:
            self._updated.wait_for(lambda: self._update_done_at > since + 0.01 or self.error, first)
            while time.time() - start < most and not self.error:
                n = self.updates
                if not self._updated.wait_for(lambda: self.updates != n or self.error, quiet):
                    break
        self._looked_at = since

    def shot(self) -> np.ndarray:
        if self.error:
            raise VncError(self.error)
        self._catch_up()
        n, cached = self._cache
        if n == self.updates and cached is not None:
            return cached.copy()
        with self._frame_lock:
            n = self.updates
            rgb = self.fb[:, :, 2::-1].copy()
        if self.scale < 1.0:
            rgb = np.asarray(Image.fromarray(rgb).resize((self.width, self.height), Image.BILINEAR))
        self._cache = (n, rgb)
        return rgb.copy()

    # -- input --------------------------------------------------------------------------------

    def _at(self, x: int, y: int) -> tuple[int, int]:
        """Screenshot pixels to the screen's own pixels."""
        w, h = self.server_size
        return min(w - 1, max(0, round(x / self.scale))), min(h - 1, max(0, round(y / self.scale)))

    def _pointer(self, x: int, y: int, mask: int) -> None:
        rx, ry = self._at(x, y)
        self._send(struct.pack(">BBHH", 5, mask, rx, ry))
        self.pointer = (int(x), int(y))
        self._input_at = time.time()

    def _key(self, keysym: int, down: bool) -> None:
        self._send(struct.pack(">BBxxI", 4, int(down), keysym))
        self._input_at = time.time()

    def move(self, x: int, y: int) -> None:
        with self._input_lock:
            self._pointer(x, y, self._buttons)

    def click(self, x: int, y: int, button: str | int = "left", count: int = 1) -> None:
        b = {"left": 1, "wheel": 2, "middle": 2, "right": 3, "back": 8, "forward": 9}.get(button, button)
        bit = 1 << (int(b) - 1)
        self.move(x, y)
        time.sleep(0.03)
        with self._input_lock:
            for _ in range(count):
                self._pointer(x, y, bit)
                time.sleep(0.03)
                self._pointer(x, y, 0)
                time.sleep(0.03)
        self.actions += 1

    def drag(self, path: list[tuple[int, int]]) -> None:
        self.move(*path[0])
        time.sleep(0.05)
        with self._input_lock:
            self._buttons = 1
            self._pointer(*path[0], 1)
        time.sleep(0.05)
        for a, b in zip(path, path[1:]):
            for t in np.linspace(0, 1, 6)[1:]:
                self.move(int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t))
                time.sleep(0.012)
        time.sleep(0.05)
        with self._input_lock:
            self._buttons = 0
            self._pointer(*path[-1], 0)
        self.actions += 1

    def scroll(self, x: int, y: int, dx: int = 0, dy: int = 0) -> None:
        self.move(x, y)
        steps = [(5 if dy > 0 else 4, abs(dy)), (7 if dx > 0 else 6, abs(dx))]
        with self._input_lock:
            for button, n in steps:
                for _ in range(int(n)):
                    self._pointer(x, y, 1 << (button - 1))
                    self._pointer(x, y, 0)
                    time.sleep(0.01)
        self.actions += 1

    def press(self, combo: str) -> None:
        """A key or chord: 'Return', 'ctrl+a', 'ctrl+shift+t'."""
        parts = [p for p in combo.replace(" ", "+").split("+") if p] if len(combo) > 1 else [combo]
        syms = [keysym_for(p) for p in parts]
        with self._input_lock:
            for s in syms:
                self._key(s, True)
            time.sleep(0.02)
            for s in reversed(syms):
                self._key(s, False)
        self.actions += 1

    def type(self, text: str) -> None:
        with self._input_lock:
            for ch in text:
                s = keysym_for(ch)
                self._key(s, True)
                self._key(s, False)
                time.sleep(0.006)
        self.actions += 1
