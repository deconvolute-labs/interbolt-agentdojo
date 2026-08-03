"""Spec item 6 (missing/anomalous artifacts) and open questions 3 & 5.

Detection only -- nothing here moves files, rewrites manifests, or
substitutes a resolved path for a recorded one on disk. Findings are
reported so later phases can propagate a "provisional" flag onto any number
that depends on them.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import interbolt.constants as interbolt_constants
from agentdojo.task_suite.load_suites import get_suite

from analysis.common.artifacts import discover_results, load_jsonl, read_csv_rows
from analysis.common.discovery import (
    ROLE_A_CEILING,
    ROLE_B_ASR_MODEL,
    ROLE_C_UTILITY,
    ROLE_D_ASR_SYSTEM,
    RunRecord,
)


def _find_manifestless_dirs(results_root: Path) -> list[tuple[Path, int]]:
    """Directories under a suite dir that hold no run_manifest.json anywhere within."""
    findings = []
    for suite_dir in sorted(p for p in results_root.iterdir() if p.is_dir()):
        for child in sorted(p for p in suite_dir.iterdir() if p.is_dir()):
            if not any(child.rglob("run_manifest.json")):
                file_count = sum(1 for f in child.rglob("*") if f.is_file())
                findings.append((child, file_count))
    return findings


def _schema_version_of(path: Path) -> int | None:
    rows = load_jsonl(path)
    return rows[0].get("schema_version") if rows else None


def _expected_case_counts(suite_name: str, benchmark_version: str) -> tuple[int, int]:
    """(benign user-task count, injection-task count) for a suite/version."""
    suite = get_suite(benchmark_version, suite_name)
    return len(suite.user_tasks), len(suite.injection_tasks)


def render_anomalies_section(
    records: list[RunRecord], results_root: Path, repo_root: Path, summary_csvs: dict[str, Path]
) -> str:
    lines = ["## 6. Missing / anomalous artifacts", ""]

    # -- Empty / manifestless directories, cross-referenced against misplaced runs --
    lines.append("### Empty or manifest-less directories")
    empty_dirs = _find_manifestless_dirs(results_root)
    mismatched = [r for r in records if r.path_mismatch]
    if not empty_dirs:
        lines.append("_(none found)_")
    for path, count in empty_dirs:
        note = ""
        for r in mismatched:
            if path.name == r.expected_dir_name and path.parent == r.repeat_dir.parent.parent:
                note = (
                    f" -- **this is exactly the expected location for the "
                    f"`{r.suite}`/`{r.role}`/`{r.policy.name if r.policy else ''}` run; its actual "
                    f"data was found instead at `{r.repeat_dir}` (see mismatch table below). "
                    f"No file was moved; downstream code must use the actual path.**"
                )
        lines.append(f"- `{path}`: {count} files{note}")
    lines.append("")

    lines.append("### Directories whose content identity doesn't match their path")
    if not mismatched:
        lines.append("_(none found)_")
    for r in mismatched:
        lines.append(
            f"- `{r.repeat_dir}`: `run_manifest.json` content identifies this as "
            f"`(suite={r.suite}, role={r.role}, policy={r.policy.name if r.policy else None})`, "
            f"whose expected location is `.../{r.expected_dir_name}/repeat_N`, but the directory's "
            f"actual parent is named `{r.actual_parent_dir_name}`."
        )
    lines.append("")

    # -- Stale policy_file paths --
    lines.append("### Stale `defense.policy_file` paths (recorded path missing, resolved by content hash)")
    stale = [r for r in records if r.policy and r.policy.stale]
    unresolvable = [r for r in records if r.policy and r.policy.unresolvable]
    if not stale:
        lines.append("_(none found)_")
    for r in stale:
        lines.append(
            f"- `{r.repeat_dir}`: recorded `defense.policy_file = \"{r.policy.recorded_path}\"` "
            f"does not exist on disk; `defense.policy_sha256` resolves unambiguously to "
            f"`{r.policy.resolved_path}`. Both values reported; the recorded path was never "
            f"edited or substituted on disk."
        )
    if unresolvable:
        lines.append(
            f"**{len(unresolvable)} run(s) have a `policy_sha256` that matches no file under "
            f"the policies root at all** -- flagged as `unresolvable`, treat any number from "
            f"these runs as provisional:"
        )
        for r in unresolvable:
            lines.append(f"  - `{r.repeat_dir}` (`policy_sha256={r.policy.sha256}`)")
    lines.append("")

    # -- Interbolt event schema version split --
    lines.append("### `interbolt_events.jsonl` schema-version split")
    lines.append(
        f"Currently-installed `interbolt.constants.EVENT_SCHEMA_VERSION = {interbolt_constants.EVENT_SCHEMA_VERSION}`."
    )
    lines.append("")
    lines.append("| Suite | Role | Policy | schema_version | interbolt.version | install_mode | dirty |")
    lines.append("|---|---|---|---|---|---|---|")
    off_version_count = 0
    for r in records:
        if r.role == ROLE_A_CEILING:
            lines.append(
                f"| {r.suite} | {r.role} | | _(excluded: no policy, no `interbolt_events.jsonl`)_ | | | |"
            )
            continue
        if r.role not in (ROLE_B_ASR_MODEL, ROLE_C_UTILITY, ROLE_D_ASR_SYSTEM):
            continue
        version = _schema_version_of(r.repeat_dir / "interbolt_events.jsonl")
        ib = r.manifest.get("interbolt") or {}
        flag = ""
        if version is not None and version != interbolt_constants.EVENT_SCHEMA_VERSION:
            flag = " **← not the currently-installed schema version**"
            off_version_count += 1
        lines.append(
            f"| {r.suite} | {r.role} | {r.policy.name if r.policy else ''} | {version}{flag} | "
            f"{ib.get('version')} | {ib.get('install_mode')} | {ib.get('dirty')} |"
        )
    lines.append("")
    if off_version_count:
        lines.append(
            f"** WARNING: {off_version_count} run(s) used a schema/interbolt-build different from "
            f"the currently-installed one.** The spec asks to \"fail loudly on an unrecognized "
            f"[schema] value\" -- Phase 0 treats that as this prominent warning (a hard crash here "
            f"would prevent the manifest itself from being produced); a later phase that "
            f"*interprets* schema-dependent fields (e.g. `policy_fingerprint`, only present in "
            f"schema ≥ 9) should raise instead of silently proceeding. In this dataset, banking's "
            f"`B_asr_model`/`C_utility_targeted`/`D_asr_system_targeted` used interbolt 0.1.1 "
            f"(editable) while `C_utility_strict`/`D_asr_system_strict` used 0.2.0 (installed) -- "
            f"so banking's strict-vs-targeted comparison spans two different interbolt builds. "
            f"Travel is uniform (all schema 9)."
        )
    lines.append("")

    # -- Duplicate run_index rows --
    lines.append("### Duplicate `run_index.jsonl` rows")
    any_dupes = False
    for r in records:
        if r.role not in (ROLE_B_ASR_MODEL, ROLE_D_ASR_SYSTEM):
            continue
        rows = load_jsonl(r.repeat_dir / "run_index.jsonl")
        keys = [(row.get("user_task_id"), row.get("injection_task_id")) for row in rows]
        dupes = {k: c for k, c in Counter(keys).items() if c > 1}
        if dupes:
            any_dupes = True
            lines.append(f"- `{r.repeat_dir}`: {len(rows)} rows, {len(dupes)} duplicated case key(s): {dupes}")
    if not any_dupes:
        lines.append("_(none found)_")
    lines.append("")

    # -- Result-file counts vs. suite-derived expectations --
    lines.append("### Result-file counts vs. suite-derived expectations")
    lines.append("| Suite | Role | Policy | Benign count | Attacked count | Expected benign | Expected attacked | Match? |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in records:
        if r.pipeline_name is None:
            continue
        without_injections, with_injections = discover_results(r.repeat_dir, r.pipeline_name, r.suite, r.benchmark_version)
        n_user_tasks, n_injection_tasks = _expected_case_counts(r.suite, r.benchmark_version)
        if r.role in (ROLE_A_CEILING, ROLE_C_UTILITY):
            expected_benign, expected_attacked = n_user_tasks, 0
        else:
            expected_benign, expected_attacked = 0, n_user_tasks * n_injection_tasks
        match = (len(without_injections) == expected_benign) and (len(with_injections) == expected_attacked)
        lines.append(
            f"| {r.suite} | {r.role} | {r.policy.name if r.policy else ''} | {len(without_injections)} | "
            f"{len(with_injections)} | {expected_benign} | {expected_attacked} | {'yes' if match else '**NO**'} |"
        )
    lines.append("")

    # -- agentdojo.dirty --
    dirty_count = sum(1 for r in records if (r.manifest.get("agentdojo") or {}).get("dirty"))
    lines.append("### Reproducibility: `agentdojo.dirty`")
    lines.append(
        f"`{dirty_count}/{len(records)}` run manifests record `agentdojo.dirty: true` -- "
        f"{dirty_count} of {len(records)} would fail `compute_results.py`'s own `_check_publishable` "
        f"gate without `--allow-dirty` ({len(records) - dirty_count} would pass). Worth resolving "
        f"before treating any of these numbers as final."
    )
    lines.append("")

    # -- Per-suite canonical summary CSVs --
    lines.append("### Summary CSV coverage")
    for suite, path in summary_csvs.items():
        if path.exists():
            _, rows = read_csv_rows(path)
            lines.append(f"- `{path}`: found, {len(rows)} data row(s).")
        else:
            lines.append(f"- `{path}`: **not found** -- {suite}'s results haven't been published yet.")
    lines.append("")

    # -- Stray legacy CSV --
    lines.append("### Stray legacy summary CSV")
    stray = repo_root / "results" / "AgentDojo-Interbolt-Benchmark.csv"
    if stray.exists():
        stray_header, stray_rows = read_csv_rows(stray)
        lines.append(
            f"`{stray}` exists (repo-root `results/`, gitignored): {len(stray_header)} columns / "
            f"{len(stray_rows)} rows. This predates the per-suite `results.csv` split above (it "
            f"was a single combined-suite file under an older schema), so it has no current "
            f"per-suite file to diff against column-for-column. "
            f"**Treat it as pre-restructure legacy debris; ignore or delete it.**"
        )
    else:
        lines.append(f"`{stray}` not found in this checkout.")
    lines.append("")

    # -- Open questions 3 & 5 --
    lines.append("### Open question 3: are `allow_all` (B) runs shared across policies, or duplicated?")
    b_by_suite: dict[str, int] = Counter(r.suite for r in records if r.role == ROLE_B_ASR_MODEL)
    lines.append(
        f"**SHARED.** B-role run count per suite: {dict(sorted(b_by_suite.items()))} -- exactly one "
        f"`B_asr_model` directory per suite, used as the `--asr-model` input for both the strict "
        f"and targeted quartet computations."
    )
    lines.append("")

    lines.append("### Open question 5: are benign (C) and attacked (D) runs stored separately, or interleaved?")
    interleave_findings = []
    for r in records:
        if r.role != ROLE_C_UTILITY or r.pipeline_name is None:
            continue
        _, with_injections = discover_results(r.repeat_dir, r.pipeline_name, r.suite, r.benchmark_version)
        if with_injections:
            interleave_findings.append((r, len(with_injections)))
    if interleave_findings:
        lines.append(
            f"**{len(interleave_findings)} `C_utility` run(s) unexpectedly contain attacked-case "
            f"result files** -- would indicate interleaving:"
        )
        for r, n in interleave_findings:
            lines.append(f"  - `{r.repeat_dir}`: {n} attacked-case files found")
    else:
        lines.append(
            "**SEPARATE, never interleaved.** Every `C_utility` (benign) run directory contains "
            "zero attacked-case result files (checked directly, not assumed) -- `C_utility_*` and "
            "`D_asr_system_*` are always distinct directories."
        )

    return "\n".join(lines)
