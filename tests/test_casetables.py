"""analysis/common/casetables.py tests. No network calls."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from interbolt_agentdojo.compute_results import _quartet_repeat_metrics

from analysis.common.casetables import build_attacked_case_table, build_benign_task_table, build_quartets
from analysis.common.discovery import find_run_records

PIPELINE_NAME = "claude-3-opus-test"  # "claude-3-opus" substring exempts TaskResults from the >=2 messages rule
SUITE = "banking"
BENCHMARK_VERSION = "v1.2.2"

ALLOW_ALL_DEFENSE = {"policy_file": "policies/allow_all.yaml"}
STRICT_DEFENSE = {"policy_file": "policies/strict.yaml"}


def _write_manifest(repeat_dir: Path, defense: dict | None, attack: str | None = None) -> None:
    repeat_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "suite": SUITE, "benchmark_version": BENCHMARK_VERSION, "model": "test-model",
        "defense": defense, "attack": attack,
    }
    (repeat_dir / "run_manifest.json").write_text(json.dumps(manifest))


def _write_result(
    repeat_dir: Path, user_task_id: str, attack_dir: str, injection_task_id: str | None, utility: bool, security: bool
) -> None:
    directory = repeat_dir / PIPELINE_NAME / SUITE / user_task_id / attack_dir
    directory.mkdir(parents=True, exist_ok=True)
    stem = injection_task_id or "none"
    result = {
        "suite_name": SUITE,
        "pipeline_name": PIPELINE_NAME,
        "user_task_id": user_task_id,
        "injection_task_id": injection_task_id,
        "attack_type": None if attack_dir == "none" else attack_dir,
        "injections": {},
        "messages": [],
        "error": None,
        "utility": utility,
        "security": security,
        "duration": 0.0,
        "agentdojo_package_version": "test",
    }
    (directory / f"{stem}.json").write_text(json.dumps(result))


def _append_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("a") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def _build_no_attack_dir(run_dir: Path, defense: dict | None, utilities: dict[str, bool], *, repeat: int = 0) -> None:
    repeat_dir = run_dir / f"repeat_{repeat}"
    _write_manifest(repeat_dir, defense, attack=None)
    for user_task_id, utility in utilities.items():
        _write_result(repeat_dir, user_task_id, "none", None, utility, security=False)


def _build_attacked_dir(
    run_dir: Path,
    defense: dict | None,
    cases: dict[str, bool],
    call_records: dict[str, list[dict]] | None = None,
    events: dict[str, list[dict]] | None = None,
    *,
    repeat: int = 0,
) -> None:
    repeat_dir = run_dir / f"repeat_{repeat}"
    _write_manifest(repeat_dir, defense, attack="important_instructions")
    run_ids = {user_task_id: f"run-{user_task_id}" for user_task_id in cases}
    run_index_lines = [
        {"seq": i, "run_id": run_ids[u], "user_task_id": u, "injection_task_id": "injection_task_1", "started_at": "2026-07-22T00:00:00Z"}
        for i, u in enumerate(cases)
    ]
    _append_jsonl(repeat_dir / "run_index.jsonl", run_index_lines)
    for user_task_id, security in cases.items():
        _write_result(repeat_dir, user_task_id, "important_instructions", "injection_task_1", utility=True, security=security)
    if call_records is not None:
        for run_id, records in call_records.items():
            _append_jsonl(repeat_dir / "call_records.jsonl", [{**r, "run_id": run_id} for r in records])
    if events is not None:
        for run_id, event_list in events.items():
            _append_jsonl(
                repeat_dir / "interbolt_events.jsonl",
                [
                    {"outcome": e["outcome"], "decision": {"action": e["outcome"], **e["decision"], "run_id": run_id}}
                    for e in event_list
                ],
            )


def _build_quartet(root: Path, *, policy_suffix: str = "strict", defense: dict | None = None) -> tuple[Path, Path, Path, Path]:
    defense = defense if defense is not None else STRICT_DEFENSE
    ceiling = root / "A_ceiling"
    asr_model = root / "B_asr_model"
    utility = root / f"C_utility_{policy_suffix}"
    asr_system = root / f"D_asr_system_{policy_suffix}"

    _build_no_attack_dir(ceiling, None, {"user_task_0": True, "user_task_1": True})
    _build_no_attack_dir(utility, defense, {"user_task_0": True, "user_task_1": False})
    _build_attacked_dir(
        asr_model,
        ALLOW_ALL_DEFENSE,
        cases={"user_task_0": True, "user_task_1": False, "user_task_2": True},
        call_records={
            "run-user_task_0": [{"tool": "agentdojo.send_money", "args": {}}],
            "run-user_task_1": [{"tool": "agentdojo.get_balance", "args": {}}],
            "run-user_task_2": [{"tool": "agentdojo.send_money", "args": {}}],
        },
    )
    _build_attacked_dir(
        asr_system,
        defense,
        cases={"user_task_0": False, "user_task_1": False, "user_task_2": True},
        events={
            "run-user_task_0": [{"outcome": "block", "decision": {"tool": "agentdojo.send_money"}}],
            "run-user_task_2": [{"outcome": "allow", "decision": {"tool": "agentdojo.send_money"}}],
        },
    )
    return ceiling, asr_model, utility, asr_system


# ---------------------------------------------------------------------------
# build_quartets: pairing, sharing, and fail-loud on mismatch
# ---------------------------------------------------------------------------


def test_build_quartets_shares_a_and_b_across_policies(tmp_path):
    root = tmp_path / "runs"
    _build_quartet(root, policy_suffix="strict", defense=STRICT_DEFENSE)
    _build_quartet(root, policy_suffix="targeted", defense={"policy_file": "policies/targeted.yaml"})

    records = find_run_records(root, tmp_path / "policies")
    quartets = build_quartets(records)

    assert {q.policy for q in quartets} == {"strict", "targeted"}
    strict_q = next(q for q in quartets if q.policy == "strict")
    targeted_q = next(q for q in quartets if q.policy == "targeted")
    assert strict_q.a.repeat_dir == targeted_q.a.repeat_dir
    assert strict_q.b.repeat_dir == targeted_q.b.repeat_dir
    assert strict_q.c.repeat_dir != targeted_q.c.repeat_dir


def test_build_quartets_raises_on_repeat_count_mismatch(tmp_path):
    root = tmp_path / "runs"
    _build_quartet(root)
    # A second D repeat with no matching C/B/A repeat -- C/D/A/B repeat counts disagree.
    (root / "D_asr_system_strict" / "repeat_1").mkdir(parents=True)
    _write_manifest(root / "D_asr_system_strict" / "repeat_1", STRICT_DEFENSE)

    records = find_run_records(root, tmp_path / "policies")
    with pytest.raises(ValueError, match="repeat-count mismatch"):
        build_quartets(records)


# ---------------------------------------------------------------------------
# build_attacked_case_table: cross-check against the already-verified
# _quartet_repeat_metrics aggregate pipeline on the identical fixture.
# ---------------------------------------------------------------------------


def test_build_attacked_case_table_matches_quartet_repeat_metrics_taxonomy(tmp_path):
    root = tmp_path / "runs"
    ceiling, asr_model, utility, asr_system = _build_quartet(root)

    records = find_run_records(root, tmp_path / "policies")
    quartets = build_quartets(records)
    assert len(quartets) == 1

    attacked, missing = build_attacked_case_table(quartets)
    assert missing == []

    expected = _quartet_repeat_metrics(
        ceiling / "repeat_0", asr_model / "repeat_0", utility / "repeat_0", asr_system / "repeat_0", allow_dirty=True
    )
    assert Counter(r.bucket for r in attacked) == expected["taxonomy"]
    assert sum(Counter(r.bucket for r in attacked).values()) == 3


def test_build_attacked_case_table_reports_missing_from_d(tmp_path):
    root = tmp_path / "runs"
    ceiling = root / "A_ceiling"
    asr_model = root / "B_asr_model"
    utility = root / "C_utility_strict"
    asr_system = root / "D_asr_system_strict"

    _build_no_attack_dir(ceiling, None, {"user_task_0": True})
    _build_no_attack_dir(utility, STRICT_DEFENSE, {"user_task_0": True})
    # B has two cases; D only covers one -- user_task_1 is missing from D.
    _build_attacked_dir(
        asr_model,
        ALLOW_ALL_DEFENSE,
        cases={"user_task_0": True, "user_task_1": True},
        call_records={
            "run-user_task_0": [{"tool": "agentdojo.send_money", "args": {}}],
            "run-user_task_1": [{"tool": "agentdojo.send_money", "args": {}}],
        },
    )
    _build_attacked_dir(asr_system, STRICT_DEFENSE, cases={"user_task_0": False})

    records = find_run_records(root, tmp_path / "policies")
    quartets = build_quartets(records)
    attacked, missing = build_attacked_case_table(quartets)

    assert len(attacked) == 1  # only user_task_0 classified
    assert len(missing) == 1
    assert missing[0].user_task_id == "user_task_1"
    assert missing[0].from_role == "D"


def test_build_benign_task_table_joins_a_and_c(tmp_path):
    root = tmp_path / "runs"
    _build_quartet(root)

    records = find_run_records(root, tmp_path / "policies")
    quartets = build_quartets(records)
    benign, missing = build_benign_task_table(quartets)

    assert missing == []
    by_task = {r.user_task_id: r for r in benign}
    assert by_task["user_task_0"].utility_a is True
    assert by_task["user_task_0"].utility_c is True
    assert by_task["user_task_1"].utility_a is True
    assert by_task["user_task_1"].utility_c is False
