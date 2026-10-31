"""Local OCR, in its own locked-down process.

The OCR library's runtime (ONNX Runtime) contains Microsoft telemetry that connects out on its own, and its
off switch did not stop every connection in testing. A promise that screens stay on this machine can't rest on a
third party's setting, so this process gives up the ability to open a socket before that library is even loaded.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import child  # noqa: E402 - the same kernel lockdown generated code runs under


def main() -> None:
    work = Path(sys.argv[1])
    out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
    locked = child.lock_down()
    import numpy as np
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)  # never starve the app being read
    out.write(json.dumps({"ready": True, "locked": locked}) + "\n")
    for line in sys.stdin:
        job = json.loads(line)
        if job.get("probe"):
            import socket
            try:
                socket.socket()
                out.write(json.dumps({"socket": "ALLOWED"}) + "\n")
            except OSError:
                out.write(json.dumps({"socket": "blocked"}) + "\n")
            continue
        h, w = job["shape"]
        frame = np.fromfile(work / "frame.bin", dtype=np.uint8, count=w * h * 3).reshape(h, w, 3)
        result, _ = engine(frame[:, :, ::-1])
        rows = []
        for box, text, score in result or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            rows.append([float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)), text, float(score)])
        out.write(json.dumps({"rows": rows}) + "\n")


if __name__ == "__main__":
    main()
