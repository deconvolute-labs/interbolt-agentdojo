"""Content-first discovery of benchmark runs under a results root.

Runs are identified by *reading* every `run_manifest.json` found (suite,
attack, defense), never by trusting directory names. Directory names are only
used afterwards, to detect and report a mismatch against the identity the
manifest's own content implies -- this is what surfaces a run whose data was
copied to the wrong path (see `path_mismatch` below) without needing any
suite/policy-specific special-casing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from interbolt_agentdojo.compute_results import _discover_pipeline_name, _load_manifest

from analysis.common.policies import PolicyResolution, index_policies, resolve_policy

ROLE_A_CEILING = "A_ceiling"
ROLE_B_ASR_MODEL = "B_asr_model"
ROLE_C_UTILITY = "C_utility"
ROLE_D_ASR_SYSTEM = "D_asr_system"
ROLE_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RunRecord:
    repeat_dir: Path
    manifest: dict
    suite: str
    attack: str | None
    benchmark_version: str
    model: str
    policy: PolicyResolution | None
    role: str
    expected_dir_name: str
    actual_parent_dir_name: str
    path_mismatch: bool
    pipeline_name: str | None


def _classify_role(attack: str | None, policy: PolicyResolution | None) -> str:
    if policy is None:
        return ROLE_A_CEILING if attack is None else ROLE_UNKNOWN
    if attack is None:
        return ROLE_C_UTILITY
    if policy.name == "allow_all":
        return ROLE_B_ASR_MODEL
    return ROLE_D_ASR_SYSTEM


def _expected_dir_name(role: str, policy: PolicyResolution | None) -> str:
    if role in (ROLE_A_CEILING, ROLE_B_ASR_MODEL):
        return role
    if role in (ROLE_C_UTILITY, ROLE_D_ASR_SYSTEM):
        name = policy.name if policy is not None else "unknown"
        return f"{role}_{name}"
    return role


def find_run_records(results_root: Path, policies_root: Path) -> list[RunRecord]:
    results_root = Path(results_root)
    sha_index = index_policies(policies_root)

    records: list[RunRecord] = []
    for manifest_path in sorted(results_root.rglob("run_manifest.json")):
        repeat_dir = manifest_path.parent
        manifest = _load_manifest(repeat_dir)
        policy = resolve_policy(manifest.get("defense"), sha_index)
        role = _classify_role(manifest.get("attack"), policy)
        expected_dir_name = _expected_dir_name(role, policy)
        actual_parent_dir_name = repeat_dir.parent.name
        pipeline_name = _discover_pipeline_name(repeat_dir, manifest["suite"])
        records.append(
            RunRecord(
                repeat_dir=repeat_dir,
                manifest=manifest,
                suite=manifest["suite"],
                attack=manifest.get("attack"),
                benchmark_version=manifest["benchmark_version"],
                model=manifest["model"],
                policy=policy,
                role=role,
                expected_dir_name=expected_dir_name,
                actual_parent_dir_name=actual_parent_dir_name,
                path_mismatch=actual_parent_dir_name != expected_dir_name,
                pipeline_name=pipeline_name,
            )
        )

    records.sort(key=lambda r: (r.suite, r.role, str(r.repeat_dir)))
    return records
