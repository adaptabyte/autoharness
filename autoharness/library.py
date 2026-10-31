"""Harness packages on disk. A package is a plain folder, and exports as one shareable file:

    manifest.json   what it is for, how it was taught, what it cost
    harness.py      the program
    assets/         pictures it recognises things by
    versions/       every earlier harness.py, so a repair can be inspected or undone
    runs.jsonl      every run: outcome, time, which tier did the work, cloud spend
"""
from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from pathlib import Path

from . import config


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "app"


class Package:
    def __init__(self, path: Path):
        self.path = Path(path)

    @property
    def id(self) -> str:
        return self.path.name

    @property
    def manifest(self) -> dict:
        try:
            return json.loads((self.path / "manifest.json").read_text())
        except (OSError, ValueError):
            return {}

    def update(self, **fields) -> dict:
        m = self.manifest
        m.update(fields)
        tmp = self.path / "manifest.tmp"
        tmp.write_text(json.dumps(m, indent=1))
        tmp.replace(self.path / "manifest.json")
        return m

    @property
    def code(self) -> str:
        p = self.path / "harness.py"
        return p.read_text() if p.exists() else ""

    def write_code(self, code: str) -> int:
        """Save a new harness.py, keeping the previous one. Returns the new version number."""
        versions = self.path / "versions"
        versions.mkdir(exist_ok=True)
        current = self.path / "harness.py"
        n = self.manifest.get("version", 0)
        if current.exists():
            shutil.copy(current, versions / f"v{n}.py")
        current.write_text(code)
        self.update(version=n + 1)
        return n + 1

    def mark_proven(self) -> None:
        """This version passed its proof runs. Later failed changes roll back to it."""
        shutil.copy(self.path / "harness.py", self.path / "proven.py")
        self.update(proven_version=self.manifest.get("version"), proven_interface=self.manifest.get("interface"))

    def restore_proven(self) -> bool:
        proven = self.path / "proven.py"
        if not proven.exists():
            return False
        self.write_code(proven.read_text())
        self.update(interface=self.manifest.get("proven_interface"))
        return True

    @property
    def assets(self) -> Path:
        d = self.path / "assets"
        d.mkdir(exist_ok=True)
        return d

    def add_run(self, record: dict) -> None:
        with (self.path / "runs.jsonl").open("a") as f:
            f.write(json.dumps(record) + "\n")

    def runs(self) -> list[dict]:
        p = self.path / "runs.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def summary(self) -> dict:
        m = self.manifest
        runs = self.runs()
        real = [r for r in runs if r.get("kind") not in ("trial", "interface")]
        # Only runs an independent judge looked at count as proof. A run's own claim of success doesn't.
        judged = [r for r in runs if r.get("kind") == "verify"]
        ok = sum(1 for r in judged if r.get("status") == "done")
        finished = [r for r in runs if r.get("kind") in ("verify", "run") and r.get("status") == "done"]
        times = sorted(r.get("seconds", 0) for r in finished)
        code = sum(r.get("actions", 0) for r in real)
        glimmer = sum(r.get("glimmer_calls", 0) for r in real)
        repair_calls = sum(r.get("cloud_calls", 0) for r in real)
        return {
            "id": self.id, "name": m.get("name", self.id), "goal": m.get("goal", ""), "target": m.get("target", {}),
            "status": m.get("status", "new"), "teacher": m.get("teacher", "Spark"), "version": m.get("version", 0), "inputs": m.get("inputs", []),
            "teach_usd": m.get("teach_usd", 0.0), "teach_seconds": m.get("teach_seconds", 0), "created": m.get("created"),
            "repair_usd": round(sum(r.get("cloud_usd", 0) for r in real), 4), "runs": len(real), "successes": ok,
            "attempted": len(judged), "median_seconds": times[len(times) // 2] if times else None,
            "tier_code": code, "tier_glimmer": glimmer, "tier_cloud": repair_calls,
            "baseline": m.get("baseline"), "lines": self.code.count("\n"), "verified": m.get("verified"), "interface_verified": m.get("interface_verified"),
        }

    def export(self) -> Path:
        out = self.path.parent / f"{self.id}.harness"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ("manifest.json", "harness.py"):
                z.write(self.path / name, name)
            for f in self.assets.glob("*"):
                z.write(f, f"assets/{f.name}")
        return out


def all_packages() -> list[Package]:
    config.ensure_dirs()
    pkgs = [Package(p) for p in config.LIBRARY.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    return sorted(pkgs, key=lambda p: p.manifest.get("created", 0), reverse=True)


def create(name: str, goal: str, target: dict) -> Package:
    config.ensure_dirs()
    base = slugify(name)
    path, i = config.LIBRARY / base, 2
    while path.exists():
        path, i = config.LIBRARY / f"{base}-{i}", i + 1
    path.mkdir(parents=True)
    pkg = Package(path)
    pkg.update(name=name, goal=goal, target=target, status="teaching", created=time.time(), version=0, inputs=[])
    pkg.assets
    return pkg


def get(package_id: str) -> Package:
    if not re.fullmatch(r"[a-z0-9-]+", package_id):
        raise KeyError(package_id)
    path = config.LIBRARY / package_id
    if not (path / "manifest.json").exists():
        raise KeyError(package_id)
    return Package(path)


def import_file(file_path: Path) -> Package:
    """Install a .harness file someone shared. Only known files are unpacked, and only to this folder."""
    with zipfile.ZipFile(file_path) as z:
        manifest = json.loads(z.read("manifest.json"))
        pkg = create(manifest.get("name", "imported"), manifest.get("goal", ""), manifest.get("target", {}))
        for info in z.infolist():
            name = info.filename
            if name in ("harness.py",) or re.fullmatch(r"assets/[\w.-]+\.png", name):
                (pkg.path / name).write_bytes(z.read(info))
    manifest.update(status="ready", created=time.time(), imported=True)
    manifest.pop("baseline", None)
    pkg.update(**manifest)
    return pkg
