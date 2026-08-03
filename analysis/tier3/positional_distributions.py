"""Tier 3, N8 + N9 remainder: positional distributions.

N8: distribution of the call index at which a run first becomes tainted (`run_tainted` flips
`False` -> `True`). N9 remainder: block position (call index of the first blocked call) as a
fraction of trajectory length, per case with at least one block.

Both are read directly off `run_trajectory()`'s `run_tainted`/`action` fields, over every scored
run_id. N8 covers B, C, and D roles (any run that goes through Interbolt); N9 remainder covers
only C and D (B is `allow_all` and never blocks, so "first block position" is undefined there).
A is excluded from both -- it has no `call_records.jsonl`/`interbolt_events.jsonl` at all (never
touches Interbolt), confirmed in prior tier2 work -- stated explicitly rather than silently
skipped.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from analysis.common.artifacts import case_to_run_id, discover_results, run_trajectory, selected_run_ids
from analysis.common.discovery import ROLE_B_ASR_MODEL, ROLE_C_UTILITY, ROLE_D_ASR_SYSTEM, RunRecord

# The dataviz skill's validated blue ramp (references/palette.md), stepped for a 2-series
# categorical pair: step 400 (#3987e5) and step 600 (#184f95). Verified via
# scripts/validate_palette.js "#3987e5,#184f95" --mode light -- all checks pass (lightness band,
# chroma floor, CVD separation, normal-vision floor, contrast vs. #fcfcfb surface). This is a
# static print-style export (PNG/SVG to a file, not a theme-aware web page), so only the
# light-surface variant is validated and used.
SUITE_COLORS = {"banking": "#3987e5", "travel": "#184f95"}


@dataclass(frozen=True)
class TaintOnsetRow:
    suite: str
    role: str
    policy: str  # "allow_all" for B; policy name for C/D
    repeat_dir: str  # literal directory name, e.g. "repeat_0"
    user_task_id: str | None
    injection_task_id: str | None
    onset_index: int | None  # None: never tainted in this run
    trajectory_length: int


@dataclass(frozen=True)
class BlockPositionRow:
    suite: str
    role: str
    policy: str
    repeat_dir: str
    user_task_id: str | None
    injection_task_id: str | None
    first_block_index: int
    trajectory_length: int
    fraction: float


def run_id_to_case(record: RunRecord) -> tuple[set[str], dict[str, tuple[str, str | None]]]:
    """(selected run_ids, run_id -> (user_task_id, injection_task_id)) for one record."""
    if record.pipeline_name is None:
        return set(), {}
    without_inj, with_inj = discover_results(record.repeat_dir, record.pipeline_name, record.suite, record.benchmark_version)
    selected = selected_run_ids(record.repeat_dir, without_inj, with_inj)
    all_cases = {**without_inj, **with_inj}
    run_ids_map = case_to_run_id(record.repeat_dir, all_cases)
    inv = {run_id: case_key for case_key, run_id in run_ids_map.items()}
    return selected, inv


def compute_taint_onset_rows(records: list[RunRecord]) -> list[TaintOnsetRow]:
    rows: list[TaintOnsetRow] = []
    for record in records:
        if record.role not in (ROLE_B_ASR_MODEL, ROLE_C_UTILITY, ROLE_D_ASR_SYSTEM):
            continue
        selected, inv = run_id_to_case(record)
        policy_name = record.policy.name if record.policy else "none"
        for run_id in selected:
            traj = run_trajectory(record.repeat_dir, run_id)
            onset = next((i for i, cd in enumerate(traj) if cd.run_tainted), None)
            user_task_id, injection_task_id = inv.get(run_id, (None, None))
            rows.append(
                TaintOnsetRow(
                    suite=record.suite, role=record.role, policy=policy_name,
                    repeat_dir=record.repeat_dir.name, user_task_id=user_task_id,
                    injection_task_id=injection_task_id, onset_index=onset, trajectory_length=len(traj),
                )
            )
    rows.sort(key=lambda r: (r.suite, r.role, r.policy, r.repeat_dir, r.user_task_id or "", r.injection_task_id or ""))
    return rows


def compute_block_position_rows(records: list[RunRecord]) -> list[BlockPositionRow]:
    rows: list[BlockPositionRow] = []
    for record in records:
        if record.role not in (ROLE_C_UTILITY, ROLE_D_ASR_SYSTEM):
            continue
        selected, inv = run_id_to_case(record)
        policy_name = record.policy.name if record.policy else "none"
        for run_id in selected:
            traj = run_trajectory(record.repeat_dir, run_id)
            first_block = next((i for i, cd in enumerate(traj) if cd.action == "block"), None)
            if first_block is None:
                continue  # no block in this case -- outside this row type's own definition, not a drop
            user_task_id, injection_task_id = inv.get(run_id, (None, None))
            rows.append(
                BlockPositionRow(
                    suite=record.suite, role=record.role, policy=policy_name,
                    repeat_dir=record.repeat_dir.name, user_task_id=user_task_id,
                    injection_task_id=injection_task_id, first_block_index=first_block,
                    trajectory_length=len(traj), fraction=first_block / len(traj),
                )
            )
    rows.sort(key=lambda r: (r.suite, r.role, r.policy, r.repeat_dir, r.user_task_id or "", r.injection_task_id or ""))
    return rows


_TAINT_FIELDS = ["suite", "role", "policy", "repeat_dir", "user_task_id", "injection_task_id",
                  "onset_index", "trajectory_length"]


def write_taint_onset_csv(rows: list[TaintOnsetRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_TAINT_FIELDS)
        for r in rows:
            writer.writerow(
                [r.suite, r.role, r.policy, r.repeat_dir, r.user_task_id or "", r.injection_task_id or "",
                 r.onset_index if r.onset_index is not None else "", r.trajectory_length]
            )


_BLOCK_FIELDS = ["suite", "role", "policy", "repeat_dir", "user_task_id", "injection_task_id",
                  "first_block_index", "trajectory_length", "fraction"]


def write_block_position_csv(rows: list[BlockPositionRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_BLOCK_FIELDS)
        for r in rows:
            writer.writerow(
                [r.suite, r.role, r.policy, r.repeat_dir, r.user_task_id or "", r.injection_task_id or "",
                 r.first_block_index, r.trajectory_length, f"{r.fraction:.4f}"]
            )


def write_taint_onset_figure(rows: list[TaintOnsetRow], out_dir: Path, basename: str = "taint_onset_histogram") -> Path:
    """Grouped bar histogram of onset_index by suite, colorblind-safe blue pair (see
    SUITE_COLORS). Writes <basename>.svg, <basename>.png (200dpi), and <basename>.csv (the exact
    binned counts backing the chart, per Phase 3's "every figure's data written alongside as CSV
    with the same basename" rule) to `out_dir`."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tainted = [r for r in rows if r.onset_index is not None]
    suites = sorted({r.suite for r in rows})
    max_index = max((r.onset_index for r in tainted), default=0)

    counts: dict[str, list[int]] = {s: [0] * (max_index + 1) for s in suites}
    for r in tainted:
        counts[r.suite][r.onset_index] += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{basename}.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["onset_index", *suites])
        for i in range(max_index + 1):
            writer.writerow([i, *(counts[s][i] for s in suites)])

    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=200)
    x = range(max_index + 1)
    n_suites = len(suites)
    bar_width = 0.8 / max(n_suites, 1)
    for i, suite in enumerate(suites):
        offsets = [xi + (i - (n_suites - 1) / 2) * bar_width for xi in x]
        ax.bar(offsets, counts[suite], width=bar_width * 0.92, label=suite,
               color=SUITE_COLORS.get(suite, "#3987e5"), edgecolor="none")

    ax.set_xlabel("Call index at which the run first becomes tainted")
    ax.set_ylabel("Number of runs")
    ax.set_title("Taint onset (N8)")
    ax.set_xticks(list(x))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c3c2b7")
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e")
    ax.yaxis.grid(True, color="#e1e0d9", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)

    never_tainted = len(rows) - len(tainted)
    if never_tainted:
        fig.text(0.5, -0.02, f"{never_tainted} run(s) never tainted, excluded from this histogram (see the CSV/markdown for the count).",
                  ha="center", fontsize=8, color="#898781")

    fig.tight_layout()
    svg_path = out_dir / f"{basename}.svg"
    png_path = out_dir / f"{basename}.png"
    fig.savefig(svg_path, bbox_inches="tight")
    fig.savefig(png_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return csv_path


def render_markdown(taint_rows: list[TaintOnsetRow], block_rows: list[BlockPositionRow]) -> str:
    lines = ["## N8 + N9 remainder: positional distributions", ""]

    lines.append("### N8. Taint onset")
    lines.append("")
    lines.append(
        "Call index at which a run first becomes tainted, over every scored run in roles B, C, "
        "and D (A never touches Interbolt, excluded). Histogram: "
        "`figures/taint_onset_histogram.{svg,png}` (blue pair `#3987e5` banking / `#184f95` "
        "travel, validated colorblind-safe via the dataviz skill's palette validator)."
    )
    lines.append("")
    by_suite: dict[str, list[TaintOnsetRow]] = {}
    for r in taint_rows:
        by_suite.setdefault(r.suite, []).append(r)
    lines.append("| Suite | Runs | Ever tainted | Never tainted | Onset index (min/median/max) |")
    lines.append("|---|---|---|---|---|")
    for suite, group in sorted(by_suite.items()):
        tainted = sorted(r.onset_index for r in group if r.onset_index is not None)
        never = len(group) - len(tainted)
        if tainted:
            median = tainted[len(tainted) // 2] if len(tainted) % 2 else (tainted[len(tainted) // 2 - 1] + tainted[len(tainted) // 2]) / 2
            rng = f"{tainted[0]} / {median} / {tainted[-1]}"
        else:
            rng = "n/a"
        lines.append(f"| {suite} | {len(group)} | {len(tainted)} | {never} | {rng} |")
    lines.append("")

    lines.append("### N9 remainder. Block position as a fraction of trajectory length")
    lines.append("")
    lines.append(
        "For every C/D case with at least one block, the call index of the first block divided "
        "by that run's total call count. The main N9 question (blocks vs. lost tasks) is already "
        "answered by N2's `blocked_but_recovered` -- this is only the position statistic."
    )
    lines.append("")
    by_suite_role: dict[tuple[str, str], list[BlockPositionRow]] = {}
    for r in block_rows:
        by_suite_role.setdefault((r.suite, r.role), []).append(r)
    lines.append("| Suite | Role | Cases with a block | Fraction (min/median/max) |")
    lines.append("|---|---|---|---|")
    for (suite, role), group in sorted(by_suite_role.items()):
        fracs = sorted(r.fraction for r in group)
        median = fracs[len(fracs) // 2] if len(fracs) % 2 else (fracs[len(fracs) // 2 - 1] + fracs[len(fracs) // 2]) / 2
        lines.append(f"| {suite} | {role} | {len(group)} | {fracs[0]:.2f} / {median:.2f} / {fracs[-1]:.2f} |")
    lines.append("")

    return "\n".join(lines)
