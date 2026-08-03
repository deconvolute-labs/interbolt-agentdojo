"""Tier 3, N10: trajectory cost.

Calls per case, D versus B (attacked, defended vs. undefended) and C versus A (benign, defended
vs. undefended), per (suite, policy, repeat, user_task_id, injection_task_id-or-None). A has no
`call_records.jsonl` (confirmed in prior tier2 work -- it never touches Interbolt), so its call
counts come from the raw AgentDojo message log via `raw_tool_call_names`, same fix already applied
in `analysis/tier2/shared_sinks.py`; B/C/D counts come from `call_records.jsonl` directly.

Named sanity check from the spec: banking strict's D-run `blocks_attacked` swung 297 to 334
between repeats (~12%) against near-identical case outcomes -- this module recomputes that count
independently and reports whether it still lands there, as a cross-check that this module's own
counting agrees with the already-verified figure, not a new finding.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from analysis.common.artifacts import (
    case_json_path,
    case_to_run_id,
    count_blocks,
    discover_results,
    events_by_run_id,
    load_call_records,
    raw_tool_call_names,
    read_json,
    selected_run_ids,
)
from analysis.common.casetables import Quartet
from analysis.common.discovery import RunRecord


@dataclass(frozen=True)
class TrajectoryCostRow:
    suite: str
    policy: str
    repeat: int
    user_task_id: str
    injection_task_id: str | None  # None for benign
    n_calls_undefended: int  # B (attacked) or A (benign)
    n_calls_defended: int  # D (attacked) or C (benign)
    delta: int  # defended - undefended
    policy_fingerprint: str


def _case_call_counts(record: RunRecord, cases: dict) -> dict[tuple, int]:
    """case_key -> call count, for a role with call_records.jsonl (B, C, D)."""
    if record.pipeline_name is None:
        return {}
    run_ids = case_to_run_id(record.repeat_dir, cases)
    call_records = load_call_records(record.repeat_dir)
    return {key: len(call_records.get(rid, [])) for key, rid in run_ids.items()}


def _case_call_counts_raw(record: RunRecord, cases: dict) -> dict[tuple, int]:
    """case_key -> call count, for A (no call_records.jsonl -- reads the raw message log)."""
    if record.pipeline_name is None:
        return {}
    counts: dict[tuple, int] = {}
    for case_key in cases:
        user_task_id, injection_task_id = case_key
        path = case_json_path(record.repeat_dir, record.pipeline_name, record.suite, user_task_id, injection_task_id)
        if not path.exists():
            continue
        data = read_json(path)
        counts[case_key] = len(raw_tool_call_names(data.get("messages", [])))
    return counts


def compute_attacked_rows(quartets: list[Quartet]) -> list[TrajectoryCostRow]:
    rows: list[TrajectoryCostRow] = []
    for q in quartets:
        if q.b.pipeline_name is None or q.d.pipeline_name is None:
            continue
        _, with_inj_b = discover_results(q.b.repeat_dir, q.b.pipeline_name, q.b.suite, q.b.benchmark_version)
        _, with_inj_d = discover_results(q.d.repeat_dir, q.d.pipeline_name, q.d.suite, q.d.benchmark_version)
        counts_b = _case_call_counts(q.b, with_inj_b)
        counts_d = _case_call_counts(q.d, with_inj_d)
        policy_fingerprint = (q.d.policy.sha256 if q.d.policy else None) or ""
        for case_key in sorted(set(with_inj_b) & set(with_inj_d)):
            n_b, n_d = counts_b.get(case_key), counts_d.get(case_key)
            if n_b is None or n_d is None:
                continue
            rows.append(
                TrajectoryCostRow(
                    suite=q.suite, policy=q.policy, repeat=q.repeat,
                    user_task_id=case_key[0], injection_task_id=case_key[1],
                    n_calls_undefended=n_b, n_calls_defended=n_d, delta=n_d - n_b,
                    policy_fingerprint=policy_fingerprint,
                )
            )
    rows.sort(key=lambda r: (r.suite, r.policy, r.repeat, r.user_task_id, r.injection_task_id or ""))
    return rows


def compute_benign_rows(quartets: list[Quartet]) -> list[TrajectoryCostRow]:
    rows: list[TrajectoryCostRow] = []
    for q in quartets:
        if q.a.pipeline_name is None or q.c.pipeline_name is None:
            continue
        without_inj_a, _ = discover_results(q.a.repeat_dir, q.a.pipeline_name, q.a.suite, q.a.benchmark_version)
        without_inj_c, _ = discover_results(q.c.repeat_dir, q.c.pipeline_name, q.c.suite, q.c.benchmark_version)
        counts_a = _case_call_counts_raw(q.a, without_inj_a)
        counts_c = _case_call_counts(q.c, without_inj_c)
        policy_fingerprint = (q.c.policy.sha256 if q.c.policy else None) or ""
        for case_key in sorted(set(without_inj_a) & set(without_inj_c)):
            n_a, n_c = counts_a.get(case_key), counts_c.get(case_key)
            if n_a is None or n_c is None:
                continue
            rows.append(
                TrajectoryCostRow(
                    suite=q.suite, policy=q.policy, repeat=q.repeat,
                    user_task_id=case_key[0], injection_task_id=None,
                    n_calls_undefended=n_a, n_calls_defended=n_c, delta=n_c - n_a,
                    policy_fingerprint=policy_fingerprint,
                )
            )
    rows.sort(key=lambda r: (r.suite, r.policy, r.repeat, r.user_task_id))
    return rows


def blocks_attacked_by_config(quartets: list[Quartet]) -> dict[tuple[str, str, int], int]:
    """(suite, policy, repeat) -> total block count in that D run, deduplicated to scored
    attempts -- independent recomputation used to sanity-check the spec's named 297/334 swing."""
    result: dict[tuple[str, str, int], int] = {}
    for q in quartets:
        if q.d.pipeline_name is None:
            continue
        without_inj, with_inj = discover_results(q.d.repeat_dir, q.d.pipeline_name, q.d.suite, q.d.benchmark_version)
        selected = selected_run_ids(q.d.repeat_dir, without_inj, with_inj)
        events = [e for rid, evs in events_by_run_id(q.d.repeat_dir).items() if rid in selected for e in evs]
        result[(q.suite, q.policy, q.repeat)] = count_blocks(events)
    return result


_FIELDS = ["suite", "policy", "repeat", "user_task_id", "injection_task_id",
           "n_calls_undefended", "n_calls_defended", "delta", "policy_fingerprint"]


def write_csv(rows: list[TrajectoryCostRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [r.suite, r.policy, r.repeat, r.user_task_id, r.injection_task_id or "",
                 r.n_calls_undefended, r.n_calls_defended, r.delta, r.policy_fingerprint]
            )


def render_markdown(attacked_rows: list[TrajectoryCostRow], benign_rows: list[TrajectoryCostRow], quartets: list[Quartet]) -> str:
    lines = ["## N10. Trajectory cost", ""]
    lines.append("Calls per case, D vs. B (attacked) and C vs. A (benign). Positive `delta` means the defended run made more calls than the undefended baseline for the same case.")
    lines.append("")

    for title, rows in (("Attacked (D vs. B)", attacked_rows), ("Benign (C vs. A)", benign_rows)):
        lines.append(f"### {title}")
        lines.append("")
        by_key: dict[tuple[str, str, int], list[TrajectoryCostRow]] = {}
        for r in rows:
            by_key.setdefault((r.suite, r.policy, r.repeat), []).append(r)
        lines.append("| Suite | Policy | Repeat | Cases | Total calls (undefended) | Total calls (defended) | Total delta |")
        lines.append("|---|---|---|---|---|---|---|")
        for (suite, policy, repeat), group in sorted(by_key.items()):
            total_u = sum(r.n_calls_undefended for r in group)
            total_d = sum(r.n_calls_defended for r in group)
            lines.append(f"| {suite} | {policy} | {repeat} | {len(group)} | {total_u} | {total_d} | {total_d - total_u} |")
        lines.append("")

    lines.append("### Named sanity check: banking strict's D-run `blocks_attacked` swing")
    lines.append("")
    blocks = blocks_attacked_by_config(quartets)
    banking_strict = {repeat: n for (suite, policy, repeat), n in blocks.items() if suite == "banking" and policy == "strict"}
    reproduced = banking_strict.get(0) == 297 and banking_strict.get(1) == 334
    lines.append(
        f"Recomputed independently: repeat 0 = {banking_strict.get(0, 'n/a')}, repeat 1 = {banking_strict.get(1, 'n/a')}. "
        + ("**Matches the spec's published 297/334 -- this module's counting agrees with the already-verified figure.**"
           if reproduced else "**Does not match the spec's published 297/334 -- investigate before trusting this module's counts.**")
    )
    lines.append("")

    return "\n".join(lines)
