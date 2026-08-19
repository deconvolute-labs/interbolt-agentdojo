"""Pipeline builders: undefended baseline, Interbolt-gated, and run scoping."""

from __future__ import annotations

import collections
import json
import time
from pathlib import Path

import interbolt
from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, PipelineConfig, get_llm, load_system_message
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop, tool_result_to_str
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionsRuntime
from agentdojo.logging import Logger
from agentdojo.models import MODEL_PROVIDERS, ModelsEnum
from agentdojo.task_suite.task_suite import TaskSuite
from agentdojo.types import ChatMessage
from interbolt import Policy
from interbolt.models.protocols import Reporter
from interbolt.utils import current_run_id

from interbolt_agentdojo.executor import DEFAULT_AGENT_ID, InterboltToolsExecutor
from interbolt_agentdojo.progress import format_duration, get_logger


def build_plain_pipeline(model: str | BasePipelineElement, suite: TaskSuite) -> AgentPipeline:
    """The undefended baseline: AgentDojo's own default pipeline, untouched.

    `suite` isn't used yet -- `TaskSuite` has no per-suite system message
    (AgentDojo's own `system_messages.yaml` only declares `default`); kept
    in the signature so a future suite-specific message is a one-line
    addition here, not a signature change.
    """
    return AgentPipeline.from_config(
        PipelineConfig(llm=model, model_id=None, defense=None, system_message_name=None, system_message=None)
    )


def _resolve_llm(model: str | BasePipelineElement) -> tuple[BasePipelineElement, str]:
    if isinstance(model, str):
        return get_llm(MODEL_PROVIDERS[ModelsEnum(model)], model, None, "tool"), model
    return model, model.name


def build_interbolt_pipeline(
    model: str | BasePipelineElement,
    suite: TaskSuite,
    policy_path: Path,
    mode: str,
    reporter: Reporter,
    call_records_path: Path | None = None,
    *,
    agent_id: str = DEFAULT_AGENT_ID,
) -> AgentPipeline:
    """Same shape as `AgentPipeline.from_config`'s `defense is None` branch, with
    `InterboltToolsExecutor` substituted for AgentDojo's `ToolsExecutor`."""
    interbolt.configure(policy=Policy.from_file(policy_path), mode=mode, reporter=reporter)

    llm, llm_name = _resolve_llm(model)
    tools_loop = ToolsExecutionLoop(
        [
            InterboltToolsExecutor(
                tool_result_to_str,
                call_records_path=call_records_path,
                suite_name=suite.name,
                suite_tools=[t.name for t in suite.tools],
                agent_id=agent_id,
            ),
            llm,
        ]
    )
    pipeline = AgentPipeline([SystemMessage(load_system_message(None)), InitQuery(), llm, tools_loop])
    pipeline.name = f"{llm_name}-interbolt-{policy_path.stem}-{mode}"
    return pipeline


class RunScopedPipeline(BasePipelineElement):
    """Wraps a pipeline so each `query()` call is exactly one Interbolt run.

    AgentDojo's benchmark loop calls `pipeline.query()` once per
    (user_task, injection_task) case, so scoping one Interbolt run per
    `query()` call keeps `run_tainted` from leaking across cases. Also
    appends the join key AgentDojo's own logs lack -- `{seq, run_id,
    user_task_id, injection_task_id, started_at}` -- to `run_index_path`.
    """

    def __init__(
        self, inner: BasePipelineElement, run_index_path: Path, *, agent_id: str = DEFAULT_AGENT_ID
    ) -> None:
        self.inner = inner
        # AgentDojo's benchmark loop reads `agent_pipeline.name` off the
        # outermost element (this wrapper) to route trace logging; without
        # propagating it, TraceLogger silently can't save any trace JSON.
        self.name = inner.name
        self.run_index_path = run_index_path
        self._agent_id = agent_id
        self._seq = self._existing_row_count()

    def _existing_row_count(self) -> int:
        if not self.run_index_path.exists():
            return 0
        with self.run_index_path.open() as f:
            return sum(1 for line in f if line.strip())

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: list[ChatMessage] = [],
        extra_args: dict = {},
    ):
        with interbolt.get_runtime().agent_context_sync(self._agent_id):
            run_id = current_run_id.get()
            # AgentDojo's TraceLogger pushes suite/task identity onto a context
            # stack for the whole (user_task, injection_task) case; Logger.get()
            # falls back to NullLogger (no .context) outside that scope, e.g. in
            # direct unit-test calls, hence the getattr guard.
            context = getattr(Logger().get(), "context", {})
            with self.run_index_path.open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "seq": self._seq,
                            "run_id": run_id,
                            "user_task_id": context.get("user_task_id"),
                            "injection_task_id": context.get("injection_task_id"),
                            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }
                    )
                    + "\n"
                )
                
            self._seq += 1
            status, error = "ok", None
            
            try:
                result = self.inner.query(query, runtime, env, messages, extra_args)
            except BaseException as e:
                status, error = "error", f"{type(e).__name__}: {e}"
                raise
            finally:
                with (self.run_index_path.parent / "run_outcomes.jsonl").open("a") as f:
                    f.write(json.dumps({
                        "run_id": run_id,
                        "status": status,
                        "error": error,
                        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }) + "\n")

            Logger().get().log(result[3])
            return result

class ProgressLoggingPipeline(BasePipelineElement):
    """Wraps a pipeline to print console progress while a benchmark run is in flight.

    AgentDojo's own per-task loop lives in the `agentdojo` package, not here, so
    there's no clean in-process hook for "a task just finished" without patching
    that dependency. Instead this reads the trace JSON files `TraceLogger`
    already writes to `repeat_dir` as a normal side effect -- one appears
    shortly after each (user_task, injection_task) case completes, strictly
    before the next case's first `query()` call, since AgentDojo's loop is
    sequential. Scanning for new files on every `query()` call (plus a final
    `flush()`) is enough to report each finished task without touching
    AgentDojo internals.
    """

    def __init__(self, inner: BasePipelineElement, repeat_dir: Path, total: int) -> None:
        self.inner = inner
        # AgentDojo's benchmark loop reads `agent_pipeline.name` off the
        # outermost element to route trace logging (same reason RunScopedPipeline
        # propagates it above).
        self.name = inner.name
        self.repeat_dir = repeat_dir
        self.total = total
        self.start = time.monotonic()
        self.request_count = 0
        self.recent: collections.deque[str] = collections.deque(maxlen=2)
        self.seen: set[Path] = set()

        if self.repeat_dir.exists():
            already_done = sorted(self.repeat_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime)
            if already_done:
                self.seen.update(already_done)
                get_logger().info(f"resuming: {len(already_done)}/{self.total} tasks already recorded")

    def _scan_for_new_results(self) -> None:
        if not self.repeat_dir.exists():
            return
        logger = get_logger()
        for f in sorted(self.repeat_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime):
            if f in self.seen:
                continue
            self.seen.add(f)
            try:
                record = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue

            if record.get("error"):
                label = "ERROR"
            elif record.get("utility"):
                label = "PASS"
            else:
                label = "FAIL"
            self.recent.append(label)

            done = len(self.seen)
            elapsed = time.monotonic() - self.start
            eta = elapsed * (self.total - done) / done if done and done < self.total else 0
            task_desc = record.get("user_task_id", "?")
            injection_id = record.get("injection_task_id")
            if injection_id:
                task_desc += f" x {injection_id}"
            logger.info(
                f"[{done}/{self.total}] {task_desc} -> {label} "
                f"(elapsed {format_duration(elapsed)}, eta {format_duration(eta)}) "
                f"recent: {' '.join(self.recent)}"
            )

    def flush(self) -> None:
        self._scan_for_new_results()

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: list[ChatMessage] = [],
        extra_args: dict = {},
    ):
        self._scan_for_new_results()
        self.request_count += 1
        elapsed = time.monotonic() - self.start
        get_logger().info(f"request #{self.request_count} (elapsed {format_duration(elapsed)})")
        return self.inner.query(query, runtime, env, messages, extra_args)
