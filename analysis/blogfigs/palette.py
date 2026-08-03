"""Palette and chrome shared by figures 2, 3, 4, 5, per `analysis/final_figure_spec.md`.

Exact role colors from the spec's palette table -- not the site's own zinc/emerald theme (that
was `analysis/blogfigs`'s earlier, now-superseded scheme). Figure backgrounds are transparent in
both themes (`savefig(transparent=True)`), so `figure.facecolor`/`axes.facecolor` are deliberately
left unset here rather than pinned to an opaque color.
"""

from __future__ import annotations

import logging

import matplotlib

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

LIGHT = dict(
    primary="#1d4ed8",
    baseline="#94a3b8",
    attention="#b45309",
    loss_blocked="#b91c1c",
    loss_other="#a16207",
    completed="#15803d",
    text="#18181b",
    muted="#71717a",
    axis="#d4d4d8",
    # Contrasting label color for text drawn on top of a solid-filled bar of the given role.
    on_primary="#ffffff",
    on_baseline="#18181b",
    on_completed="#ffffff",
    on_loss_blocked="#ffffff",
    on_loss_other="#ffffff",
    on_attention="#ffffff",
)

DARK = dict(
    primary="#60a5fa",
    baseline="#52525b",
    attention="#fbbf24",
    loss_blocked="#f87171",
    loss_other="#eab308",
    completed="#4ade80",
    text="#e4e4e7",
    muted="#a1a1aa",
    axis="#3f3f46",
    on_primary="#0b1220",
    on_baseline="#e4e4e7",
    on_completed="#0b1220",
    on_loss_blocked="#1a0505",
    on_loss_other="#1a1400",
    on_attention="#1a1400",
)

THEMES = {"light": LIGHT, "dark": DARK}

FIG_WIDTH_IN = 7.6
DPI = 100


def palette(theme: str) -> dict:
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r}, expected 'light' or 'dark'")
    return THEMES[theme]


def apply_rcparams(c: dict) -> None:
    matplotlib.rcParams.update(
        {
            "svg.fonttype": "none",
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans"],
            "font.size": 10,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "text.color": c["text"],
            "axes.edgecolor": c["axis"],
            "axes.labelcolor": c["text"],
            "xtick.color": c["muted"],
            "ytick.color": c["muted"],
        }
    )


def strip_spines(ax, *, keep_left: bool = False, keep_bottom: bool = True) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(keep_left)
    ax.spines["bottom"].set_visible(keep_bottom)
