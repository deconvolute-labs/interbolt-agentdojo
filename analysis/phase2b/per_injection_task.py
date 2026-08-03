"""Phase 2B, N1 + N6 (joined, per `analysis/verification.md`'s Phase 5 file tree):

N1. Per-injection-task block rate -- block rate 1.00 aggregated across nine different
attack texts is consistent with the thesis but doesn't test it; this computes the
rate separately for each injection task, within each (suite, policy, repeat), plus
the count of cases reaching a gated sink (a rate over two cases isn't evidence of
much).

N6. Refusal variance across injection tasks -- `model_refused` broken down by
injection task, within each suite and repeat (policy-invariant per I4, so reported
once per (suite,repeat) and repeated across policy rows here since the file is at
N1's finer grain). Joined against N14 (`pseudo_case_standalone`): an injection task
that fails standalone contributes refusals that are incapacity, not refusal.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suite

from analysis.common.casetables import AttackedCaseRow, Quartet, refusal_counts_by_injection_task
from analysis.common.discovery import RunRecord
from analysis.phase2b.pseudo_case_standalone import compute_rows as compute_pseudo_case_rows


@dataclass(frozen=True)
class InjectionTaskRow:
    suite: str
    policy: str
    repeat: int
    injection_task_id: str
    block_rate_num: int
    block_rate_den: int
    gated_sink_case_count: int  # == block_rate_den; named per spec's "report count alongside"
    refused_count: int
    case_count: int
    achievable_standalone: bool | None
    policy_fingerprint: str

    @property
    def block_rate(self) -> float | None:
        return self.block_rate_num / self.block_rate_den if self.block_rate_den else None

    @property
    def refusal_rate(self) -> float | None:
        return self.refused_count / self.case_count if self.case_count else None


def _group(rows: list, key) -> dict:
    groups: dict = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    return groups


def _repeat_dir_name_to_index(quartets: list[Quartet]) -> dict[tuple[str, str], int]:
    """(suite, repeat_dir_name) -> positional repeat index, from each quartet's B
    record -- needed to join `pseudo_case_standalone`'s directory-name-keyed rows
    onto this module's positional-index-keyed ones."""
    return {(q.suite, q.b.repeat_dir.name): q.repeat for q in quartets}


def compute_rows(
    attacked: list[AttackedCaseRow], quartets: list[Quartet], records: list[RunRecord]
) -> list[InjectionTaskRow]:
    rows_by_group = _group(attacked, lambda r: (r.suite, r.policy, r.repeat, r.injection_task_id))

    b_by_suite_repeat: dict[tuple[str, int], RunRecord] = {(q.suite, q.repeat): q.b for q in quartets}
    refusal_by_suite_repeat = {
        key: refusal_counts_by_injection_task(b) for key, b in b_by_suite_repeat.items()
    }

    dir_to_index = _repeat_dir_name_to_index(quartets)
    achievable: dict[tuple[str, int, str], bool | None] = {}
    for pr in compute_pseudo_case_rows(records):
        idx = dir_to_index.get((pr.suite, pr.repeat))
        if idx is None:
            continue
        achievable[(pr.suite, idx, pr.injection_task_id)] = pr.achievable_standalone

    out: list[InjectionTaskRow] = []
    for q in quartets:
        suite_obj = get_suite(q.d.benchmark_version, q.suite)
        policy_fingerprint = (q.d.policy.sha256 if q.d.policy else None) or ""
        refusal = refusal_by_suite_repeat.get((q.suite, q.repeat), {})
        for injection_task_id in sorted(suite_obj.injection_tasks):
            case_rows = rows_by_group.get((q.suite, q.policy, q.repeat, injection_task_id), [])
            blocked = sum(1 for r in case_rows if r.bucket == "interbolt_blocked")
            succeeded = sum(1 for r in case_rows if r.bucket == "attack_succeeded_defended")
            refused_count, case_count = refusal.get(injection_task_id, (0, 0))
            out.append(
                InjectionTaskRow(
                    suite=q.suite,
                    policy=q.policy,
                    repeat=q.repeat,
                    injection_task_id=injection_task_id,
                    block_rate_num=blocked,
                    block_rate_den=blocked + succeeded,
                    gated_sink_case_count=blocked + succeeded,
                    refused_count=refused_count,
                    case_count=case_count,
                    achievable_standalone=achievable.get((q.suite, q.repeat, injection_task_id)),
                    policy_fingerprint=policy_fingerprint,
                )
            )

    out.sort(key=lambda r: (r.suite, r.policy, r.repeat, r.injection_task_id))
    return out


_FIELDS = [
    "suite", "policy", "repeat", "injection_task_id",
    "block_rate_num", "block_rate_den", "block_rate", "gated_sink_case_count",
    "refused_count", "case_count", "refusal_rate", "achievable_standalone", "policy_fingerprint",
]


def write_csv(rows: list[InjectionTaskRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [
                    r.suite, r.policy, r.repeat, r.injection_task_id,
                    r.block_rate_num, r.block_rate_den,
                    f"{r.block_rate:.4f}" if r.block_rate is not None else "",
                    r.gated_sink_case_count,
                    r.refused_count, r.case_count,
                    f"{r.refusal_rate:.4f}" if r.refusal_rate is not None else "",
                    r.achievable_standalone,
                    r.policy_fingerprint,
                ]
            )


def render_markdown(rows: list[InjectionTaskRow]) -> str:
    lines = ["## N1 + N6: per-injection-task block rate and refusal variance", ""]
    lines.append(
        "N1: block rate per injection task (`interbolt_blocked / (interbolt_blocked + "
        "attack_succeeded_defended)`), with the gated-sink case count alongside since a rate "
        "over few cases is weak evidence. N6: `model_refused` count per injection task "
        "(policy-invariant, repeated per policy row here), cross-referenced against N14's "
        "standalone achievability -- an unachievable injection task's refusals are incapacity, "
        "not refusal."
    )
    lines.append("")
    lines.append("| Suite | Policy | Repeat | Injection task | Block rate | Gated-sink cases | Refused | Refusal rate | Achievable standalone |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        block_rate = f"{r.block_rate:.2f} ({r.block_rate_num}/{r.block_rate_den})" if r.block_rate is not None else "undefined (den=0)"
        refusal_rate = f"{r.refusal_rate:.2f} ({r.refused_count}/{r.case_count})" if r.refusal_rate is not None else "n/a"
        if r.achievable_standalone is True:
            achievable = "yes"
        elif r.achievable_standalone is False:
            achievable = "**no**"
        else:
            achievable = "n/a"
        lines.append(
            f"| {r.suite} | {r.policy} | {r.repeat} | {r.injection_task_id} | {block_rate} | "
            f"{r.gated_sink_case_count} | {r.refused_count} | {refusal_rate} | {achievable} |"
        )
    lines.append("")

    varying = [r for r in rows if r.block_rate is not None and r.block_rate != 1.0]
    if varying:
        lines.append(
            f"**{len(varying)} (suite,policy,repeat,injection_task) row(s) have block rate < 1.00 "
            "-- the policy is not flat across attack texts.**"
        )
    else:
        lines.append("Every individual injection task with at least one gated-sink case has block rate 1.00.")
    return "\n".join(lines)
