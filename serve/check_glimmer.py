"""Health-check a running Glimmer server: lists models, runs one chat call."""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001/v1"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def chat(prompt):
    body = json.dumps({"model": "muse-glimmer",
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 32}).encode()
    req = urllib.request.Request(BASE + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer EMPTY"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


if __name__ == "__main__":
    print("models:", [m["id"] for m in get("/models")["data"]])
    print("reply:", chat("Reply with exactly: GLIMMER_OK"))
