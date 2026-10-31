"""The only module that talks to the Meta Model API.

Every call is priced and written to a persistent ledger before the result is used, and every call
is refused once the budget is gone or the caller is in local-only mode. So "this run sent nothing to
the cloud" is a fact the code can report, not a promise.
"""
from __future__ import annotations

import base64
import fcntl
import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import numpy as np
from PIL import Image

from . import config


class CloudError(RuntimeError):
    pass


class BudgetExceeded(CloudError):
    pass


class CloudBlocked(CloudError):
    """Raised when something tries to use the cloud during a local-only run."""


_lock = threading.Lock()


class Ledger:
    """All-time Meta API spend, kept on disk so the budget survives restarts."""

    @staticmethod
    def read() -> dict:
        try:
            return json.loads(config.LEDGER.read_text())
        except (OSError, ValueError):
            return {"spent_usd": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "bytes_sent": 0}

    @staticmethod
    def add(usd: float, tokens_in: int, tokens_out: int, bytes_sent: int) -> dict:
        with _lock:
            config.ensure_dirs()
            # A file lock as well: separate processes can be spending at once, and none may lose the others' records.
            lock_file = open(config.LEDGER.with_suffix(".lock"), "w")
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            d = Ledger.read()
            d["spent_usd"] = round(d["spent_usd"] + usd, 6)
            d["calls"] += 1
            d["input_tokens"] += tokens_in
            d["output_tokens"] += tokens_out
            d["bytes_sent"] += bytes_sent
            tmp = config.LEDGER.with_suffix(".tmp")
            tmp.write_text(json.dumps(d))
            tmp.replace(config.LEDGER)
            lock_file.close()
            return d

    @staticmethod
    def remaining() -> float:
        return config.BUDGET_USD - Ledger.read()["spent_usd"]


@dataclass
class Meter:
    """Spend attributed to one job (a teaching session, a baseline run, a repair)."""

    usd: float = 0.0
    calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    bytes_sent: int = 0
    seconds: float = 0.0

    def snapshot(self) -> dict:
        return dict(usd=round(self.usd, 5), calls=self.calls, input_tokens=self.input_tokens,
                    cached_tokens=self.cached_tokens, output_tokens=self.output_tokens,
                    bytes_sent=self.bytes_sent, seconds=round(self.seconds, 1))


def image_url(frame: np.ndarray, quality: int = 88) -> str:
    """A frame as a data URL. JPEG keeps screenshots small without hurting UI text at this quality."""
    buf = io.BytesIO()
    Image.fromarray(frame).save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class Cloud:
    def __init__(self, meter: Meter | None = None, limit_usd: float | None = None, allowed: bool = True):
        self.meter = meter or Meter()
        self.limit_usd = limit_usd
        self.allowed = allowed

    def _post(self, path: str, body: dict, timeout: float = 300) -> dict:
        if not self.allowed:
            raise CloudBlocked("cloud use is switched off for this run")
        if Ledger.remaining() <= 0:
            raise BudgetExceeded(f"the ${config.BUDGET_USD:.2f} Meta API budget is used up")
        if self.limit_usd is not None and self.meter.usd >= self.limit_usd:
            raise BudgetExceeded(f"this job reached its ${self.limit_usd:.2f} limit")
        key = config.api_key()
        if not key:
            raise CloudError("no Meta API key: set MODEL_API_KEY or put it in .env")
        data = json.dumps(body).encode()
        delay = 2.0
        for attempt in range(5):
            req = urllib.request.Request(
                config.API_BASE + path, data=data,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    out = json.load(resp)
                self.meter.seconds += time.time() - t0
                self.meter.bytes_sent += len(data)
                return out
            except urllib.error.HTTPError as e:
                detail = e.read()[:500].decode("utf8", "replace")
                if e.code in (408, 409, 429) or e.code >= 500:
                    if attempt == 4:
                        raise CloudError(f"Meta API HTTP {e.code}: {detail}") from e
                else:
                    raise CloudError(f"Meta API HTTP {e.code}: {detail}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                if attempt == 4:
                    raise CloudError(f"cannot reach the Meta API: {e}") from e
            time.sleep(delay)
            delay *= 2
        raise CloudError("unreachable")

    def respond(self, **body) -> dict:
        """POST /responses, charging the ledger and this job's meter from the reported usage."""
        data_len_before = self.meter.bytes_sent
        out = self._post("/responses", body)
        if out.get("error"):
            raise CloudError(str(out["error"])[:500])
        model = body.get("model", config.TEACHER_MODEL)
        u = out.get("usage") or {}
        tin, tout = int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))
        cached = int((u.get("input_tokens_details") or {}).get("cached_tokens", 0))
        p = config.PRICES.get(model) or config.PRICES[config.TEACHER_MODEL]
        usd = ((tin - cached) * p.input + cached * p.cached + tout * p.output) / 1e6
        self.meter.usd += usd
        self.meter.calls += 1
        self.meter.input_tokens += tin
        self.meter.cached_tokens += cached
        self.meter.output_tokens += tout
        Ledger.add(usd, tin, tout, self.meter.bytes_sent - data_len_before)
        return out

    def segment(self, frame: np.ndarray, phrase: str) -> list[dict]:
        """SAM 3.1: every instance of a noun phrase, as pixel boxes."""
        before = self.meter.bytes_sent
        out = self._post("/responses", dict(
            model=config.SAM_MODEL,
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": phrase},
                {"type": "input_image", "image_url": image_url(frame, 92)}]}]))
        self.meter.usd += config.SAM_PER_IMAGE
        self.meter.calls += 1
        Ledger.add(config.SAM_PER_IMAGE, 0, 0, self.meter.bytes_sent - before)
        return parse_sam(response_text(out))


_BOX = re.compile(r"<\|box;x1=(-?[\d.]+);y1=(-?[\d.]+);x2=(-?[\d.]+);y2=(-?[\d.]+);w=(\d+);h=(\d+)\|>")


def parse_sam(text: str) -> list[dict]:
    """SAM's reply is one text blob of <|box;...|><|mask;...|> tokens. Only the boxes are needed."""
    return [{"x1": round(float(a)), "y1": round(float(b)), "x2": round(float(c)), "y2": round(float(d))}
            for a, b, c, d, _w, _h in _BOX.findall(text)]


def response_text(resp: dict) -> str:
    parts = []
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text"):
                    parts.append(c.get("text", ""))
    return "\n".join(parts).strip()
