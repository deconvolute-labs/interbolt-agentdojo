"""Tier 3, N4: confidence bounds.

Clopper-Pearson intervals on the zero-failure results the spec's own "What is stable and what is
not" section names: block rate 1.00 (all eight rows), banking ASR_system 0/144 (all four banking
rows), and B-baseline contamination 0 (I9, once per (suite, repeat) since B is shared across
policies). Reported alongside each metric's already-observed repeat-to-repeat variance, not
instead of it, per the spec's own instruction.

Uses `scipy.stats.beta` for the exact interval (not an approximation) -- the only Tier 3 module
that needs `scipy`, synced via `uv sync --group analysis`. The CLI catches this module's
`ImportError` and skips it with a message when the optional group isn't installed; the other
eight Tier 3 items have no new dependency.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from scipy.stats import beta

from analysis.common.artifacts import discover_results, events_by_run_id, quartet_repeat_metrics, selected_run_ids
from analysis.common.casetables import Quartet

ALPHA = 0.05  # 95% two-sided Clopper-Pearson


def clopper_pearson(k: int, n: int, alpha: float = ALPHA) -> tuple[float, float]:
    """Exact two-sided (1-alpha) Clopper-Pearson interval for k successes of n trials."""
    if n <= 0:
        raise ValueError(f"clopper_pearson: n must be > 0, got {n}")
    if not (0 <= k <= n):
        raise ValueError(f"clopper_pearson: k must be in [0, n], got k={k}, n={n}")
    lower = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    upper = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return lower, upper


@dataclass(frozen=True)
class ConfidenceBoundRow:
    suite: str
    policy: str  # "" for the B-level contamination check (shared across policies, like I9)
    repeat: int
    metric: str  # "block_rate" | "asr_system" | "contamination"
    k: int
    n: int
    observed_rate: float
    ci_lower: float
    ci_upper: float
    alpha: float


def compute_rows(quartets: list[Quartet]) -> list[ConfidenceBoundRow]:
    rows: list[ConfidenceBoundRow] = []
    seen_b: set[tuple[str, int]] = set()

    for q in quartets:
        metrics = quartet_repeat_metrics(q.a.repeat_dir, q.b.repeat_dir, q.c.repeat_dir, q.d.repeat_dir, allow_dirty=True)

        k, n = metrics["taxonomy"].get("interbolt_blocked", 0), metrics["block_rate_denom"]
        if n and k == n:
            lower, upper = clopper_pearson(k, n)
            rows.append(ConfidenceBoundRow(q.suite, q.policy, q.repeat, "block_rate", k, n, k / n, lower, upper, ALPHA))

        if q.suite == "banking":
            k, n = metrics["asr_system_num"], metrics["asr_system_den"]
            if n and k == 0:
                lower, upper = clopper_pearson(k, n)
                rows.append(ConfidenceBoundRow(q.suite, q.policy, q.repeat, "asr_system", k, n, k / n, lower, upper, ALPHA))

        b_key = (q.suite, q.repeat)
        if b_key not in seen_b and q.b.pipeline_name is not None:
            seen_b.add(b_key)
            without_inj, with_inj = discover_results(q.b.repeat_dir, q.b.pipeline_name, q.b.suite, q.b.benchmark_version)
            selected = selected_run_ids(q.b.repeat_dir, without_inj, with_inj)
            n_b_decisions = sum(len(evs) for rid, evs in events_by_run_id(q.b.repeat_dir).items() if rid in selected)
            if n_b_decisions and metrics["contamination"] == 0:
                lower, upper = clopper_pearson(0, n_b_decisions)
                rows.append(ConfidenceBoundRow(q.suite, "", q.repeat, "contamination", 0, n_b_decisions, 0.0, lower, upper, ALPHA))

    rows.sort(key=lambda r: (r.suite, r.metric, r.policy, r.repeat))
    return rows


_FIELDS = ["suite", "policy", "repeat", "metric", "k", "n", "observed_rate", "ci_lower", "ci_upper", "alpha"]


def write_csv(rows: list[ConfidenceBoundRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [r.suite, r.policy, r.repeat, r.metric, r.k, r.n, f"{r.observed_rate:.4f}",
                 f"{r.ci_lower:.4f}", f"{r.ci_upper:.4f}", r.alpha]
            )


def render_markdown(rows: list[ConfidenceBoundRow]) -> str:
    lines = ["## N4. Confidence bounds", ""]
    lines.append(
        "Exact 95% two-sided Clopper-Pearson intervals (`scipy.stats.beta`), applied only to the "
        "already-established zero-failure results -- reported alongside each metric's own "
        "observed repeat-to-repeat variance (see the headline table in `analysis/verification.md`), "
        "not instead of it. `contamination` is reported once per (suite, repeat) -- B is shared "
        "across policies, same scope I9 uses."
    )
    lines.append("")
    lines.append("| Suite | Policy | Repeat | Metric | k/n | Observed | 95% CI |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r.suite} | {r.policy or '(shared)'} | {r.repeat} | {r.metric} | {r.k}/{r.n} | "
            f"{r.observed_rate:.3f} | [{r.ci_lower:.4f}, {r.ci_upper:.4f}] |"
        )
    lines.append("")
    return "\n".join(lines)
