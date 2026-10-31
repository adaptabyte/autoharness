"""Muse Glimmer on this machine, over any OpenAI-compatible local server (vLLM, llama.cpp, Ollama)."""
from __future__ import annotations

import base64
import io
import json
import re
import time
import urllib.error
import urllib.request

import numpy as np
from PIL import Image

from . import config


class LocalModelError(RuntimeError):
    pass


def _data_url(frame: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(frame).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def extract_json(text: str):
    """The first JSON value in a reply, tolerating code fences and stray words around it."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
    return json.loads(text)


class Glimmer:
    def __init__(self, url: str | None = None, model: str | None = None):
        self.url = (url or config.GLIMMER_URL).rstrip("/")
        self.model = model or config.GLIMMER_MODEL
        self.calls = 0
        self.seconds = 0.0
        self.tokens = 0
        self.last_prompt_tokens: int | None = None

    def available(self, timeout: float = 2.0) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/models", timeout=timeout) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def _chat(self, content: list, max_tokens: int, strength: str) -> str:
        body = {"model": self.model, "messages": [{"role": "user", "content": content}],
                "max_tokens": max_tokens, "temperature": 0,
                "chat_template_kwargs": {"reasoning_strength": strength}}
        req = urllib.request.Request(self.url + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                out = json.load(r)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise LocalModelError(f"Glimmer is not answering at {self.url}: {e}") from e
        self.calls += 1
        self.seconds += time.time() - t0
        self.tokens += int((out.get("usage") or {}).get("completion_tokens", 0))
        self.last_prompt_tokens = (out.get("usage") or {}).get("prompt_tokens")
        return (out["choices"][0]["message"].get("content") or "").strip()

    def ask(self, question: str, image: np.ndarray | None = None, choices: list[str] | None = None,
            schema: dict | None = None, max_tokens: int = 1500, strength: str = "low"):
        """Answer a question about an image. With choices returns one of them; with schema, parsed JSON."""
        prompt = question
        if choices:
            prompt += "\n\nReply with exactly one of these options and nothing else:\n" + "\n".join(
                f"- {c}" for c in choices)
        if schema:
            prompt += ("\n\nReply with only a JSON object matching this shape, no other text:\n"
                       + json.dumps(schema))
        content: list = [{"type": "text", "text": prompt}]
        if image is not None:
            content.insert(0, {"type": "image_url", "image_url": {"url": _data_url(image)}})
        last_error = None
        for _ in range(2):
            text = self._chat(content, max_tokens, strength)
            if schema:
                try:
                    return extract_json(text)
                except ValueError as e:
                    last_error = e
                    continue
            if choices:
                low = text.lower()
                matches = [c for c in choices if c.lower() == low.strip(" .\"'`")]
                matches = matches or [c for c in sorted(choices, key=len, reverse=True) if c.lower() in low]
                if matches:
                    return matches[0]
                last_error = ValueError(f"reply was not an option: {text[:120]}")
                continue
            if text:
                return text
            last_error = ValueError("empty reply")
            max_tokens *= 2
        raise LocalModelError(f"Glimmer gave no usable answer: {last_error}")
