"""Assembles Phase 0's findings into `analysis_out/artifact_manifest.md`.

Deterministic by construction: no wall-clock timestamp is embedded (so two
runs against the same tree are byte-for-byte identical, per the eventual
Phase 5 reproducibility requirement), and every section sorts its inputs
before rendering.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from analysis.common.discovery import find_run_records
from analysis.phase0.anomalies import render_anomalies_section
from analysis.phase0.inventory import render_file_type_samples, render_tree_section
from analysis.phase0.join_keys import render_join_key_matrix
from analysis.phase0.pipeline_locate import render_pipeline_locate_section
from analysis.phase0.scoring_source import render_scoring_source_section


def _render_run_metadata(results_root: Path, policies_root: Path, n_records: int) -> str:
    lines = ["## 0. Run metadata", ""]
    lines.append(f"- Results root: `{results_root}`")
    lines.append(f"- Policies root: `{policies_root}`")
    lines.append(f"- Runs discovered (by content, via `run_manifest.json`): {n_records}")
    lines.append(f"- Python: `{sys.version.split()[0]}` on `{platform.platform()}`")
    lines.append(
        "- No wall-clock timestamp is embedded in this file by design, so re-running "
        "against an unchanged tree produces a byte-identical manifest (see Phase 0's "
        "verification: idempotency check)."
    )
    return "\n".join(lines)


def build_manifest(results_root: Path, policies_root: Path, repo_root: Path) -> str:
    """`results_root`/`policies_root` are expected relative to `repo_root` (the cwd);
    kept as given so paths rendered into the manifest match what a reader would
    type at the repo root, rather than being silently rewritten absolute/relative.
    """
    records = find_run_records(results_root, policies_root)
    summary_csv = results_root / "AgentDojo-Interbolt-Benchmark.csv"

    sections = [
        "# Artifact manifest",
        "",
        (
            "Phase 0 of `analysis/verification.md`. Every number below is computed live from "
            "`runs/published/` and `policies/` at generation time -- nothing here is a literal "
            "transcription of prior exploration. Findings are report-only: nothing in this phase "
            "moves files, rewrites manifests, or fixes anomalies."
        ),
        "",
        _render_run_metadata(results_root, policies_root, len(records)),
        "",
        render_tree_section(results_root, max_depth=4),
        "",
        render_file_type_samples(records, policies_root, summary_csv),
        "",
        render_join_key_matrix(records, repo_root),
        "",
        render_scoring_source_section(records),
        "",
        render_pipeline_locate_section(repo_root),
        "",
        render_anomalies_section(records, results_root, repo_root),
        "",
    ]
    return "\n".join(sections) + "\n"


def write_manifest(results_root: Path, policies_root: Path, repo_root: Path, out_path: Path) -> Path:
    content = build_manifest(results_root, policies_root, repo_root)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    return out_path
