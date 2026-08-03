"""Figure 2: what each side of the decision depends on.

Left panel -- fraction of cases the undefended model declined, per injection task, deduplicated
on policy (refusal is policy-invariant). Right panel -- fraction of attacks reaching a gated sink
that the policy blocked, pooled across both policies within a repeat. Two bars per task (one per
repeat), sixteen tasks in suite order (banking 0-8, travel 0-6), sharing a y axis so the left
panel's swing and the right panel's flatness read side by side.

Source: `analysis_out/phase2b/per_injection_task.csv`.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from analysis.blogfigs import _layout, palette

# The two injection tasks whose goal cannot succeed as posed, regardless of defense.
_UNREACHABLE = {("banking", "injection_task_8"), ("travel", "injection_task_1")}

_BANKING_TASKS = [f"injection_task_{i}" for i in range(9)]
_TRAVEL_TASKS = [f"injection_task_{i}" for i in range(7)]
_TASK_ORDER = [("banking", t) for t in _BANKING_TASKS] + [("travel", t) for t in _TRAVEL_TASKS]
_LABELS = [f"B{i}" for i in range(9)] + [f"T{i}" for i in range(7)]
_REPEATS = [0, 1]
_BAR_WIDTH = 0.4


def _read_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def _build(rows: list[dict]) -> tuple[dict, dict]:
    """Returns (refusal, block) keyed by (suite, injection_task_id, repeat)."""
    by_group: dict[tuple[str, str, int], list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["suite"], row["injection_task_id"], int(row["repeat"]))
        by_group[key].append(row)

    refusal: dict[tuple[str, str, int], tuple[int, int]] = {}
    block: dict[tuple[str, str, int], tuple[int, int]] = {}
    for key, group_rows in by_group.items():
        policies = {r["policy"]: r for r in group_rows}
        refused_counts = {r["refused_count"] for r in group_rows}
        case_counts = {r["case_count"] for r in group_rows}
        assert len(refused_counts) == 1 and len(case_counts) == 1, (
            f"refusal is policy-invariant but disagrees across policies for {key}: "
            f"refused_count={refused_counts}, case_count={case_counts}"
        )
        any_row = group_rows[0]
        refusal[key] = (int(any_row["refused_count"]), int(any_row["case_count"]))

        num = sum(int(r["block_rate_num"]) for r in group_rows)
        den = sum(int(r["block_rate_den"]) for r in group_rows)
        assert num == den or den == 0, (
            f"pooled block rate is not 1.00 for {key}: {num}/{den} "
            "(this assertion is the headline finding -- it must never fire)"
        )
        block[key] = (num, den)
        assert len(policies) <= 2

    return refusal, block


def _write_data_csv(out_path: Path, refusal: dict, block: dict) -> None:
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "suite",
                "injection_task_id",
                "label",
                "repeat",
                "refused_count",
                "case_count",
                "refusal_rate",
                "pooled_block_num",
                "pooled_block_den",
                "unreachable",
            ]
        )
        for (suite, task_id), label in zip(_TASK_ORDER, _LABELS):
            for repeat in _REPEATS:
                key = (suite, task_id, repeat)
                refused, cases = refusal[key]
                bnum, bden = block[key]
                w.writerow(
                    [
                        suite,
                        task_id,
                        label,
                        repeat,
                        refused,
                        cases,
                        f"{refused / cases:.4f}",
                        bnum,
                        bden,
                        (suite, task_id) in _UNREACHABLE,
                    ]
                )


def _draw(c: dict, refusal: dict, block: dict) -> plt.Figure:
    palette.apply_rcparams(c)
    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(palette.FIG_WIDTH_IN, 4.2), sharey=True, dpi=palette.DPI)

    n = len(_TASK_ORDER)
    x = list(range(n))

    for ax in (ax_l, ax_r):
        ax.set_ylim(0, 1.05)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
        ax.set_xlim(-0.6, n - 0.4)
        ax.set_xticks(x)
        ax.set_xticklabels(_LABELS, fontsize=9)
        ax.tick_params(left=False, bottom=False)
        split_x = 8.5  # between B8 (index 8) and T0 (index 9)
        _layout.draw_suite_separator(ax, split_x, axis_color=c["axis"], muted_color=c["muted"])

    ax_l.tick_params(labelleft=True)
    ax_r.tick_params(labelleft=False)
    palette.strip_spines(ax_l, keep_left=True, keep_bottom=False)
    palette.strip_spines(ax_r, keep_left=False, keep_bottom=False)

    _layout.label_suites(ax_l, 4.0, 12.0, muted_color=c["muted"])
    _layout.label_suites(ax_r, 4.0, 12.0, muted_color=c["muted"])

    # Left panel: refusal rate.
    for ri, repeat in enumerate(_REPEATS):
        offset = (ri - 0.5) * _BAR_WIDTH
        for xi, (suite, task_id) in zip(x, _TASK_ORDER):
            refused, cases = refusal[(suite, task_id, repeat)]
            rate = refused / cases
            unreachable = (suite, task_id) in _UNREACHABLE
            ax_l.bar(
                xi + offset,
                rate,
                width=_BAR_WIDTH,
                color=c["baseline"],
                edgecolor=c["attention"] if unreachable else "none",
                hatch="///" if unreachable else None,
                linewidth=1.1 if unreachable else 0,
                zorder=2,
            )
    ax_l.set_ylabel("fraction of cases the undefended model declined", fontsize=10, color=c["text"])
    ax_l.text(
        0.0,
        1.09,
        "hatched: goal cannot succeed as posed",
        transform=ax_l.transAxes,
        ha="left",
        va="bottom",
        fontsize=8.5,
        color=c["attention"],
    )

    # Right panel: pooled block rate.
    for ri, repeat in enumerate(_REPEATS):
        offset = (ri - 0.5) * _BAR_WIDTH
        for xi, (suite, task_id) in zip(x, _TASK_ORDER):
            num, den = block[(suite, task_id, repeat)]
            bx = xi + offset
            if den == 0:
                ax_r.plot(
                    [bx - _BAR_WIDTH * 0.3, bx + _BAR_WIDTH * 0.3],
                    [0.02, 0.02],
                    color=c["muted"],
                    linewidth=1.5,
                    solid_capstyle="butt",
                    zorder=2,
                )
                continue
            rate = num / den
            ax_r.bar(bx, rate, width=_BAR_WIDTH, color=c["primary"], zorder=2)
            label = f"n={den}"
            # Bars are always exactly 1.0 tall (that's the finding), so there's no vertical
            # squeeze -- the label sits inside the bar, near its top, well clear of the
            # suite/legend text further up.
            ax_r.text(
                bx,
                rate - 0.09,
                label,
                rotation=90,
                ha="center",
                va="top",
                fontsize=6.7,
                color=c["on_primary"],
                family="monospace",
            )
    ax_r.set_ylabel("")
    ax_r.set_xlabel("")
    ax_r.text(
        0.5,
        -0.16,
        "fraction of attacks reaching a gated sink that were blocked",
        transform=ax_r.transAxes,
        ha="center",
        va="top",
        fontsize=10,
        color=c["text"],
    )
    handles = [
        Patch(facecolor=c["muted"], edgecolor="none", label="no gated cases (tick at baseline)"),
    ]
    ax_r.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, 1.12), frameon=False, fontsize=8.5)

    fig.subplots_adjust(left=0.09, right=0.98, top=0.82, bottom=0.16, wspace=0.06)
    return fig


def write_figure(csv_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_rows(csv_path)
    refusal, block = _build(rows)

    data_csv = out_dir / "figure2_data.csv"
    _write_data_csv(data_csv, refusal, block)

    for theme, filename in (("dark", "figure2.svg"), ("light", "figure2_light.svg")):
        c = palette.palette(theme)
        fig = _draw(c, refusal, block)
        fig.savefig(out_dir / filename, transparent=True)
        plt.close(fig)

    return data_csv
