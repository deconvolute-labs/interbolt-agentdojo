"""CLI: record a replay corpus in one spend.

A thin preset over `run_benchmark`: forces `--policy policies/generic.yaml
--mode dry_run`. `dry_run` blocks nothing, so this run's trajectory and
AgentDojo results ARE the baseline numbers; recording under a real policy
(rather than `allow_all`) makes the emitted decisions' matched-rule fields
informative. One spend, two artifacts: `interbolt_events.jsonl` (the
replay corpus) and the AgentDojo traces (the baseline).

    uv run python -m interbolt_agentdojo.record_corpus \\
      --suite banking --model <model> \\
      [--attack important_instructions] \\
      [--user-tasks ...] [--injection-tasks ...] \\
      --logdir runs/<name>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from interbolt_agentdojo.run_benchmark import DEFAULT_BENCHMARK_VERSION, run

_RECORDING_POLICY = "policies/generic.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--attack", default=None)
    parser.add_argument("--user-tasks", nargs="+", default=None)
    parser.add_argument("--injection-tasks", nargs="+", default=None)
    parser.add_argument("--logdir", required=True, type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.policy = _RECORDING_POLICY
    args.mode = "dry_run"
    args.repeats = 1
    args.force_rerun = False
    args.benchmark_version = DEFAULT_BENCHMARK_VERSION
    run(args)


if __name__ == "__main__":
    main()
