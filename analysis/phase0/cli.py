"""Entry point: uv run python -m analysis.phase0.cli [options]

Must be run from the repo root (it imports `compare_blocking.py` by path,
and defaults its own paths relative to cwd).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from analysis.phase0.report import write_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=Path("runs/published"))
    parser.add_argument("--policies-root", type=Path, default=Path("policies"))
    parser.add_argument("--out", type=Path, default=Path("analysis_out/artifact_manifest.md"))
    parser.add_argument(
        "--suite",
        type=str,
        default=None,
        help="Suite to use for representative examples in the report (default: first suite found)",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()
    path = write_manifest(args.results_root, args.policies_root, repo_root, args.out, args.suite)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
