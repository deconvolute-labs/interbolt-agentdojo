"""Shared x-axis chrome for figures 2 and 3: a vertical rule between suites plus small
"banking"/"travel" labels above the axis. Figure 3's spec text says "as in Figure 2" -- this is
that shared piece, so it isn't duplicated between the two modules.
"""

from __future__ import annotations


def draw_suite_separator(ax, split_x: float, *, axis_color: str, muted_color: str) -> None:
    ax.axvline(split_x, color=axis_color, linewidth=1.0, zorder=1)


def label_suites(ax, banking_center: float, travel_center: float, *, muted_color: str) -> None:
    ax.text(
        banking_center,
        1.0,
        "banking",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="bottom",
        fontsize=8.5,
        color=muted_color,
    )
    ax.text(
        travel_center,
        1.0,
        "travel",
        transform=ax.get_xaxis_transform(),
        ha="center",
        va="bottom",
        fontsize=8.5,
        color=muted_color,
    )
