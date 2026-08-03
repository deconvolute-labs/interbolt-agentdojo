"""Tier 2, T2.5: named variance cases.

`analysis.phase2b.utility_loss_attribution` already classifies every benign task into six
categories from `utility_a`/`utility_c`/`n_blocks`. This surfaces the two categories the spec
calls out as not yet named individually:

- `reverse_variance` -- the flip side of N2's variance argument (tasks that failed undefended and
  passed with the policy on); belongs in Limits alongside `run_variance`.
- `blocked_but_recovered` -- for each, which sink(s) got blocked and which state-changing tools
  were subsequently called and allowed. These are mechanical facts read from the case's C-run
  trajectory; the qualitative "what did the agent do instead" narrative is for the write-up, not
  generated prose here. "State-changing" is derived from that case's own policy YAML: a sink
  counts as state-changing if it has any declared rule besides `default` (the convention both
  `strict.yaml` and `targeted.yaml` use -- every read-only sink in these policies has only a bare
  `default: allow` rule).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from interbolt import Policy

from analysis.common.artifacts import case_to_run_id, discover_results, run_trajectory
from analysis.common.casetables import BenignTaskRow, Quartet
from analysis.phase2b.utility_loss_attribution import compute_rows as compute_loss_rows

_NAMED_CATEGORIES = ("reverse_variance", "blocked_but_recovered")


@dataclass(frozen=True)
class NamedVarianceRow:
    suite: str
    policy: str
    repeat: int
    user_task_id: str
    category: str
    blocked_sinks: str  # "|"-joined, sorted; "" if none
    subsequent_state_changing_calls: str  # "|"-joined, trajectory order; "" if none
    policy_fingerprint: str


def _state_changing_sinks(resolved_policy_path: Path) -> set[str]:
    document = Policy.from_file(str(resolved_policy_path)).document
    return {sink for sink, rules in document.sinks.items() if any(r.name != "default" for r in rules)}


def compute_rows(quartets: list[Quartet], benign: list[BenignTaskRow]) -> list[NamedVarianceRow]:
    loss_rows = compute_loss_rows(benign)
    q_by_key = {(q.suite, q.policy, q.repeat): q for q in quartets}
    state_changing_cache: dict[Path, set[str]] = {}

    rows: list[NamedVarianceRow] = []
    for lr in loss_rows:
        if lr.category not in _NAMED_CATEGORIES:
            continue
        blocked_sinks = ""
        subsequent = ""
        if lr.category == "blocked_but_recovered":
            q = q_by_key.get((lr.suite, lr.policy, lr.repeat))
            if q is not None and q.c.pipeline_name is not None:
                without_inj, _ = discover_results(q.c.repeat_dir, q.c.pipeline_name, q.c.suite, q.c.benchmark_version)
                run_ids = case_to_run_id(q.c.repeat_dir, without_inj)
                run_id = run_ids.get((lr.user_task_id, None))
                if run_id is not None:
                    trajectory = run_trajectory(q.c.repeat_dir, run_id)
                    blocked_sinks = "|".join(sorted({cd.tool for cd in trajectory if cd.action == "block"}))
                    first_block_idx = next((i for i, cd in enumerate(trajectory) if cd.action == "block"), None)
                    if first_block_idx is not None and q.c.policy is not None and q.c.policy.resolved_path is not None:
                        if q.c.policy.resolved_path not in state_changing_cache:
                            state_changing_cache[q.c.policy.resolved_path] = _state_changing_sinks(q.c.policy.resolved_path)
                        state_changing = state_changing_cache[q.c.policy.resolved_path]
                        after = [
                            cd.tool for cd in trajectory[first_block_idx + 1:]
                            if cd.action == "allow" and cd.tool in state_changing
                        ]
                        subsequent = "|".join(after)
        rows.append(
            NamedVarianceRow(
                suite=lr.suite,
                policy=lr.policy,
                repeat=lr.repeat,
                user_task_id=lr.user_task_id,
                category=lr.category,
                blocked_sinks=blocked_sinks,
                subsequent_state_changing_calls=subsequent,
                policy_fingerprint=lr.policy_fingerprint,
            )
        )
    rows.sort(key=lambda r: (r.suite, r.policy, r.repeat, r.user_task_id))
    return rows


_FIELDS = ["suite", "policy", "repeat", "user_task_id", "category", "blocked_sinks",
           "subsequent_state_changing_calls", "policy_fingerprint"]


def write_csv(rows: list[NamedVarianceRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [r.suite, r.policy, r.repeat, r.user_task_id, r.category, r.blocked_sinks,
                 r.subsequent_state_changing_calls, r.policy_fingerprint]
            )


def render_markdown(rows: list[NamedVarianceRow]) -> str:
    lines = ["## T2.5. Named variance cases", ""]
    lines.append(
        "`reverse_variance` (failed undefended, passed with the policy on) and "
        "`blocked_but_recovered` (passed both, but at least one call was blocked along the way), "
        "named individually rather than left as a bare count."
    )
    lines.append("")

    for category in _NAMED_CATEGORIES:
        subset = [r for r in rows if r.category == category]
        lines.append(f"### {category} ({len(subset)})")
        lines.append("")
        if category == "blocked_but_recovered":
            lines.append("| Suite | Policy | Repeat | User task | Blocked sink(s) | Subsequent state-changing calls |")
            lines.append("|---|---|---|---|---|---|")
            for r in subset:
                lines.append(
                    f"| {r.suite} | {r.policy} | {r.repeat} | {r.user_task_id} | {r.blocked_sinks or '(none)'} | "
                    f"{r.subsequent_state_changing_calls or '(none)'} |"
                )
        else:
            lines.append("| Suite | Policy | Repeat | User task |")
            lines.append("|---|---|---|---|")
            for r in subset:
                lines.append(f"| {r.suite} | {r.policy} | {r.repeat} | {r.user_task_id} |")
        lines.append("")

    return "\n".join(lines)
