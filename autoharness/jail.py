"""Runs one program locked in, for the public demo: it can read only the folders named, write only the ones named, and
open TCP connections only to the ports named. No root needed: Landlock, from the kernel.

    python jail.py --read /usr:/etc --write /tmp/profile --tcp 41234 -- chromium --app=https://example.com

The demo's browser runs this way, with the egress proxy as its only port, so it can't read this computer's files or reach
anything on its network. If the kernel can't do it, the program doesn't run at all.
"""
from __future__ import annotations

import ctypes
import os
import platform
import sys

CREATE, ADD_RULE, RESTRICT = 444, 445, 446  # the same numbers on x86_64 and aarch64
RULE_PATH, RULE_PORT = 1, 2
EXECUTE, WRITE_FILE, READ_FILE, READ_DIR = 1, 2, 4, 8
REMOVE_DIR, REMOVE_FILE, MAKE_CHAR, MAKE_DIR, MAKE_REG, MAKE_SOCK, MAKE_FIFO, MAKE_BLOCK, MAKE_SYM = 16, 32, 64, 128, 256, 512, 1024, 2048, 4096
REFER, TRUNCATE = 8192, 16384
BIND_TCP, CONNECT_TCP = 1, 2
SCOPE_SIGNAL = 2


class _Ruleset(ctypes.Structure):
    _fields_ = [("fs", ctypes.c_uint64), ("net", ctypes.c_uint64), ("scoped", ctypes.c_uint64)]


class _PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed", ctypes.c_uint64), ("fd", ctypes.c_int32)]


class _PortRule(ctypes.Structure):
    _fields_ = [("allowed", ctypes.c_uint64), ("port", ctypes.c_uint64)]


def confine(read: list[str], write: list[str], tcp_ports: list[int]) -> str | None:
    """Locks this process and everything it starts. Returns None on success, or why it couldn't."""
    if platform.machine() not in ("x86_64", "aarch64"):
        return "only x86_64 and aarch64 are supported"
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(CREATE, None, 0, 1)
    if abi < 4:
        return f"the kernel's Landlock is too old or off (version {abi}); version 4 or later is needed to limit the network"
    reading = EXECUTE | READ_FILE | READ_DIR
    writing = WRITE_FILE | REMOVE_DIR | REMOVE_FILE | MAKE_DIR | MAKE_REG | MAKE_SOCK | MAKE_FIFO | MAKE_SYM | TRUNCATE
    handled_fs = reading | writing | MAKE_CHAR | MAKE_BLOCK | REFER
    attr = _Ruleset(handled_fs, BIND_TCP | CONNECT_TCP, SCOPE_SIGNAL if abi >= 6 else 0)
    size = ctypes.sizeof(_Ruleset) if abi >= 6 else 16
    ruleset = libc.syscall(CREATE, ctypes.byref(attr), size, 0)
    if ruleset < 0:
        return f"Landlock refused the rules ({os.strerror(ctypes.get_errno())})"
    for paths, access in ((read, reading), (write, reading | writing | REFER)):
        for path in paths:
            if not path or not os.path.exists(path):
                continue
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            allowed = access if os.path.isdir(path) else access & (EXECUTE | WRITE_FILE | READ_FILE | TRUNCATE)
            rule = _PathRule(allowed & handled_fs, fd)
            if libc.syscall(ADD_RULE, ruleset, RULE_PATH, ctypes.byref(rule), 0) != 0:
                os.close(fd)
                return f"couldn't allow {path} ({os.strerror(ctypes.get_errno())})"
            os.close(fd)
    for port in tcp_ports:
        rule = _PortRule(CONNECT_TCP, int(port))
        if libc.syscall(ADD_RULE, ruleset, RULE_PORT, ctypes.byref(rule), 0) != 0:
            return f"couldn't allow port {port} ({os.strerror(ctypes.get_errno())})"
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # no new privileges, which Landlock needs
        return "couldn't set no-new-privileges"
    if libc.syscall(RESTRICT, ruleset, 0) != 0:
        return f"Landlock couldn't restrict this process ({os.strerror(ctypes.get_errno())})"
    os.close(ruleset)
    return None


def command(read: list[str], write: list[str], tcp_ports: list[int], cmd: list[str]) -> list[str]:
    """The command line that runs cmd inside the jail."""
    return [sys.executable, os.path.abspath(__file__), "--read", ":".join(read), "--write", ":".join(write),
            "--tcp", ",".join(str(p) for p in tcp_ports), "--", *cmd]


def main(argv: list[str]) -> None:
    if "--" not in argv:
        sys.exit("usage: jail.py --read A:B --write C --tcp PORT -- command ...")
    split = argv.index("--")
    opts, cmd = argv[:split], argv[split + 1:]
    value = {k: opts[i + 1] for i, k in enumerate(opts) if k.startswith("--") and i + 1 < len(opts)}
    read = [p for p in value.get("--read", "").split(":") if p]
    write = [p for p in value.get("--write", "").split(":") if p]
    ports = [int(p) for p in value.get("--tcp", "").split(",") if p.strip()]
    why = confine(read, write, ports)
    if why:
        sys.exit(f"Not started, because it can't be locked in: {why}")
    os.execvpe(cmd[0], cmd, os.environ)


if __name__ == "__main__":
    main(sys.argv[1:])
