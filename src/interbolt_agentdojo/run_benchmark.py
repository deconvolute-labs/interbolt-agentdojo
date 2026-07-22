"""CLI: run the banking suite, with or without Interbolt as the defense.

    uv run python -m interbolt_agentdojo.run_benchmark \\
      --suite banking --model <model> \\
      [--attack important_instructions] \\
      [--policy policies/strict.yaml --mode enforce|dry_run] \\
      [--user-tasks ...] [--injection-tasks ...] \\
      [--repeats N] [--force-rerun] \\
      --logdir runs/<name>

No `--policy` runs the undefended baseline. `--policy` without `--mode`
defaults to `enforce`.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.benchmark import benchmark_suite_with_injections, benchmark_suite_without_injections
from agentdojo.logging import OutputLogger
from agentdojo.models import ModelsEnum
from agentdojo.task_suite.load_suites import get_suite
from interbolt import JsonlReporter

from interbolt_agentdojo import progress
from interbolt_agentdojo.manifest import write_manifest
from interbolt_agentdojo.models_ext import make_llm
from interbolt_agentdojo.pipeline import (
    ProgressLoggingPipeline,
    RunScopedPipeline,
    build_interbolt_pipeline,
    build_plain_pipeline,
)

DEFAULT_BENCHMARK_VERSION = "v1.2.2"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--attack", default=None)
    parser.add_argument("--policy", default=None)
    parser.add_argument("--mode", choices=["enforce", "dry_run"], default=None)
    parser.add_argument("--user-tasks", nargs="+", default=None)
    parser.add_argument("--injection-tasks", nargs="+", default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--logdir", required=True, type=Path)
    parser.add_argument("--benchmark-version", default=DEFAULT_BENCHMARK_VERSION)
    return parser


def _resolve_model(model: str) -> str | BasePipelineElement:
    if model.startswith("gemini-"):
        # Already ModelsEnum-known, but AgentDojo's own wiring for it hardcodes
        # Vertex AI auth -- force the API-key bypass regardless (see models_ext.py).
        return make_llm(model)
    try:
        ModelsEnum(model)
        return model
    except ValueError:
        return make_llm(model)


def _print_summary(results, has_attack: bool) -> None:
    utility = list(results["utility_results"].values())
    if utility:
        print(f"Benign/attacked utility: {sum(utility)}/{len(utility)}")
    if has_attack:
        # `security=True` means the injection succeeded (see docstring of
        # agentdojo.task_suite.task_suite.TaskSuite.run_task_with_pipeline:
        # "the second [bool] indicating if the injection was successful").
        security = list(results["security_results"].values())
        attacks_succeeded = sum(security)
        print(f"Targeted ASR: {attacks_succeeded}/{len(security)}")


def _run_once(args: argparse.Namespace, repeat_dir: Path) -> None:
    suite = get_suite(args.benchmark_version, args.suite)
    model: str | BasePipelineElement = _resolve_model(args.model)

    if args.policy:
        mode = args.mode or "enforce"
        reporter = JsonlReporter(repeat_dir / "interbolt_events.jsonl")
        inner = build_interbolt_pipeline(
            model,
            suite,
            Path(args.policy),
            mode,
            reporter,
            call_records_path=repeat_dir / "call_records.jsonl",
        )
        pipeline = RunScopedPipeline(inner, repeat_dir / "run_index.jsonl")
        args.mode = mode
    else:
        pipeline = build_plain_pipeline(model, suite)

    attack = None
    if args.attack:
        import agentdojo.attacks  # noqa: F401  (import registers attacks)
        from agentdojo.attacks.attack_registry import load_attack

        attack = load_attack(args.attack, suite, pipeline)
        total = progress.count_tasks_with_injections(suite, args, attack)
    else:
        total = progress.count_tasks_without_injections(suite, args)

    tracked_pipeline = ProgressLoggingPipeline(pipeline, repeat_dir, total)

    args.run_started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # AgentDojo's benchmark functions log through the ambient `Logger` stack
    # (see agentdojo.logging.Logger.get()); their own CLI (scripts/benchmark.py)
    # always wraps the call in `OutputLogger`, which is where `logdir` actually
    # gets attached -- without it, `TraceLogger` has no `.logdir` to write to.
    with OutputLogger(str(repeat_dir)):
        if attack is not None:
            results = benchmark_suite_with_injections(
                tracked_pipeline,
                suite,
                attack,
                repeat_dir,
                args.force_rerun,
                user_tasks=args.user_tasks,
                injection_tasks=args.injection_tasks,
                benchmark_version=args.benchmark_version,
            )
        else:
            results = benchmark_suite_without_injections(
                tracked_pipeline,
                suite,
                repeat_dir,
                args.force_rerun,
                user_tasks=args.user_tasks,
                benchmark_version=args.benchmark_version,
            )
    tracked_pipeline.flush()
    args.run_finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    manifest_path = write_manifest(repeat_dir, args)
    _print_summary(results, has_attack=bool(args.attack))
    print(f"Manifest: {manifest_path}")


def run(args: argparse.Namespace) -> None:
    for i in range(args.repeats):
        if args.repeats > 1:
            progress.get_logger().info(f"=== repeat {i + 1}/{args.repeats} ===")
        _run_once(args, args.logdir / f"repeat_{i}")


def main() -> None:
    run(build_parser().parse_args())


if __name__ == "__main__":
    main()
