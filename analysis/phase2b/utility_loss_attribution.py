"""Phase 2B, N2: utility loss attribution.

Retention conflates tasks lost to a block with tasks lost to model variance. For
each benign task, per repeat, classified from `BenignTaskRow` (utility_a, utility_c,
n_blocks -- the C-run block count):

- Passed in A, failed in C, at least one block in C -> policy_caused_loss
- Passed in A, failed in C, no block in C -> run_variance (not attributable)
- Failed in A, passed in C -> reverse_variance (or an over-block artifact)
- Passed in both, at least one block in C -> blocked_but_recovered (see N9)
- Failed in both -> model_limitation
- Passed in both, no block in C -> unaffected (the spec's five bullets don't name
  this uninteresting sixth case, but every row must classify to something -- see
  Phase 5's "never silently drop a case").
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from analysis.common.casetables import BenignTaskRow

_CATEGORIES = (
    "policy_caused_loss", "run_variance", "reverse_variance",
    "blocked_but_recovered", "model_limitation", "unaffected",
)


@dataclass(frozen=True)
class UtilityLossRow:
    suite: str
    policy: str
    repeat: int
    user_task_id: str
    utility_a: bool
    utility_c: bool
    n_blocks: int
    category: str
    policy_fingerprint: str


def classify(row: BenignTaskRow) -> str:
    if row.utility_a and not row.utility_c:
        return "policy_caused_loss" if row.n_blocks else "run_variance"
    if not row.utility_a and row.utility_c:
        return "reverse_variance"
    if row.utility_a and row.utility_c:
        return "blocked_but_recovered" if row.n_blocks else "unaffected"
    return "model_limitation"  # not utility_a and not utility_c


def compute_rows(benign: list[BenignTaskRow]) -> list[UtilityLossRow]:
    rows = [
        UtilityLossRow(
            suite=b.suite,
            policy=b.policy,
            repeat=b.repeat,
            user_task_id=b.user_task_id,
            utility_a=b.utility_a,
            utility_c=b.utility_c,
            n_blocks=b.n_blocks,
            category=classify(b),
            policy_fingerprint=b.policy_fingerprint,
        )
        for b in benign
    ]
    rows.sort(key=lambda r: (r.suite, r.policy, r.repeat, r.user_task_id))
    return rows


_FIELDS = ["suite", "policy", "repeat", "user_task_id", "utility_a", "utility_c", "n_blocks", "category", "policy_fingerprint"]


def write_csv(rows: list[UtilityLossRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [r.suite, r.policy, r.repeat, r.user_task_id, r.utility_a, r.utility_c, r.n_blocks, r.category, r.policy_fingerprint]
            )


def render_markdown(rows: list[UtilityLossRow]) -> str:
    lines = ["## N2. Utility loss attribution", ""]
    lines.append(
        "Every benign task classified into one of six categories from `utility_a`/`utility_c`/"
        "`n_blocks` (the C-run block count for that task). `policy_caused_loss` and "
        "`run_variance` are the two that matter for retention's honesty; the rest are reported "
        "so no task is silently unclassified."
    )
    lines.append("")

    rollup: dict[tuple[str, str, int], dict[str, int]] = {}
    for r in rows:
        key = (r.suite, r.policy, r.repeat)
        rollup.setdefault(key, dict.fromkeys(_CATEGORIES, 0))
        rollup[key][r.category] += 1

    lines.append("| Suite | Policy | Repeat | " + " | ".join(_CATEGORIES) + " |")
    lines.append("|---|---|---|" + "---|" * len(_CATEGORIES))
    for (suite, policy, repeat), counts in sorted(rollup.items()):
        lines.append(f"| {suite} | {policy} | {repeat} | " + " | ".join(str(counts[c]) for c in _CATEGORIES) + " |")
    lines.append("")

    lines.append("### Named losses (`policy_caused_loss` and `run_variance`)")
    lines.append("")
    lines.append("| Suite | Policy | Repeat | User task | Category |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        if r.category in ("policy_caused_loss", "run_variance"):
            lines.append(f"| {r.suite} | {r.policy} | {r.repeat} | {r.user_task_id} | {r.category} |")
    lines.append("")

    return "\n".join(lines)
