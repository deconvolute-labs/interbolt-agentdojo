"""Resolve a run's recorded defense policy by content hash, not by trusting its path.

`run_manifest.json.defense.policy_file` is sometimes stale (recorded before a
directory rename). `defense.policy_sha256` is a content hash of the policy
file actually used and is always trustworthy, so policy identity is resolved
by hash lookup against every `*.yaml` under `policies/`, and the recorded
path is reported alongside the resolved one for comparison, never silently
substituted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


def index_policies(policies_root: Path) -> dict[str, Path]:
    """sha256 (hex) -> policy yaml path, for every *.yaml under policies_root."""
    index: dict[str, Path] = {}
    for path in sorted(Path(policies_root).rglob("*.yaml")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        index[digest] = path
    return index


@dataclass(frozen=True)
class PolicyResolution:
    recorded_path: str | None
    sha256: str | None
    resolved_path: Path | None
    recorded_path_exists: bool
    stale: bool  # recorded path doesn't exist on disk, but sha256 resolves elsewhere
    unresolvable: bool  # sha256 present but doesn't match any file under policies_root
    name: str | None  # policy name (yaml stem), from resolved_path if available


def resolve_policy(defense: dict | None, sha_index: dict[str, Path]) -> PolicyResolution | None:
    if defense is None:
        return None
    recorded_path = defense.get("policy_file")
    sha256 = defense.get("policy_sha256")
    resolved_path = sha_index.get(sha256) if sha256 else None
    # Recorded path is checked literally, relative to the repo root (cwd) -- it
    # is never rewritten or "helpfully" resolved against policies_root, since a
    # stale path resolving by accident would defeat the point of this check.
    literal_exists = bool(recorded_path) and Path(recorded_path).exists()
    stale = bool(recorded_path) and not literal_exists and resolved_path is not None
    unresolvable = bool(sha256) and resolved_path is None
    name = resolved_path.stem if resolved_path is not None else (Path(recorded_path).stem if recorded_path else None)
    return PolicyResolution(
        recorded_path=recorded_path,
        sha256=sha256,
        resolved_path=resolved_path,
        recorded_path_exists=literal_exists,
        stale=stale,
        unresolvable=unresolvable,
        name=name,
    )
