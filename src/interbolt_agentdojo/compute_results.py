"""Metrics + markdown tables from run dirs.

    uv run python -m interbolt_agentdojo.compute_results runs/<name> [runs/<name2> ...] [--markdown] [--allow-dirty]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from agentdojo.benchmark import load_task_results
from agentdojo.task_suite.load_suites import get_suite


def _load_manifest(repeat_dir: Path) -> dict:
    return json.loads((repeat_dir / "run_manifest.json").read_text())


def _check_publishable(manifest: dict, allow_dirty: bool) -> None:
    if allow_dirty:
        return
    for pkg in ("interbolt", "agentdojo"):
        info = manifest.get(pkg) or {}
        if info.get("install_mode") == "editable":
            raise SystemExit(
                f"refusing to include {manifest['suite']!r} run in a publishable table: "
                f"{pkg!r} is an editable install (pass --allow-dirty for development use)"
            )
        if info.get("dirty"):
            raise SystemExit(
                f"refusing to include {manifest['suite']!r} run in a publishable table: "
                f"{pkg!r} source tree is dirty (pass --allow-dirty for development use)"
            )


def _discover_pipeline_name(repeat_dir: Path, suite_name: str) -> str | None:
    for child in repeat_dir.iterdir():
        if child.is_dir() and (child / suite_name).exists():
            return child.name
    return None


def _discover_results(
    repeat_dir: Path, pipeline_name: str, suite_name: str, benchmark_version: str
) -> tuple[dict, dict]:
    """Load per-task results by walking the trace directory, tolerant of subset runs.

    Mirrors `agentdojo.benchmark.load_suite_results`'s output shape, but discovers
    which tasks actually ran instead of assuming the full suite ran (that function
    raises `FileNotFoundError` on a deliberately subsetted `--user-tasks` run).
    Still uses AgentDojo's own `load_task_results` for the actual parsing.

    With an attack, AgentDojo also solves each injection task standalone (for
    ground truth), writing `<injection_task_id>/none/none.json` -- the exact
    same directory shape as a genuine no-attack user-task run. Filtering the
    top-level directory name against the suite's real `user_tasks` excludes
    those from the benign-utility bucket.
    """
    without_injections: dict = {}
    with_injections: dict = {}
    base = repeat_dir / pipeline_name / suite_name
    if not base.exists():
        return without_injections, with_injections
    user_task_ids = set(get_suite(benchmark_version, suite_name).user_tasks.keys())
    for user_task_dir in sorted(p for p in base.iterdir() if p.is_dir() and p.name in user_task_ids):
        for attack_dir in sorted(p for p in user_task_dir.iterdir() if p.is_dir()):
            for result_file in sorted(attack_dir.glob("*.json")):
                task_results = load_task_results(
                    pipeline_name, suite_name, user_task_dir.name, attack_dir.name, result_file.stem, repeat_dir
                )
                if attack_dir.name == "none":
                    without_injections[(user_task_dir.name, None)] = task_results
                else:
                    with_injections[(user_task_dir.name, result_file.stem)] = task_results
    return without_injections, with_injections


def _interbolt_event_summary(repeat_dir: Path) -> dict:
    blocks_by_rule: Counter = Counter()
    approvals_denied = 0
    eval_errors = 0
    events_path = repeat_dir / "interbolt_events.jsonl"
    if events_path.exists():
        with events_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                decision = event["decision"]
                if decision["action"] == "block":
                    blocks_by_rule[decision.get("matched_rule") or "(default)"] += 1
                if event.get("outcome") == "require_approval":
                    approvals_denied += 1
                if event.get("outcome") == "evaluation_error":
                    eval_errors += 1
    return {
        "blocks": sum(blocks_by_rule.values()),
        "approvals_denied": approvals_denied,
        "eval_errors": eval_errors,
        "top_rules": blocks_by_rule.most_common(3),
    }


def _rate(values) -> float | None:
    values = list(values)
    if not values:
        return None
    return sum(values) / len(values)


def _repeat_metrics(repeat_dir: Path, allow_dirty: bool) -> dict:
    manifest = _load_manifest(repeat_dir)
    _check_publishable(manifest, allow_dirty)
    suite_name = manifest["suite"]
    pipeline_name = _discover_pipeline_name(repeat_dir, suite_name)
    without_injections, with_injections = {}, {}
    if pipeline_name is not None:
        without_injections, with_injections = _discover_results(
            repeat_dir, pipeline_name, suite_name, manifest["benchmark_version"]
        )

    return {
        "manifest": manifest,
        "benign_utility": _rate(r.utility for r in without_injections.values()),
        "utility_under_attack": _rate(r.utility for r in with_injections.values()),
        # `security=True` means the injection succeeded (see docstring of
        # agentdojo.task_suite.task_suite.TaskSuite.run_task_with_pipeline).
        "asr": _rate(r.security for r in with_injections.values()),
        "events": _interbolt_event_summary(repeat_dir),
    }


def _configuration_label(manifest: dict) -> str:
    defense = manifest.get("defense")
    if defense is None:
        return "No defense (baseline)"
    return Path(defense["policy_file"]).name


def compute_run(run_dir: Path, allow_dirty: bool) -> dict:
    repeat_dirs = sorted(p for p in run_dir.iterdir() if p.is_dir() and p.name.startswith("repeat_"))
    if not repeat_dirs:
        repeat_dirs = [run_dir]
    per_repeat = [_repeat_metrics(d, allow_dirty) for d in repeat_dirs]

    def collect(key: str) -> list[float]:
        return [r[key] for r in per_repeat if r[key] is not None]

    return {
        "run_dir": run_dir,
        "label": _configuration_label(per_repeat[0]["manifest"]),
        "benign_utility": collect("benign_utility"),
        "utility_under_attack": collect("utility_under_attack"),
        "asr": collect("asr"),
        "events": [r["events"] for r in per_repeat],
    }


def _spread(values: list[float]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return f"{values[0]:.2f}"
    return f"{statistics.mean(values):.2f} ({min(values):.2f}-{max(values):.2f})"


def _print_text(results: list[dict]) -> None:
    for r in results:
        print(f"{r['label']} ({r['run_dir']})")
        print(f"  Benign utility: {_spread(r['benign_utility']) or 'n/a'}")
        print(f"  Utility under attack: {_spread(r['utility_under_attack']) or 'n/a'}")
        print(f"  Targeted ASR: {_spread(r['asr']) or 'n/a'}")
        total_errors = sum(e["eval_errors"] for e in r["events"])
        if total_errors:
            print(f"  ** {total_errors} policy evaluation errors -- investigate before publishing **")


def _print_markdown(results: list[dict]) -> None:
    print("| Configuration        | Benign utility | Utility under attack | Targeted ASR |")
    print("|-----------------------|----------------|-----------------------|--------------|")
    for r in results:
        print(f"| {r['label']} | {_spread(r['benign_utility'])} | {_spread(r['utility_under_attack'])} | {_spread(r['asr'])} |")
    print()
    print("| Configuration | Blocks | Approvals denied | Eval errors | Top matched rules |")
    print("|---------------|--------|-------------------|-------------|-------------------|")
    for r in results:
        blocks = sum(e["blocks"] for e in r["events"])
        approvals = sum(e["approvals_denied"] for e in r["events"])
        errors = sum(e["eval_errors"] for e in r["events"])
        top_rules: Counter = Counter()
        for e in r["events"]:
            for rule, count in e["top_rules"]:
                top_rules[rule] += count
        top = ", ".join(f"{rule} ({count})" for rule, count in top_rules.most_common(3))
        print(f"| {r['label']} | {blocks} | {approvals} | {errors} | {top} |")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    results = [compute_run(run_dir, args.allow_dirty) for run_dir in args.run_dirs]
    if args.markdown:
        _print_markdown(results)
    else:
        _print_text(results)


if __name__ == "__main__":
    main()
