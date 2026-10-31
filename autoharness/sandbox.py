"""Starts the process that runs generated code. It cannot reach the network, the user's files, the API
key or the display. It can only talk to its parent over a pipe."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def spawn(package_dir: Path, work: Path) -> subprocess.Popen:
    """Launch the harness child for package_dir, with `work` as its only writable folder.

    The child runs with an empty environment, so it never holds the API key, and locks itself down with
    Landlock and seccomp before any generated code is imported (see child.py). It reports whether the
    lockdown succeeded, and the runtime refuses to continue if it did not.
    """
    work.mkdir(parents=True, exist_ok=True)
    site = [p for p in sys.path if p.endswith("site-packages")]
    env = {"PYTHONUNBUFFERED": "1", "OPENBLAS_NUM_THREADS": "2", "OMP_NUM_THREADS": "2", "HOME": "/nonexistent",
           "PATH": "/usr/bin", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": ":".join([str(HERE), *site])}
    return subprocess.Popen([sys.executable, str(HERE / "child.py"), str(work), str(package_dir)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(work),
                            text=True, bufsize=1, start_new_session=True)
