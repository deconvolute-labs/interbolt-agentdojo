"""Entry point: uv run python -m analysis.phase4.cli [options]

Phase 4 of `analysis/verification.md`: the claims ledger. Resolves every claim in the spec's two
Phase 4 tables against what phase0/phase1/phase2b/tier2/tier3 already computed under
`--analysis-out-dir`. Must be run from the repo root, after those phases -- see each `FileNotFoundError`
message for which CLI to run first if an artifact is missing.

Unlike every other phase, this one has no CSV output -- Phase 5's file tree lists only the two
`.md` files below, both at the top level of `--out-dir` (default `analysis_out`), matching
`case_studies.md`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import agentdojo

from analysis.phase4 import claims
from analysis.phase4.checks import compute_results, render_check_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-root", type=Path, default=Path("runs/published"))
    parser.add_argument("--analysis-out-dir", type=Path, default=Path("analysis_out"))
    parser.add_argument("--out-dir", type=Path, default=Path("analysis_out"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    candidate_path = args.out_dir / "candidate_claims.md"
    candidate_path.write_text(claims.render_candidate_markdown())
    print(f"wrote {candidate_path} ({len(claims.ALL_CLAIMS)} claims)")

    agentdojo_root = Path(agentdojo.__file__).parent
    results = compute_results(args.results_root, args.analysis_out_dir, agentdojo_root)
    check_path = args.out_dir / "claims_check.md"
    check_path.write_text(render_check_markdown(results))
    print(f"wrote {check_path} ({len(results)} claims resolved)")


if __name__ == "__main__":
    main()
