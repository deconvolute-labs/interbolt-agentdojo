"""Tier 2, T2.3: policy surface coverage.

Per (suite, policy, repeat): declared sinks versus sinks that received at least one decision;
declared (sink, rule) pairs versus pairs that matched at least once; distinct sinks the attacks
targeted versus total gated sinks. **Declared** always comes from the policy YAML
(`interbolt.Policy.from_file(...).document`), never from observed events -- a rule that never
fires still gets a zero row, so "declared and never matched" stays distinguishable from "not part
of this policy."

Rule coverage is keyed by **(sink, rule name)**, not rule name alone. The same rule name (e.g.
`block_when_run_tainted`) is deliberately reused across several sinks in these policies (banking
strict declares it on `send_money`, `schedule_transaction`, `update_scheduled_transaction`,
`update_password`, and `update_user_info`) -- a flat-by-name key would let one sink's firing mark
the name "matched" for every other sink that shares it, hiding a real gap (e.g. the rule never
firing for `update_password` specifically). This is deliberately *unlike* `compute_results.py`'s
own `rule__*__*` CSV columns, which stay flat by name there for a different purpose (aggregate
block-count reporting across a whole run, where sink identity isn't the question being asked);
that flat convention is out of scope here and is not what this module follows.

I8 found banking's security claim rests on 85 of 144 distinct cases and travel's on 41 of 140 --
this module reports which specific sinks those cases actually reached (the injection task's own
target tools, intersected with what the B run actually called), so "no policy gap" claims are
visibly scoped to a named, possibly narrow, set rather than left for a reader to work out.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suite
from interbolt import Action, Policy
from interbolt_agentdojo.executor import NAMESPACE

from analysis.common.artifacts import (
    discover_results,
    events_by_run_id,
    load_call_records,
    selected_run_ids,
    target_tools,
)
from analysis.common.casetables import AttackedCaseRow, Quartet
from analysis.common.discovery import RunRecord
from analysis.tier2.shared_sinks import attack_target_sinks

_GATED_SUCCESS_BUCKETS = frozenset({"interbolt_blocked", "attack_succeeded_defended", "attack_failed_unattributed"})


@dataclass(frozen=True)
class CoverageRow:
    suite: str
    policy: str
    repeat: int
    item_type: str  # "sink" | "rule"
    sink: str  # mirrors item_name for item_type="sink"; owning sink for item_type="rule"
    item_name: str
    declared: bool
    n_decisions_observed: int
    matched_at_least_once: bool
    policy_fingerprint: str


def _selected_events(record: RunRecord) -> list[dict]:
    """Every interbolt_events.jsonl entry for `record`, deduplicated to AgentDojo's scored
    (last) attempt per case -- same dedup rule Phase 1's I7 uses (`_selected_events_count`),
    but returning the events themselves rather than a bare count."""
    if record.pipeline_name is None:
        return []
    without_inj, with_inj = discover_results(record.repeat_dir, record.pipeline_name, record.suite, record.benchmark_version)
    selected = selected_run_ids(record.repeat_dir, without_inj, with_inj)
    return [e for run_id, evs in events_by_run_id(record.repeat_dir).items() if run_id in selected for e in evs]


def _gated_case_sinks(quartets: list[Quartet], attacked: list[AttackedCaseRow]) -> dict[tuple[str, str], set[str]]:
    """(suite, policy) -> qualified target-sink names actually reached by that policy's
    gated-success-bucket cases (interbolt_blocked / attack_succeeded_defended /
    attack_failed_unattributed), unioned across repeats -- I8's denominator, named."""
    b_by_suite_repeat = {(q.suite, q.repeat): q.b for q in quartets}
    call_records_cache: dict[Path, dict] = {}
    suite_obj_cache: dict[str, object] = {}
    result: dict[tuple[str, str], set[str]] = {}

    for r in attacked:
        if r.bucket not in _GATED_SUCCESS_BUCKETS or r.run_id_b is None:
            continue
        b_record = b_by_suite_repeat.get((r.suite, r.repeat))
        if b_record is None or b_record.pipeline_name is None:
            continue
        if r.suite not in suite_obj_cache:
            suite_obj_cache[r.suite] = get_suite(b_record.benchmark_version, r.suite)
        qualified_targets = {f"{NAMESPACE}.{t}" for t in target_tools(suite_obj_cache[r.suite], r.injection_task_id)}
        if b_record.repeat_dir not in call_records_cache:
            call_records_cache[b_record.repeat_dir] = load_call_records(b_record.repeat_dir)
        called = {c["tool"] for c in call_records_cache[b_record.repeat_dir].get(r.run_id_b, [])}
        result.setdefault((r.suite, r.policy), set()).update(qualified_targets & called)
    return result


def compute_rows(
    quartets: list[Quartet], attacked: list[AttackedCaseRow]
) -> tuple[list[CoverageRow], list[str], dict[tuple[str, str, int], int]]:
    """Returns (rows, warnings, eval_error_counts). A warning is emitted (never silently
    dropped) whenever an observed sink or (sink, rule) pair isn't in that policy's own declared
    set -- that would mean an event references something outside the policy YAML this module
    loaded, which should never happen. A `null` `matched_rule` (Interbolt failing closed on a CEL
    evaluation error, e.g. CS12's malformed `send_email` args) is not a rule name at all, so it
    is excluded from `rule_counts` rather than coerced into a fake `"(none)"` key -- counted
    instead in `eval_error_counts`, per (suite, policy, repeat), so the fact isn't silently lost."""
    rows: list[CoverageRow] = []
    warnings: list[str] = []
    eval_error_counts: dict[tuple[str, str, int], int] = {}

    for q in quartets:
        if q.d.policy is None or q.d.policy.resolved_path is None:
            warnings.append(f"suite={q.suite} policy={q.policy} repeat={q.repeat}: no resolvable policy file, skipped")
            continue
        document = Policy.from_file(str(q.d.policy.resolved_path)).document
        declared_sinks = sorted(document.sinks.keys())
        # Keyed by (sink, rule name), not rule name alone -- see the module docstring: the same
        # rule name is deliberately reused across several sinks in these policies, and a flat key
        # would let one sink's firing hide another sink's copy of the same rule never firing.
        declared_sink_rules = sorted({(sink, rule.name) for sink, rules in document.sinks.items() for rule in rules})
        policy_fingerprint = q.d.policy.sha256 or ""

        events = _selected_events(q.c) + _selected_events(q.d)
        sink_counts: Counter = Counter(e["decision"]["tool"] for e in events)
        rule_counts: Counter = Counter(
            (e["decision"]["tool"], e["decision"]["matched_rule"]) for e in events if e["decision"].get("matched_rule")
        )
        n_eval_errors = sum(1 for e in events if not e["decision"].get("matched_rule"))
        if n_eval_errors:
            eval_error_counts[(q.suite, q.policy, q.repeat)] = n_eval_errors

        for sink in declared_sinks:
            n = sink_counts.get(sink, 0)
            rows.append(
                CoverageRow(q.suite, q.policy, q.repeat, "sink", sink, sink, True, n, n > 0, policy_fingerprint)
            )
        for sink, rule in declared_sink_rules:
            n = rule_counts.get((sink, rule), 0)
            rows.append(
                CoverageRow(q.suite, q.policy, q.repeat, "rule", sink, rule, True, n, n > 0, policy_fingerprint)
            )

        for sink, n in sink_counts.items():
            if sink not in declared_sinks:
                warnings.append(
                    f"suite={q.suite} policy={q.policy} repeat={q.repeat}: {n} decision(s) observed on "
                    f"undeclared sink {sink!r}"
                )
                rows.append(CoverageRow(q.suite, q.policy, q.repeat, "sink", sink, sink, False, n, True, policy_fingerprint))
        for (sink, rule), n in rule_counts.items():
            if (sink, rule) not in declared_sink_rules:
                warnings.append(
                    f"suite={q.suite} policy={q.policy} repeat={q.repeat}: {n} decision(s) matched "
                    f"undeclared rule {rule!r} on sink {sink!r}"
                )
                rows.append(CoverageRow(q.suite, q.policy, q.repeat, "rule", sink, rule, False, n, True, policy_fingerprint))

    rows.sort(key=lambda r: (r.suite, r.policy, r.repeat, r.item_type, r.sink, r.item_name))
    return rows, warnings, eval_error_counts


def _n_gated_sinks_by_policy(quartets: list[Quartet]) -> dict[tuple[str, str], int]:
    """(suite, policy) -> count of declared sinks with at least one action:block rule."""
    seen: dict[tuple[str, str], int] = {}
    for q in quartets:
        key = (q.suite, q.policy)
        if key in seen or q.d.policy is None or q.d.policy.resolved_path is None:
            continue
        document = Policy.from_file(str(q.d.policy.resolved_path)).document
        seen[key] = sum(1 for rules in document.sinks.values() if any(r.action is Action.BLOCK for r in rules))
    return seen


_FIELDS = ["suite", "policy", "repeat", "item_type", "sink", "item_name", "declared", "n_decisions_observed",
           "matched_at_least_once", "policy_fingerprint"]


def write_csv(rows: list[CoverageRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [r.suite, r.policy, r.repeat, r.item_type, r.sink, r.item_name, r.declared,
                 r.n_decisions_observed, r.matched_at_least_once, r.policy_fingerprint]
            )


def render_markdown(
    rows: list[CoverageRow],
    warnings: list[str],
    eval_error_counts: dict[tuple[str, str, int], int],
    quartets: list[Quartet],
    attacked: list[AttackedCaseRow],
    records: list[RunRecord],
) -> str:
    lines = ["## T2.3. Policy surface coverage", ""]
    lines.append(
        "Declared sinks/rules are read from each policy's own YAML (never from observed events), so "
        "an unfired rule still gets a zero row instead of being indistinguishable from \"not part of "
        "this policy.\" Rule rows are keyed by **(sink, rule name)**, not rule name alone: the same "
        "rule name (e.g. `block_when_run_tainted`) is deliberately reused across several sinks in "
        "these policies, and a flat-by-name key would let one sink's firing mark the name \"matched\" "
        "for every other sink sharing it, hiding a real gap on the sink that never actually fired it. "
        "(This is unlike `compute_results.py`'s own flat `rule__*__*` CSV columns, which serve a "
        "different, sink-agnostic aggregate-block-count purpose and are out of scope here.) A `null` "
        "`matched_rule` (Interbolt failing closed on a CEL evaluation error) is not a rule name and "
        "is excluded from the rule coverage below rather than reported as an observed-but-undeclared "
        "rule; see \"Evaluation errors\" further down instead."
    )
    lines.append("")

    if warnings:
        lines.append("**Warnings (observed decision referencing an undeclared sink/rule):**")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    else:
        lines.append("No observed decision referenced a sink or rule outside its policy's own declared set.")
        lines.append("")

    if eval_error_counts:
        lines.append("### Evaluation errors (`matched_rule=None`, excluded from rule coverage above)")
        lines.append("")
        lines.append("| Suite | Policy | Repeat | Decisions with no matched rule |")
        lines.append("|---|---|---|---|")
        for (suite, policy, repeat), n in sorted(eval_error_counts.items()):
            lines.append(f"| {suite} | {policy} | {repeat} | {n} |")
        lines.append("")

    lines.append("### Declared vs observed")
    lines.append("")
    lines.append("| Suite | Policy | Repeat | Type | Declared | Matched at least once | Never observed |")
    lines.append("|---|---|---|---|---|---|---|")
    by_key: dict[tuple[str, str, int, str], list[CoverageRow]] = {}
    for r in rows:
        by_key.setdefault((r.suite, r.policy, r.repeat, r.item_type), []).append(r)
    for (suite, policy, repeat, item_type), group in sorted(by_key.items()):
        declared_group = [r for r in group if r.declared]
        n_matched = sum(1 for r in declared_group if r.matched_at_least_once)
        n_never = sum(1 for r in declared_group if not r.matched_at_least_once)
        lines.append(
            f"| {suite} | {policy} | {repeat} | {item_type} | {len(declared_group)} | {n_matched} | {n_never} |"
        )
    lines.append("")

    lines.append("### Declared (sink, rule) pairs that never fired")
    lines.append("")
    lines.append(
        "The concrete answer to \"did this specific sink's copy of this rule ever fire\" -- not "
        "just an aggregate count. Empty rows mean every declared (sink, rule) pair fired at least "
        "once for that (suite, policy, repeat)."
    )
    lines.append("")
    never_fired = [r for r in rows if r.item_type == "rule" and r.declared and not r.matched_at_least_once]
    if never_fired:
        lines.append("| Suite | Policy | Repeat | Sink | Rule |")
        lines.append("|---|---|---|---|---|")
        for r in sorted(never_fired, key=lambda r: (r.suite, r.policy, r.repeat, r.sink, r.item_name)):
            lines.append(f"| {r.suite} | {r.policy} | {r.repeat} | {r.sink} | {r.item_name} |")
    else:
        lines.append("None -- every declared (sink, rule) pair fired at least once in this dataset.")
    lines.append("")

    lines.append("### Gated surface vs attack-targeted surface vs cases actually reaching a gated sink")
    lines.append("")
    lines.append(
        "\"Which sinks\" reuses I8/T2.2's `target_tools` definition (every tool in an injection "
        "task's own `ground_truth`), the same definition `gated_sink_cases.csv` already reaches its "
        "85/144 and 41/140 figures with -- it is not limited to state-changing sinks, so read-only "
        "setup calls that are part of an injection's ground truth (e.g. banking's "
        "`get_scheduled_transactions`) can appear here alongside genuinely gated ones. \"Gated sinks "
        "(declared)\" in the same row is the narrower, state-changing-only count for comparison."
    )
    lines.append("")
    n_gated = _n_gated_sinks_by_policy(quartets)
    targets_all = attack_target_sinks(records, exclude_unreachable=False)
    gated_case_sinks = _gated_case_sinks(quartets, attacked)
    policy_pairs = sorted({(q.suite, q.policy) for q in quartets})
    lines.append("| Suite | Policy | Gated sinks (declared) | Attack-targeted sinks (suite) | "
                 "Sinks actually reached by gated-success cases | Which sinks |")
    lines.append("|---|---|---|---|---|---|")
    for suite, policy in policy_pairs:
        gated = n_gated.get((suite, policy), 0)
        targets = len(targets_all.get(suite, set()))
        touched = sorted(gated_case_sinks.get((suite, policy), set()))
        lines.append(f"| {suite} | {policy} | {gated} | {targets} | {len(touched)} | {', '.join(touched) or '(none)'} |")
    lines.append("")

    return "\n".join(lines)
