"""Pipeline builders: undefended baseline, Interbolt-gated, and run scoping."""

from __future__ import annotations

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

from interbolt_agentdojo.executor import AGENT_ID, InterboltToolsExecutor


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
) -> AgentPipeline:
    """Same shape as `AgentPipeline.from_config`'s `defense is None` branch, with
    `InterboltToolsExecutor` substituted for AgentDojo's `ToolsExecutor`."""
    interbolt.configure(policy=Policy.from_file(policy_path), mode=mode, reporter=reporter)

    llm, llm_name = _resolve_llm(model)
    tools_loop = ToolsExecutionLoop(
        [InterboltToolsExecutor(tool_result_to_str, call_records_path=call_records_path), llm]
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
    started_at}` -- to `run_index_path`.
    """

    def __init__(self, inner: BasePipelineElement, run_index_path: Path) -> None:
        self.inner = inner
        # AgentDojo's benchmark loop reads `agent_pipeline.name` off the
        # outermost element (this wrapper) to route trace logging; without
        # propagating it, TraceLogger silently can't save any trace JSON.
        self.name = inner.name
        self.run_index_path = run_index_path
        self._seq = 0

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: list[ChatMessage] = [],
        extra_args: dict = {},
    ):
        with interbolt.get_runtime().agent_context_sync(AGENT_ID):
            run_id = current_run_id.get()
            with self.run_index_path.open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "seq": self._seq,
                            "run_id": run_id,
                            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }
                    )
                    + "\n"
                )
            self._seq += 1
            result = self.inner.query(query, runtime, env, messages, extra_args)
            Logger().get().log(result[3])
            return result
