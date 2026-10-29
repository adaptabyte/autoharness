"""Pluggable LLM backends.

Both tiers speak the same interface: the explorer tier (a high-intelligence
multimodal model such as Muse Wonder) and the runtime tier (a fast small
model such as locally served Muse Glimmer) differ only in endpoint/model.
Any OpenAI-compatible server works, including the vLLM server in serve/.
`MockLLM` keeps the whole pipeline testable with no model at all.
"""
from __future__ import annotations

import json
import urllib.request


class MockLLM:
    """Deterministic stand-in: echoes a canned JSON plan. For tests/demos."""

    def __init__(self, reply: str = '{"actions": [], "notes": "mock"}'):
        self.reply = reply
        self.calls = 0

    def complete(self, prompt: str, image_desc: str = "") -> str:
        self.calls += 1
        return self.reply


class OpenAICompatLLM:
    """Calls any OpenAI-compatible /chat/completions endpoint (e.g. vLLM)."""

    def __init__(self, base_url: str, model: str, api_key: str = "EMPTY",
                 timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, prompt: str, image_desc: str = "") -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user",
                          "content": prompt + ("\n" + image_desc if image_desc else "")}],
            "temperature": 0.2,
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
