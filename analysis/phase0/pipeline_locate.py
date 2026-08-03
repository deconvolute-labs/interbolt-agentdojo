"""Spec item 5: locate the existing analysis pipeline and its entry point."""

from __future__ import annotations

from pathlib import Path

import interbolt_agentdojo.compute_results as compute_results


def render_pipeline_locate_section(repo_root: Path) -> str:
    lines = ["## 5. Existing analysis pipeline", ""]
    module_path = Path(compute_results.__file__)
    lines.append(
        f"**`{module_path.relative_to(repo_root) if module_path.is_relative_to(repo_root) else module_path}`** "
        f"(imported live as `interbolt_agentdojo.compute_results`, `__file__` printed above so this can't drift)."
    )
    lines.append("")
    lines.append(
        "This is the pipeline that produces each suite's `runs/published/<suite>/results.csv` "
        "(one file per suite, accumulating one row per repeat per policy via `--csv-out`) -- "
        "confirmed by re-running its quartet mode against `runs/published/` and reproducing the "
        "published banking rows exactly (see the plan's Verification section)."
    )
    lines.append("")
    lines.append("**Entry point** (live-introspected `argparse` help, so this text can't go stale):")
    lines.append("```")
    lines.append(compute_results.build_parser().format_help().rstrip())
    lines.append("```")
    lines.append("")
    lines.append("**Verified-working quartet invocation** (banking, targeted):")
    lines.append("```bash")
    lines.append(
        "uv run python -m interbolt_agentdojo.compute_results \\\n"
        "  --ceiling runs/published/banking/A_ceiling \\\n"
        "  --asr-model runs/published/banking/B_asr_model \\\n"
        "  --utility runs/published/banking/C_utility_targeted \\\n"
        "  --asr-system runs/published/banking/D_asr_system_targeted \\\n"
        "  --csv-out runs/published/banking/results.csv \\\n"
        "  --allow-dirty"
    )
    lines.append("```")
    lines.append("")
    lines.append(
        "**Not the source of the CSV** (contrary to `analysis/verification.md`'s framing that "
        "\"these pipelines are the scripts in the root of the project\"): `compare_blocking.py` "
        "(repo root) compares policy enforcement decisions between two runs via "
        "`interbolt_events.jsonl` + `run_index.jsonl`; `compare_utility_security.py` (repo root) "
        "compares AgentDojo's own `utility`/`security` booleans between two runs by walking "
        "directory structure. Both are secondary, ad-hoc comparison tools that this Phase 0 code "
        "reuses/cross-checks against (see §3), not the pipeline that produced the summary CSV."
    )
    return "\n".join(lines)
