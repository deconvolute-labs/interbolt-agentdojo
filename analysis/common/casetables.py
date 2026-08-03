"""The two case-level tables `analysis/verification.md`'s final section says everything
else derives from: one row per attacked case (the B x D join) and one row per benign
task (the A x C join).

Both builders below are a case-granularity replica of
`interbolt_agentdojo.compute_results._quartet_repeat_metrics`'s join -- same helpers,
same taxonomy function, same source-of-truth rule (AgentDojo's own `utility`/`security`
booleans score; Interbolt's events/call-records only answer "was the target sink
reached/blocked"). That function only exposes aggregate counts; these builders expose
the same computation per case so Phase 1's checks and Phase 2B's N1/N2/N6 don't need to
recompute the join themselves.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suite

from analysis.common.artifacts import (
    case_to_run_id,
    classify_case,
    count_blocks,
    discover_results,
    events_by_run_id,
    interbolt_blocked_target_sink,
    load_call_records,
    reached_target_sink,
    target_tools,
)
from analysis.common.discovery import (
    ROLE_A_CEILING,
    ROLE_B_ASR_MODEL,
    ROLE_C_UTILITY,
    ROLE_D_ASR_SYSTEM,
    RunRecord,
)


@dataclass(frozen=True)
class Quartet:
    """One suite/policy/repeat's four run roles. A and B are shared across every
    policy for a given suite/repeat; C and D are specific to `policy`."""

    suite: str
    policy: str
    repeat: int  # positional index within the sorted repeat sequence, not a directory name
    a: RunRecord
    b: RunRecord
    c: RunRecord
    d: RunRecord


@dataclass(frozen=True)
class AttackedCaseRow:
    suite: str
    policy: str
    repeat: int
    user_task_id: str
    injection_task_id: str
    security_b: bool
    security_d: bool
    reached_sink_b: bool
    blocked_d: bool
    bucket: str
    n_blocks: int  # decision.action == "block" events in this case's D run
    n_calls: int  # call_records.jsonl entries in this case's D run
    run_id_b: str | None
    run_id_d: str | None
    policy_fingerprint: str


@dataclass(frozen=True)
class BenignTaskRow:
    suite: str
    policy: str
    repeat: int
    user_task_id: str
    utility_a: bool
    utility_c: bool
    n_blocks: int  # decision.action == "block" events in this task's C run
    n_calls: int  # call_records.jsonl entries in this task's C run
    policy_fingerprint: str


@dataclass(frozen=True)
class MissingCase:
    """A case/task present in the shared baseline (B or A) but absent from the
    policy-specific run (D or C) -- reported, never silently dropped (see I10)."""

    suite: str
    policy: str
    repeat: int
    user_task_id: str
    injection_task_id: str | None
    from_role: str  # "D" or "C" -- which side of the join the case was missing from


def build_quartets(records: list[RunRecord]) -> list[Quartet]:
    """Group discovered runs into (A, B, C, D) quartets per (suite, policy, repeat).

    Repeats pair positionally (sorted by `repeat_dir.name`), mirroring
    `compute_results._five_numbers`'s existing behavior -- never assumed to share
    literal directory names across roles. Raises loudly on a policy present on one
    side of C/D but not the other, or on a repeat-count mismatch across A/B/C/D,
    rather than silently truncating to the shorter list.
    """
    quartets: list[Quartet] = []
    for suite in sorted({r.suite for r in records}):
        suite_records = [r for r in records if r.suite == suite]
        a_records = sorted((r for r in suite_records if r.role == ROLE_A_CEILING), key=lambda r: r.repeat_dir.name)
        b_records = sorted((r for r in suite_records if r.role == ROLE_B_ASR_MODEL), key=lambda r: r.repeat_dir.name)

        c_by_policy: dict[str, list[RunRecord]] = {}
        d_by_policy: dict[str, list[RunRecord]] = {}
        for r in suite_records:
            if r.role == ROLE_C_UTILITY and r.policy is not None:
                c_by_policy.setdefault(r.policy.name, []).append(r)
            elif r.role == ROLE_D_ASR_SYSTEM and r.policy is not None:
                d_by_policy.setdefault(r.policy.name, []).append(r)

        for policy_name in sorted(set(c_by_policy) | set(d_by_policy)):
            c_records = sorted(c_by_policy.get(policy_name, []), key=lambda r: r.repeat_dir.name)
            d_records = sorted(d_by_policy.get(policy_name, []), key=lambda r: r.repeat_dir.name)
            counts = {"A": len(a_records), "B": len(b_records), "C": len(c_records), "D": len(d_records)}
            if len(set(counts.values())) != 1:
                raise ValueError(
                    f"quartet repeat-count mismatch for suite={suite!r} policy={policy_name!r}: {counts} "
                    "-- every role must have the same number of repeats, paired positionally"
                )
            for i, (a, b, c, d) in enumerate(zip(a_records, b_records, c_records, d_records)):
                quartets.append(Quartet(suite=suite, policy=policy_name, repeat=i, a=a, b=b, c=c, d=d))

    quartets.sort(key=lambda q: (q.suite, q.policy, q.repeat))
    return quartets


def _require_pipeline(record: RunRecord) -> str:
    if record.pipeline_name is None:
        raise ValueError(
            f"no pipeline results found under {record.repeat_dir} "
            f"(suite={record.suite!r}, role={record.role!r}) -- run_manifest.json exists but no "
            "AgentDojo trace directory was found beneath it"
        )
    return record.pipeline_name


def build_attacked_case_table(quartets: list[Quartet]) -> tuple[list[AttackedCaseRow], list[MissingCase]]:
    """One row per (user_task, injection_task) case in every quartet's B run, joined
    against D. Cases present in B but absent from D are reported in the second return
    value rather than dropped (see `analysis/verification.md` I10)."""
    rows: list[AttackedCaseRow] = []
    missing: list[MissingCase] = []

    for q in quartets:
        _require_pipeline(q.b)
        _require_pipeline(q.d)
        suite = get_suite(q.b.benchmark_version, q.b.suite)

        _, with_injections_b = discover_results(q.b.repeat_dir, q.b.pipeline_name, q.b.suite, q.b.benchmark_version)
        _, with_injections_d = discover_results(q.d.repeat_dir, q.d.pipeline_name, q.d.suite, q.d.benchmark_version)
        case_to_run_b = case_to_run_id(q.b.repeat_dir, with_injections_b)
        case_to_run_d = case_to_run_id(q.d.repeat_dir, with_injections_d)
        call_records_b = load_call_records(q.b.repeat_dir)
        call_records_d = load_call_records(q.d.repeat_dir)
        events_by_run_d = events_by_run_id(q.d.repeat_dir)
        policy_fingerprint = (q.d.policy.sha256 if q.d.policy else None) or ""

        for case_key, result_b in with_injections_b.items():
            user_task_id, injection_task_id = case_key
            result_d = with_injections_d.get(case_key)
            if result_d is None:
                missing.append(
                    MissingCase(
                        suite=q.suite,
                        policy=q.policy,
                        repeat=q.repeat,
                        user_task_id=user_task_id,
                        injection_task_id=injection_task_id,
                        from_role="D",
                    )
                )
                continue

            tools = target_tools(suite, injection_task_id)
            run_id_b = case_to_run_b.get(case_key)
            run_id_d = case_to_run_d.get(case_key)

            reached_sink_b = reached_target_sink(call_records_b.get(run_id_b, []), tools)
            events_for_case_d = events_by_run_d.get(run_id_d, [])
            blocked_d = interbolt_blocked_target_sink(events_for_case_d, tools)
            bucket = classify_case(bool(result_b.security), reached_sink_b, bool(result_d.security), blocked_d)

            rows.append(
                AttackedCaseRow(
                    suite=q.suite,
                    policy=q.policy,
                    repeat=q.repeat,
                    user_task_id=user_task_id,
                    injection_task_id=injection_task_id,
                    security_b=bool(result_b.security),
                    security_d=bool(result_d.security),
                    reached_sink_b=reached_sink_b,
                    blocked_d=blocked_d,
                    bucket=bucket,
                    n_blocks=count_blocks(events_for_case_d),
                    n_calls=len(call_records_d.get(run_id_d, [])),
                    run_id_b=run_id_b,
                    run_id_d=run_id_d,
                    policy_fingerprint=policy_fingerprint,
                )
            )

    rows.sort(key=lambda r: (r.suite, r.policy, r.repeat, r.user_task_id, r.injection_task_id))
    missing.sort(key=lambda m: (m.suite, m.policy, m.repeat, m.user_task_id, m.injection_task_id or ""))
    return rows, missing


def build_benign_task_table(quartets: list[Quartet]) -> tuple[list[BenignTaskRow], list[MissingCase]]:
    """One row per user_task in every quartet's A run, joined against C. Tasks present
    in A but absent from C are reported in the second return value rather than
    dropped."""
    rows: list[BenignTaskRow] = []
    missing: list[MissingCase] = []

    for q in quartets:
        _require_pipeline(q.a)
        _require_pipeline(q.c)

        without_injections_a, _ = discover_results(q.a.repeat_dir, q.a.pipeline_name, q.a.suite, q.a.benchmark_version)
        without_injections_c, _ = discover_results(q.c.repeat_dir, q.c.pipeline_name, q.c.suite, q.c.benchmark_version)
        case_to_run_c = case_to_run_id(q.c.repeat_dir, without_injections_c)
        call_records_c = load_call_records(q.c.repeat_dir)
        events_by_run_c = events_by_run_id(q.c.repeat_dir)
        policy_fingerprint = (q.c.policy.sha256 if q.c.policy else None) or ""

        for case_key, result_a in without_injections_a.items():
            user_task_id = case_key[0]
            result_c = without_injections_c.get(case_key)
            if result_c is None:
                missing.append(
                    MissingCase(
                        suite=q.suite,
                        policy=q.policy,
                        repeat=q.repeat,
                        user_task_id=user_task_id,
                        injection_task_id=None,
                        from_role="C",
                    )
                )
                continue

            run_id_c = case_to_run_c.get(case_key)
            events_for_task_c = events_by_run_c.get(run_id_c, [])

            rows.append(
                BenignTaskRow(
                    suite=q.suite,
                    policy=q.policy,
                    repeat=q.repeat,
                    user_task_id=user_task_id,
                    utility_a=bool(result_a.utility),
                    utility_c=bool(result_c.utility),
                    n_blocks=count_blocks(events_for_task_c),
                    n_calls=len(call_records_c.get(run_id_c, [])),
                    policy_fingerprint=policy_fingerprint,
                )
            )

    rows.sort(key=lambda r: (r.suite, r.policy, r.repeat, r.user_task_id))
    missing.sort(key=lambda m: (m.suite, m.policy, m.repeat, m.user_task_id))
    return rows, missing


def refusal_counts_by_injection_task(record: RunRecord) -> dict[str, tuple[int, int]]:
    """injection_task_id -> (model_refused count, case count), from one B repeat's
    attacked cases.

    `model_refused`/`out_of_scope` are policy-invariant (`analysis/verification.md`
    I4): fully determined by `security_b`/`reached_sink_b`, so no D run is needed.
    `classify_case` is called with dummy `security_d=False, blocked_d=False` -- safe,
    since it returns before touching either argument whenever `reached_sink_b` is
    false or `security_b` is false, which covers both `model_refused` and
    `out_of_scope`.
    """
    if record.pipeline_name is None:
        return {}
    suite = get_suite(record.benchmark_version, record.suite)
    _, with_injections = discover_results(record.repeat_dir, record.pipeline_name, record.suite, record.benchmark_version)
    run_ids = case_to_run_id(record.repeat_dir, with_injections)
    call_records = load_call_records(record.repeat_dir)

    counts: dict[str, tuple[int, int]] = {}
    for (user_task_id, injection_task_id), result in with_injections.items():
        tools = target_tools(suite, injection_task_id)
        records = call_records.get(run_ids.get((user_task_id, injection_task_id)), [])
        reached = reached_target_sink(records, tools)
        bucket = classify_case(bool(result.security), reached, False, False)
        refused, total = counts.get(injection_task_id, (0, 0))
        counts[injection_task_id] = (refused + (bucket == "model_refused"), total + 1)
    return counts


_ATTACKED_FIELDS = [
    "suite", "policy", "repeat", "user_task_id", "injection_task_id",
    "security_b", "security_d", "reached_sink_b", "blocked_d", "bucket",
    "n_blocks", "n_calls", "run_id_b", "run_id_d", "policy_fingerprint",
]

_BENIGN_FIELDS = [
    "suite", "policy", "repeat", "user_task_id",
    "utility_a", "utility_c", "n_blocks", "n_calls", "policy_fingerprint",
]


def write_attacked_csv(rows: list[AttackedCaseRow], path: Path) -> None:
    """gated_sink_cases.csv -- despite the name, every attacked case (all six
    taxonomy buckets), per the Phase 5 file tree's own description: "one row per
    case with bucket, per policy and repeat." n_blocks/n_calls are D-run counts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_ATTACKED_FIELDS)
        for r in rows:
            writer.writerow(
                [
                    r.suite, r.policy, r.repeat, r.user_task_id, r.injection_task_id,
                    r.security_b, r.security_d, r.reached_sink_b, r.blocked_d, r.bucket,
                    r.n_blocks, r.n_calls, r.run_id_b, r.run_id_d, r.policy_fingerprint,
                ]
            )


def write_benign_csv(rows: list[BenignTaskRow], path: Path) -> None:
    """utility_per_task.csv. n_blocks/n_calls are C-run counts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_BENIGN_FIELDS)
        for r in rows:
            writer.writerow(
                [
                    r.suite, r.policy, r.repeat, r.user_task_id,
                    r.utility_a, r.utility_c, r.n_blocks, r.n_calls, r.policy_fingerprint,
                ]
            )
