"""InterboltToolsExecutor: the enforcement seam between AgentDojo tool calls and Interbolt.

Subclasses AgentDojo's `ToolsExecutor` (the single dispatch point for tool
calls, see `agentdojo.agent_pipeline.tool_execution`) rather than modifying
it. Per call: check policy, enforce the decision, and on allow taint the
formatted result before it re-enters the model's context.
"""

from __future__ import annotations

import json
from ast import literal_eval
from collections.abc import Iterable
from pathlib import Path

from agentdojo.agent_pipeline.llms.google_llm import EMPTY_FUNCTION_NAME
from agentdojo.agent_pipeline.tool_execution import ToolsExecutor, is_string_list, tool_result_to_str
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionsRuntime
from agentdojo.types import ChatMessage, ChatToolResultMessage, text_content_block_from_string
from interbolt import ApprovalDenied, PolicyEvaluationError, PolicyViolation, get_runtime, taint
from interbolt.constants import DEFAULT_AGENT_ID as INTERBOLT_RESERVED_AGENT_ID
from interbolt.utils.names import validate_agent_id

from interbolt_agentdojo.namespaces import resolve_namespace, validate_suite_coverage

# The harness's own fixed default identity -- distinct from
# `interbolt.constants.DEFAULT_AGENT_ID` ("default"), which is Interbolt's
# reserved sentinel for "no explicit agent context." Same naming pattern,
# different values -- do not conflate them.
DEFAULT_AGENT_ID = "agentdojo-agent"
_BLOCKED_MESSAGE = "Blocked by security policy."


class InterboltToolsExecutor(ToolsExecutor):
    """Gates each tool call through `interbolt.check()`/`enforce_decision_sync()`."""

    def __init__(
        self,
        tool_output_formatter=tool_result_to_str,
        call_records_path: Path | None = None,
        *,
        suite_name: str,
        suite_tools: Iterable[str] = (),
        agent_id: str = DEFAULT_AGENT_ID,
    ) -> None:
        super().__init__(tool_output_formatter)
        validate_suite_coverage(suite_name, suite_tools)
        validate_agent_id(agent_id)
        if agent_id == INTERBOLT_RESERVED_AGENT_ID:
            raise ValueError(
                f"agent_id {agent_id!r} is reserved by interbolt for implicit no-context use "
                "and may not be used as an explicit harness identity"
            )
        self.call_records_path = call_records_path
        self._suite_name = suite_name
        self._agent_id = agent_id
        self._seq = 0

    def _record_call(self, tool: str, args: dict, decision) -> None:
        if self.call_records_path is None or decision is None:
            return
        record = {
            "seq": self._seq,
            "run_id": decision.run_id,
            "tool": tool,
            "args": args,
            "label_lineages": [label.model_dump(mode="json") for label in decision.contributing_labels],
            "run_tainted": decision.run_tainted,
        }
        self._seq += 1
        with self.call_records_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def _dispatch(self, tool_call, runtime: FunctionsRuntime, env: Env) -> ChatToolResultMessage:
        interbolt_runtime = get_runtime()
        qualified_name = f"{resolve_namespace(self._suite_name, tool_call.function)}.{tool_call.function}"
        args = dict(tool_call.args)
        try:
            decision = interbolt_runtime.check(tool=qualified_name, args=args, agent_id=self._agent_id)
            interbolt_runtime.enforce_decision_sync(decision)
        except (PolicyViolation, ApprovalDenied, PolicyEvaluationError) as exc:
            self._record_call(qualified_name, args, exc.decision)
            return ChatToolResultMessage(
                role="tool",
                content=[text_content_block_from_string("")],
                tool_call_id=tool_call.id,
                tool_call=tool_call,
                error=_BLOCKED_MESSAGE,
            )

        self._record_call(qualified_name, args, decision)
        tool_call_result, error = runtime.run_function(env, tool_call.function, tool_call.args)
        formatted = self.output_formatter(tool_call_result)
        tainted = taint(formatted, source=f"tool:{tool_call.function}")
        return ChatToolResultMessage(
            role="tool",
            content=[text_content_block_from_string(tainted)],
            tool_call_id=tool_call.id,
            tool_call=tool_call,
            error=error,
        )

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: list[ChatMessage] = [],
        extra_args: dict = {},
    ):
        if len(messages) == 0:
            return query, runtime, env, messages, extra_args
        if messages[-1]["role"] != "assistant":
            return query, runtime, env, messages, extra_args
        if messages[-1]["tool_calls"] is None or len(messages[-1]["tool_calls"]) == 0:
            return query, runtime, env, messages, extra_args

        tool_call_results = []
        for tool_call in messages[-1]["tool_calls"]:
            if tool_call.function == EMPTY_FUNCTION_NAME:
                tool_call_results.append(
                    ChatToolResultMessage(
                        role="tool",
                        content=[text_content_block_from_string("")],
                        tool_call_id=tool_call.id,
                        tool_call=tool_call,
                        error="Empty function name provided. Provide a valid function name.",
                    )
                )
                continue
            if tool_call.function not in (tool.name for tool in runtime.functions.values()):
                tool_call_results.append(
                    ChatToolResultMessage(
                        role="tool",
                        content=[text_content_block_from_string("")],
                        tool_call_id=tool_call.id,
                        tool_call=tool_call,
                        error=f"Invalid tool {tool_call.function} provided.",
                    )
                )
                continue

            for arg_k, arg_v in tool_call.args.items():
                if isinstance(arg_v, str) and is_string_list(arg_v):
                    tool_call.args[arg_k] = literal_eval(arg_v)

            tool_call_results.append(self._dispatch(tool_call, runtime, env))
        return query, runtime, env, [*messages, *tool_call_results], extra_args
