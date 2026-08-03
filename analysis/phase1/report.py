"""Renders Phase 1's `CheckResult`s to `integrity_checks.csv` and a markdown summary."""

from __future__ import annotations

import csv
from pathlib import Path

from analysis.phase1.checks import CheckResult

_FIELDS = ["check_id", "suite", "policy", "repeat", "status", "computed", "expected", "detail"]


def write_checks_csv(results: list[CheckResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in results:
            writer.writerow([r.check_id, r.suite, r.policy, r.repeat, r.status, r.computed, r.expected, r.detail])


def render_markdown(results: list[CheckResult]) -> str:
    lines = ["# Phase 1: integrity checks", ""]
    failures = [r for r in results if r.status in ("FAIL", "WARN")]
    if failures:
        lines.append(f"**{len(failures)} FAIL/WARN result(s) -- listed here before the full per-check tables:**")
        lines.append("")
        lines.append("| Check | Suite | Policy | Repeat | Status | Computed | Expected | Detail |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in failures:
            lines.append(f"| {r.check_id} | {r.suite} | {r.policy} | {r.repeat} | **{r.status}** | {r.computed} | {r.expected} | {r.detail} |")
        lines.append("")
    else:
        lines.append("No FAIL/WARN results.")
        lines.append("")

    check_ids: list[str] = []
    for r in results:
        if r.check_id not in check_ids:
            check_ids.append(r.check_id)

    for check_id in check_ids:
        rows = [r for r in results if r.check_id == check_id]
        lines.append(f"## {check_id}")
        lines.append("")
        lines.append("| Suite | Policy | Repeat | Status | Computed | Expected | Detail |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in rows:
            lines.append(f"| {r.suite} | {r.policy} | {r.repeat} | {r.status} | {r.computed} | {r.expected} | {r.detail} |")
        lines.append("")

    return "\n".join(lines)
