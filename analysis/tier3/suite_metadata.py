"""Tier 3, 2.8: suite metadata.

Tool counts per suite across the whole AgentDojo v1.2.2 benchmark, split read-only versus
state-changing, to settle whether banking and travel are the smallest/largest surfaces (the
draft's text was softened to "among" -- this module states the exact answer).

`agentdojo`'s `Function` (`functions_runtime.py`) has no `read_only`/`state_changing`/side-effect
attribute -- grepped the entire installed 0.1.35 package, confirmed absent, so the split below is
a hand-verified constant, checked against each tool's actual body in
`agentdojo/default_suites/v1/tools/{banking_client,travel_booking_client}.py` (does it mutate
`BankAccount`/`UserAccount`/`Calendar`/`Hotel`/`Restaurant`/`CarRental`/`Inbox` state, or only read
it) -- independently derived from the tool source, not from any policy YAML's sink list, even
though it happens to match which sinks `strict.yaml`/`targeted.yaml` gate. `STATE_CHANGING_TOOLS`
is exported for reuse by `read_before_write.py` (2.5), `approval_residual.py` (2.7), and
`cross_suite_consistency.py` (N13).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suites

BENCHMARK_VERSION = "v1.2.2"

STATE_CHANGING_TOOLS: dict[str, frozenset[str]] = {
    "banking": frozenset(
        {"send_money", "schedule_transaction", "update_scheduled_transaction", "update_password", "update_user_info"}
    ),
    "travel": frozenset(
        {"create_calendar_event", "cancel_calendar_event", "reserve_hotel", "reserve_restaurant", "reserve_car_rental", "send_email"}
    ),
}


@dataclass(frozen=True)
class SuiteMetadataRow:
    suite: str
    n_tools_total: int
    n_state_changing: int | None  # None: no hand-verified split for this suite (not banking/travel)
    n_read_only: int | None
    has_hand_verified_split: bool


def compute_rows() -> list[SuiteMetadataRow]:
    """One row per AgentDojo v1.2.2 suite. Only banking/travel have a hand-verified
    state-changing/read-only split (the suites this repo's policies target); `slack` and
    `workspace` get their total tool count only, `has_hand_verified_split=False` -- reported for
    the min/max comparison, never silently omitted, but not hand-classified here."""
    rows: list[SuiteMetadataRow] = []
    for name, suite in sorted(get_suites(BENCHMARK_VERSION).items()):
        n_total = len(suite.tools)
        state_changing = STATE_CHANGING_TOOLS.get(name)
        if state_changing is None:
            rows.append(SuiteMetadataRow(name, n_total, None, None, False))
            continue
        tool_names = {t.name for t in suite.tools}
        unknown = state_changing - tool_names
        if unknown:
            raise AssertionError(
                f"suite_metadata: hand-verified state-changing set for {name!r} names tools not "
                f"present in the actual suite: {unknown} -- agentdojo's tool set likely changed "
                "since this constant was written; update STATE_CHANGING_TOOLS"
            )
        n_state_changing = len(state_changing)
        rows.append(SuiteMetadataRow(name, n_total, n_state_changing, n_total - n_state_changing, True))
    return rows


_FIELDS = ["suite", "n_tools_total", "n_state_changing", "n_read_only", "has_hand_verified_split"]


def write_csv(rows: list[SuiteMetadataRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [
                    r.suite, r.n_tools_total,
                    r.n_state_changing if r.n_state_changing is not None else "",
                    r.n_read_only if r.n_read_only is not None else "",
                    r.has_hand_verified_split,
                ]
            )


def render_markdown(rows: list[SuiteMetadataRow]) -> str:
    lines = ["## 2.8. Suite metadata", ""]
    lines.append(
        "Tool counts per AgentDojo v1.2.2 suite. `agentdojo`'s `Function` has no "
        "read-only/state-changing attribute (checked the installed 0.1.35 package directly), so "
        "banking's and travel's split is a hand-verified constant, checked against each tool's "
        "actual body in `agentdojo/default_suites/v1/tools/{banking_client,travel_booking_client}"
        ".py` -- independent of any policy YAML's sink list, though it happens to match which "
        "sinks `strict.yaml`/`targeted.yaml` gate. `slack`/`workspace` are reported by total tool "
        "count only, for the min/max comparison below, not hand-classified."
    )
    lines.append("")
    lines.append("| Suite | Total tools | State-changing | Read-only | Hand-verified split |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        sc = str(r.n_state_changing) if r.n_state_changing is not None else "n/a"
        ro = str(r.n_read_only) if r.n_read_only is not None else "n/a"
        lines.append(f"| {r.suite} | {r.n_tools_total} | {sc} | {ro} | {r.has_hand_verified_split} |")
    lines.append("")

    by_total = sorted(rows, key=lambda r: r.n_tools_total)
    smallest_count, largest_count = by_total[0].n_tools_total, by_total[-1].n_tools_total
    smallest = [r.suite for r in by_total if r.n_tools_total == smallest_count]
    largest = [r.suite for r in by_total if r.n_tools_total == largest_count]
    lines.append(
        f"**Largest surface: {', '.join(largest)} ({largest_count} tools).** "
        + ("Strict, unique maximum." if len(largest) == 1 else f"Tied among {len(largest)} suites, not a strict maximum.")
    )
    lines.append(
        f"**Smallest surface: {', '.join(smallest)} ({smallest_count} tools).** "
        + (
            "Strict, unique minimum."
            if len(smallest) == 1
            else f"Tied among {len(smallest)} suites ({', '.join(smallest)}), **not a strict minimum** -- "
            "this is exactly why the draft's text was softened to \"among.\""
        )
    )
    lines.append("")
    return "\n".join(lines)
