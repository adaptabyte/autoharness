"""Paths, prices and credentials. Nothing here ever logs a secret."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

HOME = Path(os.environ.get("AUTOHARNESS_HOME", Path.home() / ".autoharness")).expanduser()
LIBRARY = HOME / "library"
RUNS = HOME / "runs"
LEDGER = HOME / "ledger.json"
REPO = Path(__file__).resolve().parent.parent
SYS_ROOT = Path(os.environ.get("AUTOHARNESS_SYS", Path.home() / ".local/autoharness-sys/root")).expanduser()

API_BASE = os.environ.get("MODEL_API_BASE", "https://api.meta.ai/v1")
TEACHER_MODEL = os.environ.get("AUTOHARNESS_TEACHER", "muse-spark-1.3")
SAM_MODEL = "sam-3.1"
GLIMMER_URL = os.environ.get("GLIMMER_URL", "http://127.0.0.1:8001/v1")
GLIMMER_MODEL = os.environ.get("GLIMMER_MODEL", "muse-glimmer")

# Hard stop for all Meta API spend made through this install, in dollars.
BUDGET_USD = float(os.environ.get("AUTOHARNESS_BUDGET", "25"))


@dataclass(frozen=True)
class Price:
    input: float
    cached: float
    output: float


# Dollars per million tokens, from dev.meta.ai/docs/pricing-rate-limits (2026-10-31).
PRICES = {
    "muse-spark-1.3": Price(1.25, 0.15, 4.25),
    "muse-wonder-1.0": Price(4.00, 0.20, 20.00),
}
SAM_PER_IMAGE = 2.50 / 1000


def api_key() -> str | None:
    """MODEL_API_KEY, then ./.env, then the key Muse Code stored. Returns None if there is none."""
    key = os.environ.get("MODEL_API_KEY")
    if key:
        return key.strip()
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("MODEL_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    auth = Path.home() / ".config/muse/auth.json"
    if auth.exists():
        try:
            return json.loads(auth.read_text())["providers"]["meta"]["api_key"]
        except (KeyError, ValueError, TypeError):
            return None
    return None


def ensure_dirs() -> None:
    for d in (HOME, LIBRARY, RUNS):
        d.mkdir(parents=True, exist_ok=True)
