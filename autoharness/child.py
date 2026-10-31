"""Entry point of the sandboxed process. Locks itself down, then imports and runs the harness."""
from __future__ import annotations

import ctypes
import faulthandler
import json
import os
import platform
import resource
import signal
import struct
import sys
import traceback
from pathlib import Path


def lock_files(read_only: list[str], writable: list[str]) -> bool:
    """Landlock: from here on, this process can only touch the listed folders. Needs no root."""
    libc = ctypes.CDLL(None, use_errno=True)
    arch = platform.machine()
    if arch not in ("x86_64", "aarch64"):
        return False
    create, add_rule, restrict = 444, 445, 446  # same numbers on both architectures
    abi = libc.syscall(create, None, 0, 1)  # LANDLOCK_CREATE_RULESET_VERSION
    if abi < 1:
        return False
    read = 1 | 4 | 8  # execute, read file, read dir
    write = 2 | 16 | 32 | 128 | 256 | 512 | 1024 | 4096  # write, remove, make dir/file/sock/fifo/symlink
    handled = read | write | 64 | 2048
    if abi >= 2:
        handled |= 8192  # refer
    if abi >= 3:
        handled |= 16384  # truncate
        write |= 16384

    class Attr(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64)]

    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    attr = Attr(handled, 0)
    size = ctypes.sizeof(Attr) if abi >= 4 else 8
    ruleset = libc.syscall(create, ctypes.byref(attr), size, 0)
    if ruleset < 0:
        return False
    for paths, access in ((read_only, read), (writable, read | write)):
        for path in paths:
            if not os.path.exists(path):
                continue
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            allowed = access if os.path.isdir(path) else access & (1 | 2 | 4 | 16384)
            rule = Rule(allowed & handled, fd)
            libc.syscall(add_rule, ruleset, 1, ctypes.byref(rule), 0)
            os.close(fd)
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        return False
    ok = libc.syscall(restrict, ruleset, 0) == 0
    os.close(ruleset)
    return ok


def lock_down() -> bool:
    """Kernel-enforced: this process and its threads can never open a socket, start a program or signal one."""
    resource.setrlimit(resource.RLIMIT_AS, (8 << 30, 8 << 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 << 20, 512 << 20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    arch = platform.machine()
    tables = {
        "x86_64": (0xC000003E, [41, 42, 43, 44, 45, 46, 47, 49, 50, 53, 59, 62, 101, 165, 288, 299, 307, 310, 311, 322, 424, 434]),
        "aarch64": (0xC00000B7, [198, 199, 200, 201, 202, 203, 204, 206, 207, 208, 209, 211, 212, 221, 242, 243,
                                 270, 271, 281, 129, 424, 434]),
    }
    if arch not in tables:
        return False
    audit, denied = tables[arch]
    errno_eperm = 0x00050000 | 1
    allow = 0x7FFF0000
    n = len(denied)
    code = [(0x20, 0, 0, 4), (0x15, 1, 0, audit), (0x06, 0, 0, errno_eperm), (0x20, 0, 0, 0)]
    for i, nr in enumerate(denied):
        code.append((0x15, n - i, 0, nr))
    code += [(0x06, 0, 0, allow), (0x06, 0, 0, errno_eperm)]
    blob = b"".join(struct.pack("HBBI", *c) for c in code)
    buf = ctypes.create_string_buffer(blob)

    class Prog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]

    prog = Prog(len(code), ctypes.addressof(buf))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        return False
    return libc.prctl(22, 2, ctypes.byref(prog), 0, 0) == 0


class _LogWriter:
    def __init__(self, app):
        self.app, self.buf = app, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.app.log(line)
        return len(s)

    def flush(self):
        pass


def main() -> None:
    # If the runtime sees no activity it sends SIGUSR1, and this writes where every thread is to stderr.
    faulthandler.register(signal.SIGUSR1, file=sys.__stderr__, all_threads=True)
    work, code_dir = Path(sys.argv[1]), Path(sys.argv[2])
    rpc_out = os.fdopen(os.dup(1), "w", buffering=1)
    rpc_in = os.fdopen(os.dup(0), "r", buffering=1)
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(2, 1)
    init = json.loads(rpc_in.readline())

    # numpy and OpenCV load before the lockdown: they may probe the system while starting up.
    import numpy  # noqa: F401
    import cv2  # noqa: F401
    cv2.setNumThreads(2)
    import sdk

    prefixes = {sys.prefix, sys.base_prefix, os.path.realpath(sys.executable).rsplit("/bin/", 1)[0]}
    code_files = [str(Path(__file__).resolve().parent)]
    files_locked = lock_files(["/usr", "/lib", "/lib64", "/etc/ld.so.cache", *prefixes, *code_files, str(code_dir)],
                              [str(work)])
    locked = lock_down() and files_locked
    app = sdk.App(rpc_in, rpc_out, work, code_dir / "assets", init)
    rpc_out.write(json.dumps({"m": "ready", "locked": locked}) + "\n")
    rpc_out.flush()
    sys.stdout = _LogWriter(app)
    sys.path.insert(0, str(code_dir))
    sys.modules.setdefault("autoharness_sdk", sdk)

    def end(status: str, **kw) -> None:
        rpc_out.write(json.dumps({"m": "end", "status": status, "state": app.state, **kw}, default=str) + "\n")
        rpc_out.flush()

    try:
        if init.get("snippet") is not None:
            # A teaching experiment: a bit of code run against a recorded frame, not the live app.
            env = {"app": app, "frame": None, "np": numpy, "cv2": cv2}
            if init.get("frame_shape"):
                h, w = init["frame_shape"]
                env["frame"] = numpy.fromfile(work / "frame.bin", dtype=numpy.uint8, count=w * h * 3).reshape(h, w, 3)
            exec(compile(init["snippet"], "<experiment>", "exec"), env)
            end("returned")
            return
        import harness
        mode = init.get("mode", "run")
        if mode == "describe":
            state_doc = (harness.observe.__doc__ or "").strip() if hasattr(harness, "observe") else None
            end("returned", value={"observe": hasattr(harness, "observe"), "observe_doc": state_doc,
                                   "has_run": hasattr(harness, "run"),
                                   "verbs": [sdk.describe_verb(f) for f in sdk.VERBS.values()]})
            return
        if mode == "observe":
            end("returned", value=harness.observe(app))
            return
        if mode == "call":
            fn = sdk.VERBS.get(init["verb"])
            if fn is None:
                raise sdk.Stuck(f"no such verb: {init['verb']}")
            end("returned", value=fn(app, **(init.get("args") or {})))
            return
        harness.run(app)
        end("returned", reason="run(app) returned without calling app.done()")
    except sdk.Done:
        pass
    except sdk.Stuck as e:
        end("stuck", reason=str(e)[:1000], traceback=traceback.format_exc(limit=6)[-2500:])
    except SystemExit:
        pass
    except BaseException as e:  # noqa: BLE001 - everything a harness does wrong is reported, not fatal
        end("exception", reason=f"{type(e).__name__}: {e}"[:1000], traceback=traceback.format_exc(limit=8)[-3000:])


if __name__ == "__main__":
    main()
