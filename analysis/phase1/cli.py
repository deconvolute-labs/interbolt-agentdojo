"""Entry point: uv run python -m analysis.phase1.cli [options]

Builds the two case-level tables (`gated_sink_cases.csv`, `utility_per_task.csv`) and
runs the Phase 1 integrity checks (I1-I10) against them, writing
`integrity_checks.csv` + a markdown summary. Must be run from the repo root, same as
`analysis.phase0.cli`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from analysis.common.casetables import (
    build_attacked_case_table,
    build_benign_task_table,
    build_quartets,
    write_attacked_csv,
    write_benign_csv,
)
from analysis.common.discovery import find_run_records
from analysis.phase1.checks import run_all_checks
from analysis.phase1.report import render_markdown, write_checks_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("runs/published"))
    parser.add_argument("--policies-root", type=Path, default=Path("policies"))
    parser.add_argument("--out-dir", type=Path, default=Path("analysis_out"))
    args = parser.parse_args()

    records = find_run_records(args.results_root, args.policies_root)
    quartets = build_quartets(records)

    attacked, missing_from_d = build_attacked_case_table(quartets)
    benign, missing_from_c = build_benign_task_table(quartets)

    write_attacked_csv(attacked, args.out_dir / "gated_sink_cases.csv")
    print(f"wrote {args.out_dir / 'gated_sink_cases.csv'} ({len(attacked)} rows, {len(missing_from_d)} missing-from-D)")
    write_benign_csv(benign, args.out_dir / "utility_per_task.csv")
    print(f"wrote {args.out_dir / 'utility_per_task.csv'} ({len(benign)} rows, {len(missing_from_c)} missing-from-C)")

    results = run_all_checks(quartets, attacked, missing_from_d)
    write_checks_csv(results, args.out_dir / "integrity_checks.csv")
    print(f"wrote {args.out_dir / 'integrity_checks.csv'} ({len(results)} rows)")

    md_path = args.out_dir / "phase1_integrity_checks.md"
    md_path.write_text(render_markdown(results) + "\n")
    print(f"wrote {md_path}")

    failures = [r for r in results if r.status in ("FAIL", "WARN")]
    if failures:
        print(f"** {len(failures)} FAIL/WARN result(s) -- see {md_path} **")


if __name__ == "__main__":
    main()
