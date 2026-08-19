"""Reproducibility metadata: `run_manifest.json` per benchmark invocation."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from importlib.metadata import Distribution, PackageNotFoundError
from pathlib import Path
from urllib.parse import urlparse


def _git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _package_info(name: str) -> dict:
    try:
        dist = Distribution.from_name(name)
    except PackageNotFoundError:
        return {"version": None, "install_mode": None, "commit": None, "dirty": None}

    version = dist.version
    direct_url_text = dist.read_text("direct_url.json")
    if direct_url_text is None:
        return {"version": version, "install_mode": "package", "commit": None, "dirty": None}

    direct_url = json.loads(direct_url_text)
    is_editable = direct_url.get("dir_info", {}).get("editable", False)
    if not is_editable:
        return {"version": version, "install_mode": "package", "commit": None, "dirty": None}

    source_dir = Path(urlparse(direct_url["url"]).path)
    commit = _git(source_dir, "rev-parse", "HEAD")
    status = _git(source_dir, "status", "--porcelain")
    dirty = bool(status) if status is not None else None
    return {"version": version, "install_mode": "editable", "commit": commit, "dirty": dirty}


def write_manifest(logdir: Path, args) -> Path:
    """Write `<logdir>/run_manifest.json` and return its path."""
    defense = None
    if getattr(args, "policy", None):
        policy_path = Path(args.policy)
        defense = {
            "name": "interbolt",
            "mode": args.mode,
            "agent_id": getattr(args, "agent_id", None),
            "policy_file": str(policy_path),
            "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        }

    manifest = {
        "command": sys.argv,
        "run_started_at": args.run_started_at,
        "run_finished_at": args.run_finished_at,
        "suite": args.suite,
        "benchmark_version": args.benchmark_version,
        "model": args.model,
        "attack": getattr(args, "attack", None),
        "user_tasks": getattr(args, "user_tasks", None),
        "injection_tasks": getattr(args, "injection_tasks", None),
        "repeats": args.repeats,
        "defense": defense,
        "interbolt": _package_info("interbolt"),
        "agentdojo": _package_info("agentdojo"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }

    logdir.mkdir(parents=True, exist_ok=True)
    manifest_path = logdir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path
