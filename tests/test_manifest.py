"""manifest.py tests. No network calls."""

from __future__ import annotations

import argparse
import hashlib
import json

from interbolt_agentdojo.manifest import write_manifest

REQUIRED_KEYS = {
    "command",
    "run_started_at",
    "run_finished_at",
    "suite",
    "benchmark_version",
    "model",
    "attack",
    "user_tasks",
    "injection_tasks",
    "repeats",
    "defense",
    "interbolt",
    "agentdojo",
    "python_version",
    "platform",
}


def _args(tmp_path, policy=None) -> argparse.Namespace:
    return argparse.Namespace(
        run_started_at="2026-07-20T00:00:00Z",
        run_finished_at="2026-07-20T00:01:00Z",
        suite="banking",
        benchmark_version="v1.2.2",
        model="claude-3-haiku-20240307",
        attack=None,
        user_tasks=None,
        injection_tasks=None,
        repeats=1,
        policy=policy,
        mode="enforce" if policy else None,
    )


def test_manifest_contains_all_required_keys(tmp_path):
    manifest_path = write_manifest(tmp_path, _args(tmp_path))
    manifest = json.loads(manifest_path.read_text())
    assert REQUIRED_KEYS <= manifest.keys()
    assert manifest["defense"] is None


def test_manifest_detects_editable_interbolt_install(tmp_path):
    manifest_path = write_manifest(tmp_path, _args(tmp_path))
    manifest = json.loads(manifest_path.read_text())
    # This dev checkout depends on interbolt via an editable path source
    # (pyproject.toml [tool.uv.sources]); confirm that's detected.
    assert manifest["interbolt"]["install_mode"] == "editable"
    assert manifest["interbolt"]["commit"] is not None
    assert isinstance(manifest["interbolt"]["dirty"], bool)


def test_policy_sha256_is_stable(tmp_path):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("version: '1.0'\ndefaults:\n  sink_action: allow\nsources: []\nsinks: {}\n")
    expected = hashlib.sha256(policy_path.read_bytes()).hexdigest()

    manifest_path = write_manifest(tmp_path / "run1", _args(tmp_path, policy=str(policy_path)))
    manifest = json.loads(manifest_path.read_text())
    assert manifest["defense"]["policy_sha256"] == expected

    manifest_path_2 = write_manifest(tmp_path / "run2", _args(tmp_path, policy=str(policy_path)))
    manifest_2 = json.loads(manifest_path_2.read_text())
    assert manifest_2["defense"]["policy_sha256"] == expected
