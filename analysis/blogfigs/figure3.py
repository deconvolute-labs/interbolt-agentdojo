"""Figure 3: security and utility, before and after.

Left panel -- attack success rate, undefended (asr_model) versus under policy (asr_system), not
deduplicated: each defended bar needs its own baseline beside it even though asr_model repeats
within a suite/repeat. Right panel -- benign utility, undefended ceiling (u_ceiling) versus under
policy (u_policy). Eight configurations: suite x policy x repeat, banking then travel, strict then
targeted, repeat 0 then 1. Travel's u_ceiling swing between repeats is the point, so repeats are
never averaged.

Source: `runs/published/results.csv`.
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from analysis.blogfigs import _layout, palette

_SUITES = ["banking", "travel"]
_POLICIES = ["strict", "targeted"]
_REPEATS = ["0", "1"]
_BAR_WIDTH = 0.32


def _read_rows(csv_path: Path) -> list[dict]:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def _order(rows: list[dict]) -> list[dict]:
    by_key = {(r["suite"], r["policy"], r["repeat"]): r for r in rows}
    ordered = [by_key[(s, p, r)] for s in _SUITES for p in _POLICIES for r in _REPEATS]
    assert len(ordered) == 8 == len(rows), f"expected exactly 8 configurations, found {len(rows)}"
    return ordered


def _write_data_csv(out_path: Path, rows: list[dict]) -> None:
    cols = [
        "suite",
        "policy",
        "repeat",
        "asr_model",
        "asr_model_num",
        "asr_model_den",
        "asr_system",
        "asr_system_num",
        "asr_system_den",
        "u_ceiling",
        "u_ceiling_num",
        "u_ceiling_den",
        "u_policy",
        "u_policy_num",
        "u_policy_den",
    ]
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])


def _draw(c: dict, rows: list[dict]) -> plt.Figure:
    palette.apply_rcparams(c)
    fig, (ax_asr, ax_u) = plt.subplots(1, 2, figsize=(palette.FIG_WIDTH_IN, 3.6), dpi=palette.DPI)

    n = len(rows)
    x = list(range(n))
    tick_labels = [f"{r['policy']}\nr{r['repeat']}" for r in rows]

    for ax in (ax_asr, ax_u):
        ax.set_xlim(-0.6, n - 0.4)
        ax.set_xticks(x)
        ax.set_xticklabels(tick_labels, fontsize=7.2)
        ax.tick_params(left=False, bottom=False)
        split_x = 3.5  # between banking's repeat 1 and travel's repeat 0
        _layout.draw_suite_separator(ax, split_x, axis_color=c["axis"], muted_color=c["muted"])
        _layout.label_suites(ax, 1.5, 5.5, muted_color=c["muted"])
        palette.strip_spines(ax, keep_left=True, keep_bottom=False)

    def _paired_bars(ax, before_num_key, before_den_key, after_num_key, after_den_key, ymax, ylabel):
        ax.set_ylim(0, ymax)
        for xi, r in zip(x, rows):
            bnum, bden = int(r[before_num_key]), int(r[before_den_key])
            anum, aden = int(r[after_num_key]), int(r[after_den_key])
            before_rate = bnum / bden
            after_rate = anum / aden
            bx = xi - _BAR_WIDTH / 2
            ax_bar = xi + _BAR_WIDTH / 2
            ax.bar(bx, before_rate, width=_BAR_WIDTH, color=c["baseline"], zorder=2)
            ax.bar(ax_bar, after_rate, width=_BAR_WIDTH, color=c["primary"], zorder=2)
            ax.text(
                bx,
                before_rate + ymax * 0.015,
                f"{bnum}/{bden}",
                ha="center",
                va="bottom",
                fontsize=7,
                family="monospace",
                color=c["muted"],
            )
            ax.text(
                ax_bar,
                after_rate + ymax * 0.015,
                f"{anum}/{aden}",
                ha="center",
                va="bottom",
                fontsize=7,
                family="monospace",
                color=c["muted"],
            )
        ax.text(
            0.5,
            -0.28,
            ylabel,
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=10,
            color=c["text"],
        )

    _paired_bars(ax_asr, "asr_model_num", "asr_model_den", "asr_system_num", "asr_system_den", 0.6, "attack success rate")
    _paired_bars(ax_u, "u_ceiling_num", "u_ceiling_den", "u_policy_num", "u_policy_den", 1.0, "benign tasks completed")

    handles = [
        Patch(facecolor=c["baseline"], edgecolor="none", label="undefended"),
        Patch(facecolor=c["primary"], edgecolor="none", label="under policy"),
    ]
    fig.legend(handles=handles, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.02), frameon=False, fontsize=9)

    fig.subplots_adjust(left=0.07, right=0.98, top=0.82, bottom=0.24, wspace=0.18)
    return fig


def write_figure(csv_path: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _order(_read_rows(csv_path))

    data_csv = out_dir / "figure3_data.csv"
    _write_data_csv(data_csv, rows)

    for theme, filename in (("dark", "figure3.svg"), ("light", "figure3_light.svg")):
        c = palette.palette(theme)
        fig = _draw(c, rows)
        fig.savefig(out_dir / filename, transparent=True)
        plt.close(fig)

    return data_csv
