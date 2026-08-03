"""Entry point: uv run python -m analysis.phase2b.cli [options]

Tier 1 of Phase 2B: N14 (pseudo-case standalone achievability), N1 + N6 (joined,
per-injection-task block rate and refusal variance), N2 (utility loss attribution).
Must be run from the repo root, same as analysis.phase0.cli / analysis.phase1.cli.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from analysis.common.casetables import build_attacked_case_table, build_benign_task_table, build_quartets
from analysis.common.discovery import find_run_records
from analysis.phase2b import per_injection_task, pseudo_case_standalone, utility_loss_attribution


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("runs/published"))
    parser.add_argument("--policies-root", type=Path, default=Path("policies"))
    parser.add_argument("--out-dir", type=Path, default=Path("analysis_out"))
    args = parser.parse_args()

    records = find_run_records(args.results_root, args.policies_root)
    quartets = build_quartets(records)
    attacked, _ = build_attacked_case_table(quartets)
    benign, _ = build_benign_task_table(quartets)

    # N14
    pseudo_rows = pseudo_case_standalone.compute_rows(records)
    pseudo_case_standalone.write_csv(pseudo_rows, args.out_dir / "pseudo_case_standalone.csv")
    print(f"wrote {args.out_dir / 'pseudo_case_standalone.csv'}")
    (args.out_dir / "n14_pseudo_case_standalone.md").write_text(
        pseudo_case_standalone.render_markdown(pseudo_rows) + "\n"
    )
    print(f"wrote {args.out_dir / 'n14_pseudo_case_standalone.md'}")

    # N1 + N6
    injection_rows = per_injection_task.compute_rows(attacked, quartets, records)
    per_injection_task.write_csv(injection_rows, args.out_dir / "per_injection_task.csv")
    print(f"wrote {args.out_dir / 'per_injection_task.csv'} ({len(injection_rows)} rows)")
    (args.out_dir / "n1_n6_per_injection_task.md").write_text(
        per_injection_task.render_markdown(injection_rows) + "\n"
    )
    print(f"wrote {args.out_dir / 'n1_n6_per_injection_task.md'}")

    # N2
    loss_rows = utility_loss_attribution.compute_rows(benign)
    utility_loss_attribution.write_csv(loss_rows, args.out_dir / "utility_loss_attribution.csv")
    print(f"wrote {args.out_dir / 'utility_loss_attribution.csv'} ({len(loss_rows)} rows)")
    (args.out_dir / "n2_utility_loss_attribution.md").write_text(
        utility_loss_attribution.render_markdown(loss_rows) + "\n"
    )
    print(f"wrote {args.out_dir / 'n2_utility_loss_attribution.md'}")


if __name__ == "__main__":
    main()
