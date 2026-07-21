"""Console progress feedback for long-running benchmark invocations.

Nothing here patches or wraps AgentDojo internals: `count_tasks_*` is plain
arithmetic over public `TaskSuite`/CLI-arg attributes, and `ProgressLoggingPipeline`
(in `pipeline.py`) only reads the trace JSON files AgentDojo already writes to
`--logdir` as a normal side effect.
"""

from __future__ import annotations

import argparse
import logging

from agentdojo.attacks.base_attacks import BaseAttack
from agentdojo.task_suite.task_suite import TaskSuite

LOGGER_NAME = "interbolt_agentdojo"


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        # AgentDojo's own `OutputLogger.log()` calls `logging.info(...)` on the
        # root logger once per chat message per task; propagating there would
        # unmask that flood the moment anyone raises the root logger's level.
        logger.propagate = False
    return logger


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def count_tasks_without_injections(suite: TaskSuite, args: argparse.Namespace) -> int:
    return len(args.user_tasks) if args.user_tasks is not None else len(suite.user_tasks)


def count_tasks_with_injections(suite: TaskSuite, args: argparse.Namespace, attack: BaseAttack) -> int:
    num_user_tasks = len(args.user_tasks) if args.user_tasks is not None else len(suite.user_tasks)
    if attack.is_dos_attack:
        per_injection = 1
        preloop = 0
    else:
        per_injection = len(args.injection_tasks) if args.injection_tasks is not None else len(suite.injection_tasks)
        preloop = per_injection
    return preloop + num_user_tasks * per_injection
