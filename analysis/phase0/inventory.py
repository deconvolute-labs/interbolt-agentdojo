"""Spec items 1 (directory tree) and 2 (per-file-type samples)."""

from __future__ import annotations

import json
from pathlib import Path

from analysis.common.artifacts import load_jsonl, load_policy_yaml, read_csv_rows, read_json, suite_scoped_dir
from analysis.common.discovery import ROLE_B_ASR_MODEL, ROLE_D_ASR_SYSTEM, RunRecord
from analysis.common.treestats import format_bytes, tree_summary


def render_tree_section(results_root: Path, max_depth: int = 4) -> str:
    lines = [f"## 1. Directory tree (`{results_root}`, depth {max_depth})", ""]
    lines.append("| Depth | Directory | Direct files | Files (recursive) | Size (recursive) |")
    lines.append("|---|---|---|---|---|")
    stats = tree_summary(results_root, max_depth)
    for s in stats:
        rel = s.path.relative_to(results_root.parent) if s.path != results_root else s.path.name
        indent = "&nbsp;&nbsp;" * s.depth
        lines.append(
            f"| {s.depth} | {indent}`{rel}` | {s.direct_file_count} | "
            f"{s.recursive_file_count} | {format_bytes(s.recursive_byte_size)} |"
        )
    root_stats = stats[0]
    lines.append("")
    lines.append(
        f"**Total under `{results_root}`: {root_stats.recursive_file_count} files, "
        f"{format_bytes(root_stats.recursive_byte_size)}.**"
    )
    return "\n".join(lines)


def _pretty_jsonl_sample(path: Path, n: int = 2) -> str:
    if not path.exists():
        return f"_(not found: `{path}`)_"
    records = load_jsonl(path)[:n]
    if not records:
        return "_(empty file)_"
    return "\n\n".join(f"```json\n{json.dumps(r, indent=2)}\n```" for r in records)


def _pretty_json_sample(path: Path) -> str:
    if not path.exists():
        return f"_(not found: `{path}`)_"
    return f"```json\n{json.dumps(read_json(path), indent=2)}\n```"


def _first_lines(path: Path, n: int = 40) -> str:
    if not path.exists():
        return f"_(not found: `{path}`)_"
    text = "\n".join(Path(path).read_text().splitlines()[:n])
    suffix = path.suffix.lstrip(".")
    return f"```{suffix}\n{text}\n```"


def _find_pseudo_case_json(record: RunRecord) -> Path | None:
    """<repeat_dir>/<pipeline>/<suite>/injection_task_N/none/none.json, if present."""
    if record.pipeline_name is None:
        return None
    base = record.repeat_dir / record.pipeline_name / record.suite
    if not base.exists():
        return None
    for child in sorted(base.iterdir()):
        if child.is_dir() and child.name.startswith("injection_task_"):
            candidate = child / "none" / "none.json"
            if candidate.exists():
                return candidate
    return None


def _find_benign_case_json(record: RunRecord) -> Path | None:
    if record.pipeline_name is None:
        return None
    base = record.repeat_dir / record.pipeline_name / record.suite
    if not base.exists():
        return None
    for child in sorted(base.iterdir()):
        if child.is_dir() and child.name.startswith("user_task_"):
            candidate = child / "none" / "none.json"
            if candidate.exists():
                return candidate
    return None


def _find_attacked_case_json(record: RunRecord) -> Path | None:
    if record.pipeline_name is None:
        return None
    base = record.repeat_dir / record.pipeline_name / record.suite
    if not base.exists():
        return None
    for child in sorted(base.iterdir()):
        if not (child.is_dir() and child.name.startswith("user_task_")):
            continue
        for attack_dir in sorted(child.iterdir()):
            if attack_dir.is_dir() and attack_dir.name != "none":
                results = sorted(attack_dir.glob("*.json"))
                if results:
                    return results[0]
    return None


def _schema_version_of(path: Path) -> int | None:
    records = load_jsonl(path)
    if not records:
        return None
    return records[0].get("schema_version")


def render_file_type_samples(
    records: list[RunRecord], policies_root: Path, summary_csvs: dict[str, Path], example_suite: str
) -> str:
    lines = ["## 2. File-type samples (first 2 records / 40 lines, pretty-printed)", ""]

    try:
        a_record = next(r for r in records if r.role == "A_ceiling" and r.suite == example_suite)
    except StopIteration:
        raise ValueError(f"no A_ceiling record found for suite {example_suite!r}") from None
    b_records = [r for r in records if r.role == ROLE_B_ASR_MODEL]
    d_records = [r for r in records if r.role == ROLE_D_ASR_SYSTEM]

    # run_manifest.json
    lines.append("### `run_manifest.json`")
    lines.append(f"Sampled from `{a_record.repeat_dir / 'run_manifest.json'}`:")
    lines.append(_pretty_json_sample(a_record.repeat_dir / "run_manifest.json"))
    lines.append("")

    # run_index.jsonl
    lines.append("### `run_index.jsonl`")
    idx_record = b_records[0]
    lines.append(f"Sampled from `{idx_record.repeat_dir / 'run_index.jsonl'}`:")
    lines.append(_pretty_jsonl_sample(idx_record.repeat_dir / "run_index.jsonl"))
    lines.append("")

    # interbolt_events.jsonl -- once per distinct schema_version actually present
    lines.append("### `interbolt_events.jsonl`")
    seen_versions: dict[int, RunRecord] = {}
    for r in b_records + d_records:
        events_path = r.repeat_dir / "interbolt_events.jsonl"
        version = _schema_version_of(events_path)
        if version is not None and version not in seen_versions:
            seen_versions[version] = r
    if not seen_versions:
        lines.append("_(no interbolt_events.jsonl found)_")
    for version in sorted(seen_versions):
        r = seen_versions[version]
        lines.append(f"**schema_version={version}**, sampled from `{r.repeat_dir / 'interbolt_events.jsonl'}` (suite={r.suite}, role={r.role}, policy={r.policy.name if r.policy else None}):")
        lines.append(_pretty_jsonl_sample(r.repeat_dir / "interbolt_events.jsonl"))
        lines.append("")
    lines.append(
        f"_Distinct `schema_version` values found across all runs: {sorted(seen_versions)} "
        f"(see §6 for the full per-run breakdown and what it implies)._"
    )
    lines.append("")

    # call_records.jsonl
    lines.append("### `call_records.jsonl`")
    lines.append(f"Sampled from `{idx_record.repeat_dir / 'call_records.jsonl'}`:")
    lines.append(_pretty_jsonl_sample(idx_record.repeat_dir / "call_records.jsonl"))
    lines.append("")

    # AgentDojo per-case JSON -- benign / attacked / pseudo-case
    lines.append("### AgentDojo per-case result JSON")
    try:
        c_record = next(
            r for r in records if r.role == "C_utility" and r.policy and r.policy.name == "strict" and r.suite == example_suite
        )
    except StopIteration:
        raise ValueError(f"no C_utility/strict record found for suite {example_suite!r}") from None
    benign_path = _find_benign_case_json(c_record)
    lines.append(f"**Benign case**, sampled from `{benign_path}`:")
    lines.append(_pretty_json_sample(benign_path) if benign_path else "_(none found)_")
    lines.append("")
    attacked_path = _find_attacked_case_json(d_records[0])
    lines.append(f"**Attacked case**, sampled from `{attacked_path}`:")
    lines.append(_pretty_json_sample(attacked_path) if attacked_path else "_(none found)_")
    lines.append("")
    pseudo_path = _find_pseudo_case_json(b_records[0])
    lines.append(
        "**Pseudo-case** (AgentDojo's own \"solve the injection goal as a standalone task\" "
        f"ground-truth check -- `user_task_id` holds an `injection_task_N` string, "
        f"`injection_task_id` and `attack_type` are both null), sampled from `{pseudo_path}`:"
    )
    lines.append(_pretty_json_sample(pseudo_path) if pseudo_path else "_(none found)_")
    lines.append("")

    # Policy YAML
    lines.append("### Policy YAML")
    for name in ("allow_all", "strict", "targeted"):
        path = suite_scoped_dir(policies_root, example_suite) / f"{name}.yaml"
        lines.append(f"**`{name}.yaml`** (`{path}`):")
        if path.exists():
            content = load_policy_yaml(path)
            preview = "\n".join(path.read_text().splitlines()[:25])
            lines.append(f"```yaml\n{preview}\n```")
            lines.append(f"_(top-level keys: {sorted(content.keys())})_")
        else:
            lines.append(f"_(not found: `{path}`)_")
        lines.append("")

    # Summary CSV -- one per suite (`<results_root>/<suite>/results.csv`, accumulated
    # across policies/repeats by `compute_results.py --csv-out`); not every suite has
    # one yet (e.g. travel, at time of writing).
    lines.append("### Summary CSV")
    for suite, summary_csv in summary_csvs.items():
        lines.append(f"**{suite}**, `{summary_csv}`:")
        if summary_csv.exists():
            header, rows = read_csv_rows(summary_csv)
            lines.append(f"Header ({len(header)} columns): `{header}`")
            for row in rows[:2]:
                lines.append(f"- `{row}`")
            lines.append(f"_({len(rows)} data rows total)_")
        else:
            lines.append(f"_(not found: `{summary_csv}`)_")
        lines.append("")

    # results_*.md
    lines.append("### `results_*.md`")
    md_path = a_record.repeat_dir.parent.parent / "results_strict.md"
    lines.append(f"Sampled from `{md_path}` (first 10 lines):")
    lines.append(_first_lines(md_path, n=10))
    lines.append("_Fully derived from the summary CSV cells; adds no new information._")

    return "\n".join(lines)
