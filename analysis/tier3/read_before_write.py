"""Tier 3, 2.5: read-before-write.

For every C/D case with at least one blocked call to a state-changing sink, confirm at least one
read-only call preceded the first such block in that run's trajectory. A genuine behavioral
confirmation, not a structurally-guaranteed-to-pass check -- a real violation (a blocked
state-changing call as the very first call in the trajectory) would surface here.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from interbolt_agentdojo.namespaces import resolve_namespace

from analysis.common.artifacts import discover_results, run_trajectory, selected_run_ids
from analysis.common.discovery import ROLE_C_UTILITY, ROLE_D_ASR_SYSTEM, RunRecord
from analysis.tier3.positional_distributions import run_id_to_case
from analysis.tier3.suite_metadata import STATE_CHANGING_TOOLS


@dataclass(frozen=True)
class ReadBeforeWriteRow:
    suite: str
    role: str
    policy: str
    repeat_dir: str
    user_task_id: str | None
    injection_task_id: str | None
    applicable: bool  # False: no blocked state-changing call in this case, nothing to check
    read_preceded_first_block: bool | None  # None when not applicable
    first_block_index: int | None
    n_reads_before: int


def compute_rows(records: list[RunRecord]) -> list[ReadBeforeWriteRow]:
    rows: list[ReadBeforeWriteRow] = []
    for record in records:
        if record.role not in (ROLE_C_UTILITY, ROLE_D_ASR_SYSTEM):
            continue
        state_changing = {
            f"{resolve_namespace(record.suite, t)}.{t}" for t in STATE_CHANGING_TOOLS.get(record.suite, frozenset())
        }
        selected, inv = run_id_to_case(record)
        policy_name = record.policy.name if record.policy else "none"
        for run_id in selected:
            traj = run_trajectory(record.repeat_dir, run_id)
            first_block = next(
                (i for i, cd in enumerate(traj) if cd.action == "block" and cd.tool in state_changing), None
            )
            user_task_id, injection_task_id = inv.get(run_id, (None, None))
            if first_block is None:
                rows.append(
                    ReadBeforeWriteRow(
                        suite=record.suite, role=record.role, policy=policy_name, repeat_dir=record.repeat_dir.name,
                        user_task_id=user_task_id, injection_task_id=injection_task_id,
                        applicable=False, read_preceded_first_block=None, first_block_index=None, n_reads_before=0,
                    )
                )
                continue
            reads_before = sum(1 for cd in traj[:first_block] if cd.tool not in state_changing)
            rows.append(
                ReadBeforeWriteRow(
                    suite=record.suite, role=record.role, policy=policy_name, repeat_dir=record.repeat_dir.name,
                    user_task_id=user_task_id, injection_task_id=injection_task_id,
                    applicable=True, read_preceded_first_block=reads_before > 0,
                    first_block_index=first_block, n_reads_before=reads_before,
                )
            )
    rows.sort(key=lambda r: (r.suite, r.role, r.policy, r.repeat_dir, r.user_task_id or "", r.injection_task_id or ""))
    return rows


_FIELDS = ["suite", "role", "policy", "repeat_dir", "user_task_id", "injection_task_id",
           "applicable", "read_preceded_first_block", "first_block_index", "n_reads_before"]


def write_csv(rows: list[ReadBeforeWriteRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [
                    r.suite, r.role, r.policy, r.repeat_dir, r.user_task_id or "", r.injection_task_id or "",
                    r.applicable, r.read_preceded_first_block if r.read_preceded_first_block is not None else "",
                    r.first_block_index if r.first_block_index is not None else "", r.n_reads_before,
                ]
            )


def render_markdown(rows: list[ReadBeforeWriteRow]) -> str:
    lines = ["## 2.5. Read-before-write", ""]
    lines.append(
        "For every C/D case with a blocked state-changing call, confirm at least one read-only "
        "call preceded the first such block."
    )
    lines.append("")

    applicable = [r for r in rows if r.applicable]
    violations = [r for r in applicable if not r.read_preceded_first_block]
    lines.append(
        f"Applicable cases (at least one blocked state-changing call): {len(applicable)} of {len(rows)}. "
        f"Violations (block with no preceding read): {len(violations)}."
    )
    lines.append("")

    if violations:
        lines.append("### Violations")
        lines.append("")
        lines.append("| Suite | Role | Policy | Repeat | User task | Injection task | First block index |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in violations:
            lines.append(
                f"| {r.suite} | {r.role} | {r.policy} | {r.repeat_dir} | {r.user_task_id} | "
                f"{r.injection_task_id or ''} | {r.first_block_index} |"
            )
        lines.append("")
    else:
        lines.append("No violations: every applicable case's first blocked state-changing call was preceded by at least one read.")
        lines.append("")

    return "\n".join(lines)
