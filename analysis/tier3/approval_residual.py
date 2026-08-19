"""Tier 3, 2.7: approval residual (proxy).

Neither `strict.yaml` nor `targeted.yaml` uses `require_approval` -- both fail closed straight to
`block` once the run is tainted -- so the draft's `[N]` of `[M]` approval-residual figure has no
literal referent in this dataset. The proxy computed instead, explicitly labeled a proxy
throughout: benign (C-run) state-changing calls blocked over benign state-changing calls
attempted.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from interbolt_agentdojo.namespaces import resolve_namespace

from analysis.common.artifacts import run_trajectory
from analysis.common.discovery import ROLE_C_UTILITY, RunRecord
from analysis.tier3.positional_distributions import run_id_to_case
from analysis.tier3.suite_metadata import STATE_CHANGING_TOOLS


@dataclass(frozen=True)
class ApprovalResidualRow:
    suite: str
    policy: str
    repeat_dir: str
    n_state_changing_attempted: int
    n_state_changing_blocked: int
    proxy_rate: float | None
    policy_fingerprint: str


def compute_rows(records: list[RunRecord]) -> list[ApprovalResidualRow]:
    rows: list[ApprovalResidualRow] = []
    for record in records:
        if record.role != ROLE_C_UTILITY:
            continue
        state_changing = {
            f"{resolve_namespace(record.suite, t)}.{t}" for t in STATE_CHANGING_TOOLS.get(record.suite, frozenset())
        }
        selected, _ = run_id_to_case(record)
        attempted = blocked = 0
        for run_id in selected:
            for cd in run_trajectory(record.repeat_dir, run_id):
                if cd.tool in state_changing:
                    attempted += 1
                    if cd.action == "block":
                        blocked += 1
        policy_name = record.policy.name if record.policy else "none"
        policy_fingerprint = (record.policy.sha256 if record.policy else None) or ""
        rows.append(
            ApprovalResidualRow(
                suite=record.suite, policy=policy_name, repeat_dir=record.repeat_dir.name,
                n_state_changing_attempted=attempted, n_state_changing_blocked=blocked,
                proxy_rate=(blocked / attempted) if attempted else None,
                policy_fingerprint=policy_fingerprint,
            )
        )
    rows.sort(key=lambda r: (r.suite, r.policy, r.repeat_dir))
    return rows


_FIELDS = ["suite", "policy", "repeat_dir", "n_state_changing_attempted", "n_state_changing_blocked",
           "proxy_rate", "policy_fingerprint"]


def write_csv(rows: list[ApprovalResidualRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [
                    r.suite, r.policy, r.repeat_dir, r.n_state_changing_attempted, r.n_state_changing_blocked,
                    f"{r.proxy_rate:.4f}" if r.proxy_rate is not None else "", r.policy_fingerprint,
                ]
            )


def render_markdown(rows: list[ApprovalResidualRow]) -> str:
    lines = ["## 2.7. Approval residual (proxy)", ""]
    lines.append(
        "**This is a proxy, not the draft's `[N]` of `[M]` approval-residual figure** -- neither "
        "policy uses `require_approval`. Reported instead: benign state-changing calls blocked "
        "over benign state-changing calls attempted, per (suite, policy, repeat)."
    )
    lines.append("")
    lines.append("| Suite | Policy | Repeat | Attempted | Blocked | Proxy rate |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        rate = f"{r.proxy_rate:.3f} ({r.n_state_changing_blocked}/{r.n_state_changing_attempted})" if r.proxy_rate is not None else "undefined (0 attempted)"
        lines.append(f"| {r.suite} | {r.policy} | {r.repeat_dir} | {r.n_state_changing_attempted} | {r.n_state_changing_blocked} | {rate} |")
    lines.append("")
    return "\n".join(lines)
