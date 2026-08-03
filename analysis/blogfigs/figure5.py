"""Figure 5: benign tasks by outcome.

Horizontal stacked bars, one per configuration, same eight configurations and order as Figure 3
(suite x policy x repeat). Absolute counts, not fractions: banking bars total 16, travel 20, so
the x axis is fixed 0-20 and banking bars are visibly shorter -- that size difference is the
point, so it is never normalized away.

Source: `analysis_out/phase2b/utility_loss_attribution.csv`, one row per
(suite, policy, repeat, user_task_id) with a single categorical `category` column.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from analysis.blogfigs import palette

_SUITES = ["banking", "travel"]
_POLICIES = ["strict", "targeted"]
_REPEATS = ["0", "1"]

# Stacking order, left to right: (category column, color role, legend label).
_SEGMENTS = [
    ("unaffected", "completed", "completed"),
    ("blocked_but_recovered", "primary", "blocked but scored complete"),
    ("policy_caused_loss", "loss_blocked", "lost to a block"),
    ("run_variance", "loss_other", "lost without a block"),
    ("reverse_variance", "attention", "passed only under policy"),
    ("model_limitation", "baseline", "failed undefended too"),
]
_CATEGORY_NAMES = {seg[0] for seg in _SEGMENTS}

_TOTAL = {"banking": 16, "travel": 20}


def _read_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def _aggregate(rows: list[dict]) -> dict[tuple[str, str, str], Counter]:
    counts: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for r in rows:
        key = (r["suite"], r["policy"], r["repeat"])
        category = r["category"]
        if category not in _CATEGORY_NAMES:
            raise ValueError(f"unexpected category {category!r} in utility_loss_attribution.csv row {r}")
        counts[key][category] += 1

    for (suite, _policy, _repeat), c in counts.items():
        total = sum(c[seg[0]] for seg in _SEGMENTS)
        assert total == _TOTAL[suite], (
            f"segments for {(suite, _policy, _repeat)} sum to {total}, expected {_TOTAL[suite]}"
        )

    banking_run_variance = [counts[("banking", p, r)]["run_variance"] for p in _POLICIES for r in _REPEATS]
    assert all(v == 0 for v in banking_run_variance), (
        "banking is supposed to lose nothing without a block in every configuration: "
        f"got run_variance={banking_run_variance}"
    )
    travel_run_variance = [counts[("travel", p, r)]["run_variance"] for p in _POLICIES for r in _REPEATS]
    assert all(v > 0 for v in travel_run_variance), (
        "travel is supposed to lose something without a block in every configuration: "
        f"got run_variance={travel_run_variance}"
    )

    return counts


def _order() -> list[tuple[str, str, str]]:
    return [(s, p, r) for s in _SUITES for p in _POLICIES for r in _REPEATS]


def _write_data_csv(out_path: Path, counts: dict) -> None:
    keys = _order()
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        cols = ["suite", "policy", "repeat"] + [seg[0] for seg in _SEGMENTS] + ["total"]
        w.writerow(cols)
        for key in keys:
            c = counts[key]
            values = [c[seg[0]] for seg in _SEGMENTS]
            w.writerow(list(key) + values + [sum(values)])


def _draw(c: dict, counts: dict) -> plt.Figure:
    palette.apply_rcparams(c)
    fig, ax = plt.subplots(figsize=(palette.FIG_WIDTH_IN, 3.8), dpi=palette.DPI)

    keys = _order()
    n = len(keys)
    y = list(range(n))[::-1]  # first config at top
    tick_labels = [f"{s}\n{p} r{r}" for s, p, r in keys]

    ax.set_xlim(0, 20)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_yticks(y)
    ax.set_yticklabels(tick_labels, fontsize=8)
    ax.set_xticks([0, 5, 10, 15, 20])
    ax.tick_params(left=False, bottom=False)
    ax.xaxis.grid(True, color=c["axis"], linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    palette.strip_spines(ax, keep_left=False, keep_bottom=True)
    ax.text(
        0.5,
        -0.14,
        "benign tasks",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=10,
        color=c["text"],
    )

    for yi, key in zip(y, keys):
        counter = counts[key]
        left = 0.0
        for col, role, _label in _SEGMENTS:
            width = counter[col]
            if width == 0:
                left += width
                continue
            ax.barh(yi, width, left=left, height=0.62, color=c[role], zorder=2)
            label_color = c[f"on_{role}"]
            if width >= 1.2:
                ax.text(
                    left + width / 2,
                    yi,
                    str(width),
                    ha="center",
                    va="center",
                    fontsize=8.5,
                    color=label_color,
                )
            left += width

    handles = [Patch(facecolor=c[role], edgecolor="none", label=label) for _col, role, label in _SEGMENTS]
    fig.legend(
        handles=handles,
        loc="upper center",
        ncol=len(_SEGMENTS),
        bbox_to_anchor=(0.5, 0.99),
        frameon=False,
        fontsize=6.8,
        columnspacing=0.8,
        handlelength=1.1,
        handletextpad=0.4,
    )

    fig.subplots_adjust(left=0.16, right=0.97, top=0.76, bottom=0.16)
    return fig


def write_figure(csv_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_rows(csv_path)
    counts = _aggregate(rows)

    data_csv = out_dir / "figure5_data.csv"
    _write_data_csv(data_csv, counts)

    for theme, filename in (("dark", "figure5.svg"), ("light", "figure5_light.svg")):
        c = palette.palette(theme)
        fig = _draw(c, counts)
        fig.savefig(out_dir / filename, transparent=True)
        plt.close(fig)

    return data_csv
