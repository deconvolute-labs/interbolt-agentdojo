"""Tier 3, N5: decision determinism.

Groups every decision by (sink, serialized arguments, untrusted source set); within a group,
action and matched rule must be constant.

**Substitution, stated up front because it changes what "untrusted source set" means here:**
checked every `interbolt_events.jsonl` record published under `runs/published/` (12,843 events,
both suites, every role) -- `decision.contributing_labels`, `decision.trifecta`,
`decision.untrusted_sources`, and the top-level `sources` field are `[]` in 100% of them, as is
`call_records.jsonl`'s `label_lineages`. Schema version 9 doesn't populate them. The only
taint-related signal actually present is the boolean `run_tainted`. For these four policies this
is a faithful substitute, not a shortcut: every non-default rule in
`policies/{banking,travel}/{strict,targeted}.yaml` branches on `run.tainted` or argument
presence, never on a label/source field -- `run_tainted` *is* the full untrusted-source signal
these policies act on. The group key here is therefore `(sink, json.dumps(args, sort_keys=True),
run_tainted)`.

CS12 (travel targeted repeat 1, malformed `send_email` args) raises a CEL evaluation error, so
Interbolt fails closed with `action="block"` but `matched_rule=None`. Comparing a `None` rule
against a real rule name for the same key would misreport that as non-determinism, so
`matched_rule` consistency is checked only among non-eval-error decisions in a group;
`n_eval_error_decisions` is reported per group (and named explicitly in the markdown) instead of
being silently folded into a rule-consistency verdict.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from analysis.common.artifacts import CallDecision, discover_results, run_trajectory, selected_run_ids
from analysis.common.casetables import Quartet
from analysis.common.discovery import RunRecord


@dataclass(frozen=True)
class GroupRow:
    suite: str
    policy: str
    sink: str
    args_json: str
    run_tainted: bool
    n_decisions: int
    n_eval_error_decisions: int
    action_consistent: bool
    matched_rule_consistent: bool
    actions: str  # sorted, "|"-joined distinct actions seen
    matched_rules: str  # sorted, "|"-joined distinct non-null matched rules among non-eval-error decisions
    policy_fingerprint: str


def _all_call_decisions(record: RunRecord) -> list[CallDecision]:
    """Every CallDecision (tool + args + action + matched_rule + outcome + run_tainted) across
    every scored case in one C or D run, flattened -- reuses `selected_run_ids` for the same
    retry-dedup rule Phase 1's I7 and `policy_coverage._selected_events` already use, and
    `run_trajectory` for the already-verified call/decision alignment."""
    if record.pipeline_name is None:
        return []
    without_inj, with_inj = discover_results(record.repeat_dir, record.pipeline_name, record.suite, record.benchmark_version)
    selected = selected_run_ids(record.repeat_dir, without_inj, with_inj)
    decisions: list[CallDecision] = []
    for run_id in selected:
        decisions.extend(run_trajectory(record.repeat_dir, run_id))
    return decisions


def compute_rows(quartets: list[Quartet]) -> list[GroupRow]:
    """Grouped per (suite, policy), combining both repeats' C and D runs -- determinism is a
    claim about the policy engine itself, not about any single repeat, so pooling repeats gives
    the grouping more chances to catch a real violation (the same (sink, args, tainted) triple
    recurring across separately-sampled runs)."""
    by_suite_policy: dict[tuple[str, str], list[Quartet]] = {}
    for q in quartets:
        by_suite_policy.setdefault((q.suite, q.policy), []).append(q)

    rows: list[GroupRow] = []
    for (suite, policy), qs in sorted(by_suite_policy.items()):
        decisions: list[CallDecision] = []
        for q in qs:
            decisions += _all_call_decisions(q.c) + _all_call_decisions(q.d)
        policy_fingerprint = (qs[0].d.policy.sha256 if qs[0].d.policy else None) or ""

        groups: dict[tuple[str, str, bool], list[CallDecision]] = {}
        for cd in decisions:
            key = (cd.tool, json.dumps(cd.args, sort_keys=True), cd.run_tainted)
            groups.setdefault(key, []).append(cd)

        for (sink, args_json, tainted), group in sorted(groups.items()):
            clean = [cd for cd in group if cd.outcome != "evaluation_error"]
            eval_error = [cd for cd in group if cd.outcome == "evaluation_error"]
            actions = sorted({cd.action for cd in group})
            clean_rules = sorted({cd.matched_rule for cd in clean if cd.matched_rule is not None})
            rows.append(
                GroupRow(
                    suite=suite,
                    policy=policy,
                    sink=sink,
                    args_json=args_json,
                    run_tainted=tainted,
                    n_decisions=len(group),
                    n_eval_error_decisions=len(eval_error),
                    action_consistent=len(actions) <= 1,
                    matched_rule_consistent=len(clean_rules) <= 1,
                    actions="|".join(actions),
                    matched_rules="|".join(clean_rules),
                    policy_fingerprint=policy_fingerprint,
                )
            )

    rows.sort(key=lambda r: (r.suite, r.policy, r.sink, r.args_json, r.run_tainted))
    return rows


_FIELDS = [
    "suite", "policy", "sink", "args_json", "run_tainted", "n_decisions", "n_eval_error_decisions",
    "action_consistent", "matched_rule_consistent", "actions", "matched_rules", "policy_fingerprint",
]


def write_csv(rows: list[GroupRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [
                    r.suite, r.policy, r.sink, r.args_json, r.run_tainted, r.n_decisions, r.n_eval_error_decisions,
                    r.action_consistent, r.matched_rule_consistent, r.actions, r.matched_rules, r.policy_fingerprint,
                ]
            )


def render_markdown(rows: list[GroupRow]) -> str:
    lines = ["## N5. Decision determinism", ""]
    lines.append(
        "Grouped by `(sink, serialized args, run_tainted)` -- see the module docstring for why "
        "`run_tainted` stands in for \"untrusted source set\" (the label/source fields the spec "
        "names are unpopulated in every published event). Within a group, `action` must be "
        "constant across every decision, and `matched_rule` must be constant among non-eval-error "
        "decisions (an evaluation-error decision's `matched_rule=None` is not compared, so CS12's "
        "group can't be misread as non-determinism)."
    )
    lines.append("")

    n_groups = len(rows)
    action_violations = [r for r in rows if not r.action_consistent]
    rule_violations = [r for r in rows if not r.matched_rule_consistent]
    eval_error_groups = [r for r in rows if r.n_eval_error_decisions > 0]

    lines.append(f"Groups: {n_groups}. Action violations: {len(action_violations)}. "
                 f"Matched-rule violations: {len(rule_violations)}. "
                 f"Groups containing an evaluation-error decision: {len(eval_error_groups)}.")
    lines.append("")

    if eval_error_groups:
        lines.append("### Groups containing an evaluation-error decision (handled explicitly, not compared for rule consistency)")
        lines.append("")
        lines.append("| Suite | Policy | Sink | Run tainted | n decisions | n eval errors | Actions | Matched rules (clean) |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in eval_error_groups:
            lines.append(
                f"| {r.suite} | {r.policy} | {r.sink} | {r.run_tainted} | {r.n_decisions} | "
                f"{r.n_eval_error_decisions} | {r.actions} | {r.matched_rules or '(none)'} |"
            )
        lines.append("")

    if action_violations or rule_violations:
        lines.append("### Violations")
        lines.append("")
        lines.append("| Suite | Policy | Sink | Args | Run tainted | Actions | Matched rules |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in action_violations + [r for r in rule_violations if r not in action_violations]:
            lines.append(
                f"| {r.suite} | {r.policy} | {r.sink} | `{r.args_json}` | {r.run_tainted} | "
                f"{r.actions} | {r.matched_rules} |"
            )
        lines.append("")
    else:
        lines.append(
            "No violations: every group's action is constant, and every group's matched rule is "
            "constant among its non-eval-error decisions."
        )
        lines.append("")

    return "\n".join(lines)
