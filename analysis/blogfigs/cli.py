"""Entry point: uv run python -m analysis.blogfigs.cli [options]

Figures 2-5 for the blog post, per `analysis/final_figure_spec.md`. Figures 2/3/5 are matplotlib
plots read straight from pre-computed CSVs; Figure 4 is a hand-drawn SVG diagram built from the
two raw AgentDojo trace JSONs for CS1. Must be run from the repo root, since all paths (including
the two raw run JSONs Figure 4 reads) are relative to it.

Default --out-dir is the sibling website repo's public image directory, matching the paths already
hardcoded into the blog post's mdx.
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_OUT_DIR = Path("./analysis_out/blogfigs/provenance-agentdojo-benchmark")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-injection-task-csv", type=Path, default=Path("analysis_out/phase2b/per_injection_task.csv"))
    parser.add_argument("--results-csv", type=Path, default=Path("runs/published/results.csv"))
    parser.add_argument(
        "--utility-loss-csv", type=Path, default=Path("analysis_out/phase2b/utility_loss_attribution.csv")
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    try:
        import matplotlib  # noqa: F401
    except ImportError as exc:
        print(f"** skipped figures 2/3/5: matplotlib not installed ({exc}) -- run `uv sync --group analysis` **")
    else:
        from analysis.blogfigs import figure2, figure3, figure5

        csv_out = figure2.write_figure(args.per_injection_task_csv, args.out_dir)
        print(f"wrote {args.out_dir / 'figure2.svg'}, figure2_light.svg, and {csv_out}")

        csv_out = figure3.write_figure(args.results_csv, args.out_dir)
        print(f"wrote {args.out_dir / 'figure3.svg'}, figure3_light.svg, and {csv_out}")

        csv_out = figure5.write_figure(args.utility_loss_csv, args.out_dir)
        print(f"wrote {args.out_dir / 'figure5.svg'}, figure5_light.svg, and {csv_out}")

    from analysis.blogfigs import figure4

    light_path, dark_path, csv_out = figure4.write_figure(args.out_dir)
    print(f"wrote {dark_path}, {light_path}, and {csv_out}")


if __name__ == "__main__":
    main()
