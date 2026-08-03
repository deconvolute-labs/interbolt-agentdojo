"""Tier 3, N13: cross-suite consistency.

Blocks per gated call, share of trajectories with at least one block, taint onset, and block
rate, across banking (11 tools) and travel (28 tools). A rollup, not new computation: pulls tool
counts from `suite_metadata`, block rate from the already-verified `quartet_repeat_metrics`
pipeline, block-with-a-block share from `AttackedCaseRow.n_blocks` (already computed by
`casetables.build_attacked_case_table`), and taint onset by calling
`positional_distributions.compute_taint_onset_rows` directly rather than recomputing it -- the
same "import, don't duplicate" pattern `phase2b/per_injection_task.py` already uses against
`pseudo_case_standalone.py`.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from interbolt import Action, Policy

from analysis.common.artifacts import count_blocks, events_by_run_id, load_call_records, quartet_repeat_metrics
from analysis.common.casetables import AttackedCaseRow, Quartet
from analysis.common.discovery import RunRecord
from analysis.tier3.positional_distributions import TaintOnsetRow
from analysis.tier3.suite_metadata import compute_rows as compute_suite_metadata_rows


@dataclass(frozen=True)
class CrossSuiteRow:
    suite: str
    policy: str
    repeat: int
    n_tools: int
    n_gated_sinks: int
    n_gated_calls: int  # C+D calls to a gated sink
    n_blocks: int  # C+D total blocks
    blocks_per_gated_call: float | None
    n_attacked_cases: int
    n_attacked_cases_with_block: int
    share_with_block: float | None
    block_rate_num: int
    block_rate_den: int
    block_rate: float | None
    taint_onset_median: float | None  # pooled across both repeats for this (suite, policy)
    policy_fingerprint: str


def _gated_sinks(resolved_policy_path) -> set[str]:
    document = Policy.from_file(str(resolved_policy_path)).document
    return {sink for sink, rules in document.sinks.items() if any(r.action is Action.BLOCK for r in rules)}


def _gated_calls_and_blocks(record: RunRecord, gated_sinks: set[str]) -> tuple[int, int]:
    """(calls to a gated sink, blocks) in one C or D run, across every discovered call/event --
    not deduplicated to scored attempts, matching N10's own call-counting convention (raw
    call_records.jsonl totals), since this is about calls actually dispatched, not case scoring."""
    if record.pipeline_name is None:
        return 0, 0
    call_records = load_call_records(record.repeat_dir)
    n_gated_calls = sum(1 for calls in call_records.values() for c in calls if c["tool"] in gated_sinks)
    n_blocks = sum(count_blocks(evs) for evs in events_by_run_id(record.repeat_dir).values())
    return n_gated_calls, n_blocks


def _taint_onset_median(taint_rows: list[TaintOnsetRow], suite: str, policy: str) -> float | None:
    values = sorted(r.onset_index for r in taint_rows if r.suite == suite and r.policy == policy and r.onset_index is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def compute_rows(quartets: list[Quartet], attacked: list[AttackedCaseRow], taint_rows: list[TaintOnsetRow]) -> list[CrossSuiteRow]:
    n_tools_by_suite = {r.suite: r.n_tools_total for r in compute_suite_metadata_rows()}
    attacked_by_key: dict[tuple[str, str, int], list[AttackedCaseRow]] = {}
    for r in attacked:
        attacked_by_key.setdefault((r.suite, r.policy, r.repeat), []).append(r)

    rows: list[CrossSuiteRow] = []
    for q in quartets:
        if q.d.policy is None or q.d.policy.resolved_path is None:
            continue
        gated_sinks = _gated_sinks(q.d.policy.resolved_path)
        gc_c, blocks_c = _gated_calls_and_blocks(q.c, gated_sinks)
        gc_d, blocks_d = _gated_calls_and_blocks(q.d, gated_sinks)
        n_gated_calls, n_blocks = gc_c + gc_d, blocks_c + blocks_d

        case_rows = attacked_by_key.get((q.suite, q.policy, q.repeat), [])
        n_attacked = len(case_rows)
        n_with_block = sum(1 for r in case_rows if r.n_blocks > 0)

        metrics = quartet_repeat_metrics(q.a.repeat_dir, q.b.repeat_dir, q.c.repeat_dir, q.d.repeat_dir, allow_dirty=True)
        block_rate = metrics["block_rate_interbolt"]
        block_rate_num = metrics["taxonomy"].get("interbolt_blocked", 0)
        block_rate_den = metrics["block_rate_denom"]

        rows.append(
            CrossSuiteRow(
                suite=q.suite, policy=q.policy, repeat=q.repeat,
                n_tools=n_tools_by_suite.get(q.suite, 0),
                n_gated_sinks=len(gated_sinks),
                n_gated_calls=n_gated_calls, n_blocks=n_blocks,
                blocks_per_gated_call=(n_blocks / n_gated_calls) if n_gated_calls else None,
                n_attacked_cases=n_attacked, n_attacked_cases_with_block=n_with_block,
                share_with_block=(n_with_block / n_attacked) if n_attacked else None,
                block_rate_num=block_rate_num, block_rate_den=block_rate_den, block_rate=block_rate,
                taint_onset_median=_taint_onset_median(taint_rows, q.suite, q.policy),
                policy_fingerprint=q.d.policy.sha256 or "",
            )
        )
    rows.sort(key=lambda r: (r.suite, r.policy, r.repeat))
    return rows


_FIELDS = ["suite", "policy", "repeat", "n_tools", "n_gated_sinks", "n_gated_calls", "n_blocks",
           "blocks_per_gated_call", "n_attacked_cases", "n_attacked_cases_with_block", "share_with_block",
           "block_rate_num", "block_rate_den", "block_rate", "taint_onset_median", "policy_fingerprint"]


def write_csv(rows: list[CrossSuiteRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [
                    r.suite, r.policy, r.repeat, r.n_tools, r.n_gated_sinks, r.n_gated_calls, r.n_blocks,
                    f"{r.blocks_per_gated_call:.4f}" if r.blocks_per_gated_call is not None else "",
                    r.n_attacked_cases, r.n_attacked_cases_with_block,
                    f"{r.share_with_block:.4f}" if r.share_with_block is not None else "",
                    r.block_rate_num, r.block_rate_den,
                    f"{r.block_rate:.4f}" if r.block_rate is not None else "",
                    r.taint_onset_median if r.taint_onset_median is not None else "",
                    r.policy_fingerprint,
                ]
            )


def render_markdown(rows: list[CrossSuiteRow]) -> str:
    lines = ["## N13. Cross-suite consistency", ""]
    lines.append(
        "Banking (11 tools) vs. travel (28 tools), same metrics side by side. "
        "`taint_onset_median` is pooled across both repeats for a (suite, policy) -- it does not "
        "vary by repeat in this table even though the row grain is per-repeat."
    )
    lines.append("")
    lines.append("| Suite | Policy | Repeat | Tools | Gated sinks | Gated calls | Blocks | "
                 "Blocks/gated call | Attacked cases | ...with block | Share | Block rate | Taint onset (median) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        bpgc = f"{r.blocks_per_gated_call:.3f}" if r.blocks_per_gated_call is not None else "n/a"
        share = f"{r.share_with_block:.2f}" if r.share_with_block is not None else "n/a"
        rate = f"{r.block_rate:.2f} ({r.block_rate_num}/{r.block_rate_den})" if r.block_rate is not None else "undefined"
        onset = f"{r.taint_onset_median:.1f}" if r.taint_onset_median is not None else "n/a"
        lines.append(
            f"| {r.suite} | {r.policy} | {r.repeat} | {r.n_tools} | {r.n_gated_sinks} | {r.n_gated_calls} | "
            f"{r.n_blocks} | {bpgc} | {r.n_attacked_cases} | {r.n_attacked_cases_with_block} | {share} | "
            f"{rate} | {onset} |"
        )
    lines.append("")
    return "\n".join(lines)
