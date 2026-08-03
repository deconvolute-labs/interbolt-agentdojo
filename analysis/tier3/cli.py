"""Entry point: uv run python -m analysis.tier3.cli [options]

Tier 3 of `analysis/verification.md`: 2.8 (suite metadata), N5 (decision determinism), N8 + N9
remainder (positional distributions, plus the N8 taint-onset figure), N10 (trajectory cost), N13
(cross-suite consistency), 2.5 (read-before-write), 2.7 (approval residual proxy), N4 (confidence
bounds). Must be run from the repo root, same as analysis.phase0.cli / analysis.phase1.cli /
analysis.phase2b.cli / analysis.tier2.cli.

N8's figure needs `matplotlib` and N4 needs `scipy`, both in the optional `analysis` dependency
group (`uv sync --group analysis`). The other seven items have no new dependency; if the optional
group isn't installed, this CLI skips just those two pieces with a clear message and still
completes the rest.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from analysis.common.casetables import build_attacked_case_table, build_benign_task_table, build_quartets
from analysis.common.discovery import find_run_records
from analysis.tier3 import (
    approval_residual,
    cross_suite_consistency,
    decision_determinism,
    positional_distributions,
    read_before_write,
    suite_metadata,
    trajectory_cost,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-root", type=Path, default=Path("runs/published"))
    parser.add_argument("--policies-root", type=Path, default=Path("policies"))
    parser.add_argument("--out-dir", type=Path, default=Path("analysis_out"))
    parser.add_argument("--figures-dir", type=Path, default=Path("analysis_out/figures"))
    args = parser.parse_args()

    records = find_run_records(args.results_root, args.policies_root)
    quartets = build_quartets(records)
    attacked, _ = build_attacked_case_table(quartets)
    benign, _ = build_benign_task_table(quartets)

    # 2.8
    metadata_rows = suite_metadata.compute_rows()
    suite_metadata.write_csv(metadata_rows, args.out_dir / "suite_metadata.csv")
    print(f"wrote {args.out_dir / 'suite_metadata.csv'} ({len(metadata_rows)} rows)")
    (args.out_dir / "suite_metadata.md").write_text(suite_metadata.render_markdown(metadata_rows) + "\n")
    print(f"wrote {args.out_dir / 'suite_metadata.md'}")

    # N5
    determinism_rows = decision_determinism.compute_rows(quartets)
    decision_determinism.write_csv(determinism_rows, args.out_dir / "decision_determinism.csv")
    print(f"wrote {args.out_dir / 'decision_determinism.csv'} ({len(determinism_rows)} rows)")
    (args.out_dir / "decision_determinism.md").write_text(decision_determinism.render_markdown(determinism_rows) + "\n")
    print(f"wrote {args.out_dir / 'decision_determinism.md'}")

    # N8 + N9 remainder
    taint_rows = positional_distributions.compute_taint_onset_rows(records)
    positional_distributions.write_taint_onset_csv(taint_rows, args.out_dir / "taint_onset.csv")
    print(f"wrote {args.out_dir / 'taint_onset.csv'} ({len(taint_rows)} rows)")
    block_pos_rows = positional_distributions.compute_block_position_rows(records)
    positional_distributions.write_block_position_csv(block_pos_rows, args.out_dir / "block_position_fraction.csv")
    print(f"wrote {args.out_dir / 'block_position_fraction.csv'} ({len(block_pos_rows)} rows)")
    (args.out_dir / "positional_distributions.md").write_text(
        positional_distributions.render_markdown(taint_rows, block_pos_rows) + "\n"
    )
    print(f"wrote {args.out_dir / 'positional_distributions.md'}")
    try:
        fig_csv = positional_distributions.write_taint_onset_figure(taint_rows, args.figures_dir)
        print(f"wrote {args.figures_dir / 'taint_onset_histogram.svg'}, .png, and {fig_csv}")
    except ImportError as exc:
        print(f"** skipped N8 figure: matplotlib not installed ({exc}) -- run `uv sync --group analysis` **")

    # N10
    cost_attacked_rows = trajectory_cost.compute_attacked_rows(quartets)
    cost_benign_rows = trajectory_cost.compute_benign_rows(quartets)
    trajectory_cost.write_csv(cost_attacked_rows, args.out_dir / "trajectory_cost_attacked.csv")
    print(f"wrote {args.out_dir / 'trajectory_cost_attacked.csv'} ({len(cost_attacked_rows)} rows)")
    trajectory_cost.write_csv(cost_benign_rows, args.out_dir / "trajectory_cost_benign.csv")
    print(f"wrote {args.out_dir / 'trajectory_cost_benign.csv'} ({len(cost_benign_rows)} rows)")
    (args.out_dir / "trajectory_cost.md").write_text(
        trajectory_cost.render_markdown(cost_attacked_rows, cost_benign_rows, quartets) + "\n"
    )
    print(f"wrote {args.out_dir / 'trajectory_cost.md'}")

    # N13
    cross_suite_rows = cross_suite_consistency.compute_rows(quartets, attacked, taint_rows)
    cross_suite_consistency.write_csv(cross_suite_rows, args.out_dir / "cross_suite_consistency.csv")
    print(f"wrote {args.out_dir / 'cross_suite_consistency.csv'} ({len(cross_suite_rows)} rows)")
    (args.out_dir / "cross_suite_consistency.md").write_text(cross_suite_consistency.render_markdown(cross_suite_rows) + "\n")
    print(f"wrote {args.out_dir / 'cross_suite_consistency.md'}")

    # 2.5
    rbw_rows = read_before_write.compute_rows(records)
    read_before_write.write_csv(rbw_rows, args.out_dir / "read_before_write.csv")
    print(f"wrote {args.out_dir / 'read_before_write.csv'} ({len(rbw_rows)} rows)")
    (args.out_dir / "read_before_write.md").write_text(read_before_write.render_markdown(rbw_rows) + "\n")
    print(f"wrote {args.out_dir / 'read_before_write.md'}")

    # 2.7
    approval_rows = approval_residual.compute_rows(records)
    approval_residual.write_csv(approval_rows, args.out_dir / "approval_residual.csv")
    print(f"wrote {args.out_dir / 'approval_residual.csv'} ({len(approval_rows)} rows)")
    (args.out_dir / "approval_residual.md").write_text(approval_residual.render_markdown(approval_rows) + "\n")
    print(f"wrote {args.out_dir / 'approval_residual.md'}")

    # N4
    try:
        from analysis.tier3 import confidence_bounds

        bound_rows = confidence_bounds.compute_rows(quartets)
        confidence_bounds.write_csv(bound_rows, args.out_dir / "confidence_bounds.csv")
        print(f"wrote {args.out_dir / 'confidence_bounds.csv'} ({len(bound_rows)} rows)")
        (args.out_dir / "confidence_bounds.md").write_text(confidence_bounds.render_markdown(bound_rows) + "\n")
        print(f"wrote {args.out_dir / 'confidence_bounds.md'}")
    except ImportError as exc:
        print(f"** skipped N4 confidence_bounds: scipy not installed ({exc}) -- run `uv sync --group analysis` **")


if __name__ == "__main__":
    main()
