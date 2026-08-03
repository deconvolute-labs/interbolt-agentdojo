"""Entry point: uv run python -m analysis.tier2.cli [options]

Tier 2 of `analysis/verification.md`: T2.1 (strict vs targeted divergence), T2.2 (shared sinks),
T2.3 (policy surface coverage), T2.4 (case study export), T2.5 (named variance cases). Must be
run from the repo root, same as analysis.phase0.cli / analysis.phase1.cli / analysis.phase2b.cli.

`case_studies.md` is written one directory above `--out-dir` (default `analysis_out/tier2` ->
`analysis_out/case_studies.md`), matching the spec's Phase 5 file tree.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from analysis.common.casetables import build_attacked_case_table, build_benign_task_table, build_quartets
from analysis.common.discovery import find_run_records
from analysis.tier2 import case_studies, divergence, named_variance_cases, policy_coverage, shared_sinks


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

    # T2.1
    attacked_alignments, attacked_div_rows = divergence.compute_attacked(quartets)
    divergence.write_csv(attacked_div_rows, args.out_dir / "divergence_strict_vs_targeted.csv")
    print(f"wrote {args.out_dir / 'divergence_strict_vs_targeted.csv'} ({len(attacked_div_rows)} rows)")
    benign_alignments, benign_div_rows = divergence.compute_benign(quartets)
    divergence.write_csv(benign_div_rows, args.out_dir / "divergence_benign.csv")
    print(f"wrote {args.out_dir / 'divergence_benign.csv'} ({len(benign_div_rows)} rows)")
    (args.out_dir / "divergence.md").write_text(
        divergence.render_markdown(attacked_alignments, attacked_div_rows, benign_alignments, benign_div_rows) + "\n"
    )
    print(f"wrote {args.out_dir / 'divergence.md'}")

    # T2.2
    sink_rows = shared_sinks.compute_rows(records)
    shared_sinks.write_csv(sink_rows, args.out_dir / "shared_sinks.csv")
    print(f"wrote {args.out_dir / 'shared_sinks.csv'} ({len(sink_rows)} rows)")
    (args.out_dir / "shared_sinks.md").write_text(shared_sinks.render_markdown(sink_rows) + "\n")
    print(f"wrote {args.out_dir / 'shared_sinks.md'}")

    # T2.3
    coverage_rows, coverage_warnings, coverage_eval_errors = policy_coverage.compute_rows(quartets, attacked)
    policy_coverage.write_csv(coverage_rows, args.out_dir / "policy_coverage.csv")
    print(f"wrote {args.out_dir / 'policy_coverage.csv'} ({len(coverage_rows)} rows, {len(coverage_warnings)} warnings)")
    (args.out_dir / "policy_coverage.md").write_text(
        policy_coverage.render_markdown(coverage_rows, coverage_warnings, coverage_eval_errors, quartets, attacked, records) + "\n"
    )
    print(f"wrote {args.out_dir / 'policy_coverage.md'}")

    # T2.4 -- one level above --out-dir, per the spec's Phase 5 tree.
    case_studies_path = args.out_dir.parent / "case_studies.md" if args.out_dir.name == "tier2" else args.out_dir / "case_studies.md"
    case_studies_path.write_text(case_studies.build_markdown(quartets, records, attacked) + "\n")
    print(f"wrote {case_studies_path}")

    # T2.5
    variance_rows = named_variance_cases.compute_rows(quartets, benign)
    named_variance_cases.write_csv(variance_rows, args.out_dir / "named_variance_cases.csv")
    print(f"wrote {args.out_dir / 'named_variance_cases.csv'} ({len(variance_rows)} rows)")
    (args.out_dir / "named_variance_cases.md").write_text(named_variance_cases.render_markdown(variance_rows) + "\n")
    print(f"wrote {args.out_dir / 'named_variance_cases.md'}")


if __name__ == "__main__":
    main()
