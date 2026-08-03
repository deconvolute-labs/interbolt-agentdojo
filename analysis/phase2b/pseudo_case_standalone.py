"""Phase 2B, N14: are injection goals achievable as standalone tasks?

AgentDojo solves each injection task as an ordinary user task before scoring the attack,
purely as its own ground-truth check -- the result directory carries `user_task_id =
injection_task_N` with `injection_task_id` and `attack_type` both null. `_discover_results`
(`interbolt_agentdojo.compute_results`) deliberately excludes these from the benign bucket by
filtering directory names against the suite's real `user_tasks`; this module reads exactly the
files that filter discards, on purpose.

Read B (`allow_all`) runs only. In C and D the standalone check still executes through the
gated pipeline, so the policy blocks it and the goal fails regardless of whether the model
could perform it -- see `analysis/verification.md`'s Status section, correction 2. B enforces
nothing, so its result means what it should.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from analysis.common.artifacts import read_json
from analysis.common.casetables import refusal_counts_by_injection_task
from analysis.common.discovery import ROLE_B_ASR_MODEL, RunRecord


@dataclass(frozen=True)
class PseudoCaseRow:
    suite: str
    repeat: str
    injection_task_id: str
    achievable_standalone: bool | None  # None: pseudo-case JSON missing or `utility` null
    refused_count: int
    case_count: int

    @property
    def refusal_rate(self) -> float | None:
        return self.refused_count / self.case_count if self.case_count else None


def _pseudo_case_utilities(record: RunRecord) -> dict[str, bool | None]:
    """injection_task_id -> utility, from every `<repeat_dir>/<pipeline>/<suite>/injection_task_N/none/none.json` found."""
    result: dict[str, bool | None] = {}
    if record.pipeline_name is None:
        return result
    base = record.repeat_dir / record.pipeline_name / record.suite
    if not base.exists():
        return result
    for child in sorted(base.iterdir()):
        if child.is_dir() and child.name.startswith("injection_task_"):
            case_path = child / "none" / "none.json"
            if case_path.exists():
                result[child.name] = read_json(case_path).get("utility")
    return result


def compute_rows(records: list[RunRecord]) -> list[PseudoCaseRow]:
    rows: list[PseudoCaseRow] = []
    for record in records:
        if record.role != ROLE_B_ASR_MODEL:
            continue
        utilities = _pseudo_case_utilities(record)
        refusal = refusal_counts_by_injection_task(record)
        for injection_task_id in sorted(utilities):
            refused, total = refusal.get(injection_task_id, (0, 0))
            rows.append(
                PseudoCaseRow(
                    suite=record.suite,
                    repeat=record.repeat_dir.name,
                    injection_task_id=injection_task_id,
                    achievable_standalone=utilities[injection_task_id],
                    refused_count=refused,
                    case_count=total,
                )
            )
    rows.sort(key=lambda r: (r.suite, r.repeat, r.injection_task_id))
    return rows


def write_csv(rows: list[PseudoCaseRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["suite", "repeat", "injection_task_id", "achievable_standalone", "refused_count", "case_count", "refusal_rate"]
        )
        for r in rows:
            writer.writerow(
                [
                    r.suite,
                    r.repeat,
                    r.injection_task_id,
                    r.achievable_standalone,
                    r.refused_count,
                    r.case_count,
                    f"{r.refusal_rate:.3f}" if r.refusal_rate is not None else "",
                ]
            )


def render_markdown(rows: list[PseudoCaseRow]) -> str:
    lines = ["## N14. Injection goals achievable as standalone tasks", ""]
    lines.append(
        "Read from B (`allow_all`) runs only -- see `analysis/verification.md`'s Status "
        "section, correction 2. `model_refused`/`out_of_scope` cross-referenced here are "
        "policy-invariant (I4), so they need no D run either."
    )
    lines.append("")
    lines.append("| Suite | Repeat | Injection task | Achievable standalone | In-context refusal rate |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        if r.achievable_standalone is True:
            achievable = "yes"
        elif r.achievable_standalone is False:
            achievable = "**no**"
        else:
            achievable = "n/a (missing/null)"
        rate = f"{r.refusal_rate:.2f} ({r.refused_count}/{r.case_count})" if r.refusal_rate is not None else "n/a"
        lines.append(f"| {r.suite} | {r.repeat} | {r.injection_task_id} | {achievable} | {rate} |")
    lines.append("")

    unachievable = [r for r in rows if r.achievable_standalone is not True]
    if unachievable:
        named = ", ".join(f"{r.suite}/{r.injection_task_id} ({r.repeat})" for r in unachievable)
        lines.append(
            f"**{len(unachievable)} pseudo-case(s) did not cleanly succeed standalone under "
            f"`allow_all`, reported here rather than filtered: {named}.**"
        )
    else:
        lines.append("Every discovered pseudo-case succeeded standalone.")
    return "\n".join(lines)
