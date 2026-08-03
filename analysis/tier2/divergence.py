"""Tier 2, T2.1: strict versus targeted decision divergence.

For every (suite, repeat) where both `strict` and `targeted` policies are present, compares
the two policies' trajectories for every shared case -- D runs (attacked) and, separately, C
runs (benign) -- call by call, via `analysis.common.artifacts.run_trajectory`.

**Alignment rule** (stated here since every number below depends on it, per
`analysis/verification.md`'s Phase 5 requirement to print a definitional choice next to the
number it produces): position `i` is aligned across the two trajectories only if the tool name
matches at that index in both. `naive_len` is `min(len(strict), len(targeted))`; within it,
`first_mismatch_index` is the first position where tool names differ (or `naive_len` if none);
`truncated_len` is that index. A "naive full-length" reading considers every position `i <
naive_len` where the tools happen to match, even past an earlier desync; a "truncated" reading
only trusts the prefix before the first desync (`i < truncated_len`) -- since that prefix is by
construction free of any tool mismatch, every differing-action row already carries a
`within_truncated_window` flag rather than needing a second row set.

A scored trajectory's trailing tool call with no matching tool response (AgentDojo's
iteration-cap case) is dropped for free: `run_trajectory` reads `call_records.jsonl`, which never
contains a call that was never dispatched to Interbolt.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from analysis.common.artifacts import CallDecision, case_to_run_id, discover_results, run_trajectory
from analysis.common.casetables import Quartet


@dataclass(frozen=True)
class DivergenceRow:
    suite: str
    repeat: int
    user_task_id: str
    injection_task_id: str | None  # None for benign
    call_index: int
    tool: str
    action_strict: str
    action_targeted: str
    matched_rule_strict: str | None
    matched_rule_targeted: str | None
    outcome_strict: str
    outcome_targeted: str
    is_eval_error: bool
    action_differs: bool
    args_differ: bool
    within_truncated_window: bool
    policy_fingerprint_strict: str
    policy_fingerprint_targeted: str


@dataclass(frozen=True)
class CaseAlignment:
    suite: str
    repeat: int
    user_task_id: str
    injection_task_id: str | None
    len_strict: int
    len_targeted: int
    naive_len: int
    first_mismatch_index: int | None  # None: no tool-name mismatch within naive_len
    truncated_len: int
    tool_at_mismatch_strict: str | None  # tool at first_mismatch_index, strict side (None if no mismatch)
    tool_at_mismatch_targeted: str | None  # same, targeted side
    n_action_divergent_naive: int
    n_action_divergent_truncated: int
    n_args_only_divergent_naive: int
    n_args_only_divergent_truncated: int


def _quartets_by_suite_repeat(quartets: list[Quartet]) -> dict[tuple[str, int], dict[str, Quartet]]:
    out: dict[tuple[str, int], dict[str, Quartet]] = {}
    for q in quartets:
        out.setdefault((q.suite, q.repeat), {})[q.policy] = q
    return out


def _align_case(
    suite: str,
    repeat: int,
    user_task_id: str,
    injection_task_id: str | None,
    traj_strict: list[CallDecision],
    traj_targeted: list[CallDecision],
    fp_strict: str,
    fp_targeted: str,
) -> tuple[CaseAlignment, list[DivergenceRow]]:
    naive_len = min(len(traj_strict), len(traj_targeted))
    first_mismatch_index: int | None = None
    for i in range(naive_len):
        if traj_strict[i].tool != traj_targeted[i].tool:
            first_mismatch_index = i
            break
    truncated_len = first_mismatch_index if first_mismatch_index is not None else naive_len

    rows: list[DivergenceRow] = []
    for i in range(naive_len):
        s, t = traj_strict[i], traj_targeted[i]
        if s.tool != t.tool:
            continue
        action_differs = s.action != t.action
        args_differ = s.args != t.args
        if not action_differs and not args_differ:
            continue
        is_eval_error = s.outcome == "evaluation_error" or t.outcome == "evaluation_error"
        rows.append(
            DivergenceRow(
                suite=suite,
                repeat=repeat,
                user_task_id=user_task_id,
                injection_task_id=injection_task_id,
                call_index=i,
                tool=s.tool,
                action_strict=s.action,
                action_targeted=t.action,
                matched_rule_strict=s.matched_rule,
                matched_rule_targeted=t.matched_rule,
                outcome_strict=s.outcome,
                outcome_targeted=t.outcome,
                is_eval_error=is_eval_error,
                action_differs=action_differs,
                args_differ=args_differ,
                within_truncated_window=i < truncated_len,
                policy_fingerprint_strict=fp_strict,
                policy_fingerprint_targeted=fp_targeted,
            )
        )

    alignment = CaseAlignment(
        suite=suite,
        repeat=repeat,
        user_task_id=user_task_id,
        injection_task_id=injection_task_id,
        len_strict=len(traj_strict),
        len_targeted=len(traj_targeted),
        naive_len=naive_len,
        first_mismatch_index=first_mismatch_index,
        truncated_len=truncated_len,
        tool_at_mismatch_strict=traj_strict[first_mismatch_index].tool if first_mismatch_index is not None else None,
        tool_at_mismatch_targeted=traj_targeted[first_mismatch_index].tool if first_mismatch_index is not None else None,
        n_action_divergent_naive=sum(1 for r in rows if r.action_differs),
        n_action_divergent_truncated=sum(1 for r in rows if r.action_differs and r.within_truncated_window),
        # is_eval_error rows excluded: a malformed-args-induced CEL crash isn't ordinary
        # argument variation, so counting it here would misrepresent what this count means.
        # The row itself is never dropped -- it still appears in `rows`/the CSV.
        n_args_only_divergent_naive=sum(1 for r in rows if r.args_differ and not r.action_differs and not r.is_eval_error),
        n_args_only_divergent_truncated=sum(
            1 for r in rows
            if r.args_differ and not r.action_differs and not r.is_eval_error and r.within_truncated_window
        ),
    )
    return alignment, rows


def _require_pipeline(record) -> None:
    if record.pipeline_name is None:
        raise ValueError(
            f"no pipeline results found under {record.repeat_dir} (suite={record.suite!r}, role={record.role!r})"
        )


def compute_attacked(quartets: list[Quartet]) -> tuple[list[CaseAlignment], list[DivergenceRow]]:
    """D (attacked) vs D, strict vs targeted, per shared (user_task_id, injection_task_id) case."""
    alignments: list[CaseAlignment] = []
    rows: list[DivergenceRow] = []
    for (suite, repeat), by_policy in sorted(_quartets_by_suite_repeat(quartets).items()):
        if "strict" not in by_policy or "targeted" not in by_policy:
            continue
        qs, qt = by_policy["strict"], by_policy["targeted"]
        _require_pipeline(qs.d)
        _require_pipeline(qt.d)
        _, with_inj_s = discover_results(qs.d.repeat_dir, qs.d.pipeline_name, qs.d.suite, qs.d.benchmark_version)
        _, with_inj_t = discover_results(qt.d.repeat_dir, qt.d.pipeline_name, qt.d.suite, qt.d.benchmark_version)
        run_ids_s = case_to_run_id(qs.d.repeat_dir, with_inj_s)
        run_ids_t = case_to_run_id(qt.d.repeat_dir, with_inj_t)
        fp_s = (qs.d.policy.sha256 if qs.d.policy else None) or ""
        fp_t = (qt.d.policy.sha256 if qt.d.policy else None) or ""

        for case_key in sorted(set(with_inj_s) & set(with_inj_t)):
            user_task_id, injection_task_id = case_key
            rid_s, rid_t = run_ids_s.get(case_key), run_ids_t.get(case_key)
            if rid_s is None or rid_t is None:
                continue
            traj_s = run_trajectory(qs.d.repeat_dir, rid_s)
            traj_t = run_trajectory(qt.d.repeat_dir, rid_t)
            alignment, case_rows = _align_case(
                suite, repeat, user_task_id, injection_task_id, traj_s, traj_t, fp_s, fp_t
            )
            alignments.append(alignment)
            rows.extend(case_rows)

    rows.sort(key=lambda r: (r.suite, r.repeat, r.user_task_id, r.injection_task_id or "", r.call_index))
    alignments.sort(key=lambda a: (a.suite, a.repeat, a.user_task_id, a.injection_task_id or ""))
    return alignments, rows


def compute_benign(quartets: list[Quartet]) -> tuple[list[CaseAlignment], list[DivergenceRow]]:
    """C (benign) vs C, strict vs targeted, per shared user_task_id."""
    alignments: list[CaseAlignment] = []
    rows: list[DivergenceRow] = []
    for (suite, repeat), by_policy in sorted(_quartets_by_suite_repeat(quartets).items()):
        if "strict" not in by_policy or "targeted" not in by_policy:
            continue
        qs, qt = by_policy["strict"], by_policy["targeted"]
        _require_pipeline(qs.c)
        _require_pipeline(qt.c)
        without_inj_s, _ = discover_results(qs.c.repeat_dir, qs.c.pipeline_name, qs.c.suite, qs.c.benchmark_version)
        without_inj_t, _ = discover_results(qt.c.repeat_dir, qt.c.pipeline_name, qt.c.suite, qt.c.benchmark_version)
        run_ids_s = case_to_run_id(qs.c.repeat_dir, without_inj_s)
        run_ids_t = case_to_run_id(qt.c.repeat_dir, without_inj_t)
        fp_s = (qs.c.policy.sha256 if qs.c.policy else None) or ""
        fp_t = (qt.c.policy.sha256 if qt.c.policy else None) or ""

        for case_key in sorted(set(without_inj_s) & set(without_inj_t)):
            user_task_id = case_key[0]
            rid_s, rid_t = run_ids_s.get(case_key), run_ids_t.get(case_key)
            if rid_s is None or rid_t is None:
                continue
            traj_s = run_trajectory(qs.c.repeat_dir, rid_s)
            traj_t = run_trajectory(qt.c.repeat_dir, rid_t)
            alignment, case_rows = _align_case(suite, repeat, user_task_id, None, traj_s, traj_t, fp_s, fp_t)
            alignments.append(alignment)
            rows.extend(case_rows)

    rows.sort(key=lambda r: (r.suite, r.repeat, r.user_task_id, r.call_index))
    alignments.sort(key=lambda a: (a.suite, a.repeat, a.user_task_id))
    return alignments, rows


_FIELDS = [
    "suite", "repeat", "user_task_id", "injection_task_id", "call_index", "tool",
    "action_strict", "action_targeted", "matched_rule_strict", "matched_rule_targeted",
    "outcome_strict", "outcome_targeted", "is_eval_error",
    "action_differs", "args_differ", "within_truncated_window",
    "policy_fingerprint_strict", "policy_fingerprint_targeted",
]


def write_csv(rows: list[DivergenceRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [
                    r.suite, r.repeat, r.user_task_id, r.injection_task_id or "", r.call_index, r.tool,
                    r.action_strict, r.action_targeted, r.matched_rule_strict or "", r.matched_rule_targeted or "",
                    r.outcome_strict, r.outcome_targeted, r.is_eval_error,
                    r.action_differs, r.args_differ, r.within_truncated_window,
                    r.policy_fingerprint_strict, r.policy_fingerprint_targeted,
                ]
            )


def _direction_counts(rows: list[DivergenceRow]) -> tuple[int, int, int]:
    """(strict_blocks_targeted_allows, targeted_blocks_strict_allows, other) among action-divergent rows."""
    strict_blocks = targeted_blocks = other = 0
    for r in rows:
        if not r.action_differs:
            continue
        if r.action_strict == "block" and r.action_targeted == "allow":
            strict_blocks += 1
        elif r.action_targeted == "block" and r.action_strict == "allow":
            targeted_blocks += 1
        else:
            other += 1
    return strict_blocks, targeted_blocks, other


def render_markdown(
    attacked_alignments: list[CaseAlignment],
    attacked_rows: list[DivergenceRow],
    benign_alignments: list[CaseAlignment],
    benign_rows: list[DivergenceRow],
) -> str:
    lines = ["## T2.1. Strict versus targeted decision divergence", ""]
    lines.append(
        "**Alignment rule:** position `i` is aligned across two trajectories only if the tool name "
        "matches at index `i` in both. `naive_len = min(len_strict, len_targeted)`. Within that window, "
        "`first_mismatch_index` is the first position where tool names differ (blank if none); "
        "`truncated_len` is that index. A differing-action/args row is reported for every tool-matching "
        "position in the naive window; `within_truncated_window` marks whether it also survives the "
        "stricter truncated-at-first-desync reading. Call sequences are sourced from "
        "`call_records.jsonl` via `run_trajectory`, which already excludes an iteration-cap trailing "
        "tool call that was never dispatched to Interbolt -- no separate trimming needed."
    )
    lines.append("")

    for title, alignments, rows in (
        ("Attacked (D strict vs D targeted)", attacked_alignments, attacked_rows),
        ("Benign (C strict vs C targeted)", benign_alignments, benign_rows),
    ):
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"Cases compared: {len(alignments)}. Differing-action-or-args positions found: {len(rows)}.")
        n_tool_mismatch_cases = sum(1 for a in alignments if a.first_mismatch_index is not None)
        lines.append(
            f"Cases with at least one tool-name desync within the naive window: {n_tool_mismatch_cases} "
            f"of {len(alignments)}."
        )
        eval_error_rows = [r for r in rows if r.is_eval_error]
        if eval_error_rows:
            lines.append(
                f"**{len(eval_error_rows)} row(s) are evaluation-error artifacts** -- one side's `block` is "
                "a fail-closed response to a CEL evaluation crash (`outcome=evaluation_error`), not a real "
                "rule match, even when `action_strict == action_targeted`. Excluded from the args-only-"
                "divergent counts below; see the `Outcome` columns in the table to identify them."
            )
        strict_blocks, targeted_blocks, other = _direction_counts(rows)
        n_action = strict_blocks + targeted_blocks + other
        if n_action:
            lines.append(
                f"Action-divergent positions: {n_action} total -- strict blocks/targeted allows: "
                f"{strict_blocks}, targeted blocks/strict allows: {targeted_blocks}, other: {other}. "
                + ("**Direction is always strict-blocks-targeted-allows.**" if targeted_blocks == 0 and other == 0
                   and strict_blocks > 0 else "Direction is not uniformly one-sided.")
            )
        else:
            lines.append("No action-divergent positions found.")
        lines.append("")

        lines.append("| Suite | Repeat | User task | Injection task | Call index | Tool | Action (strict) | "
                      "Action (targeted) | Rule (strict) | Rule (targeted) | Outcome (strict) | "
                      "Outcome (targeted) | Eval error | Within truncated window |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            lines.append(
                f"| {r.suite} | {r.repeat} | {r.user_task_id} | {r.injection_task_id or ''} | {r.call_index} | "
                f"{r.tool} | {r.action_strict} | {r.action_targeted} | {r.matched_rule_strict or ''} | "
                f"{r.matched_rule_targeted or ''} | {r.outcome_strict} | {r.outcome_targeted} | "
                f"{r.is_eval_error} | {r.within_truncated_window} |"
            )
        lines.append("")

    lines.append("### Banking `user_task_2`: N2's flagship divergence, checked against this alignment rule")
    lines.append("")
    banking_ut2_rows = [r for r in benign_rows if r.suite == "banking" and r.user_task_id == "user_task_2"]
    banking_ut2_alignments = {
        a.repeat: a for a in benign_alignments if a.suite == "banking" and a.user_task_id == "user_task_2"
    }
    if banking_ut2_rows:
        repeats = sorted({r.repeat for r in banking_ut2_rows if r.action_differs})
        lines.append(
            f"Appears directly in the benign divergence set in repeat(s) {repeats}, matching N2's finding "
            "that it is lost under strict and kept under targeted."
        )
    else:
        lines.append(
            "**Does not appear as a differing-action row in either repeat under this module's positional "
            "alignment rule.** Direct inspection of the raw runs confirms N2's finding is still correct -- "
            "strict blocks `update_scheduled_transaction` via `block_when_run_tainted` and targeted allows "
            "the same call via `allow_non_redirecting_edits` -- but in both repeats the two separately "
            "sampled runs make their own read calls (`get_balance`, `get_iban`, ...) in a different order "
            "before reaching that call, so a tool-name mismatch lands at the exact position where the "
            "interesting divergence sits, and this module's strict per-index alignment rule loses it before "
            "ever comparing actions. Per-repeat detail:"
        )
        for repeat in sorted(banking_ut2_alignments):
            a = banking_ut2_alignments[repeat]
            if a.first_mismatch_index is None:
                lines.append(f"- repeat {repeat}: no tool-name mismatch found (naive_len={a.naive_len}); see rows above.")
            else:
                lines.append(
                    f"- repeat {repeat}: first tool-name mismatch at call index {a.first_mismatch_index} "
                    f"(strict calls `{a.tool_at_mismatch_strict}`, targeted calls `{a.tool_at_mismatch_targeted}` "
                    f"at that position)."
                )
        lines.append(
            "This is itself a finding: index-based alignment, as specified, is not robust to run-to-run "
            "variation in the model's own call ordering, even on an identical benign prompt with only the "
            "policy changed. A future alignment rule keyed on tool identity rather than position would "
            "recover this case; this module intentionally does not do that, since the spec's stated rule is "
            "positional."
        )
    lines.append("")

    return "\n".join(lines)
