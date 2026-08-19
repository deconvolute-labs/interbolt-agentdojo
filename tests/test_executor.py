"""InterboltToolsExecutor + RunScopedPipeline tests. No network calls."""

from __future__ import annotations

import json

import interbolt
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime, make_function
from agentdojo.logging import OutputLogger, TraceLogger
from agentdojo.types import ChatAssistantMessage
from interbolt import InMemoryReporter, Policy, taint

from interbolt_agentdojo.executor import DEFAULT_AGENT_ID, InterboltToolsExecutor
from interbolt_agentdojo.pipeline import RunScopedPipeline


def echo_tool(value: str) -> str:
    """Returns value unchanged.

    :param value: The value to echo.
    """
    return value


def danger_tool(value: str) -> str:
    """A stand-in for a state-changing tool.

    :param value: An argument.
    """
    return "done"


def _runtime() -> FunctionsRuntime:
    return FunctionsRuntime(functions=[make_function(echo_tool), make_function(danger_tool)])


def _assistant_message(tool_call: FunctionCall) -> ChatAssistantMessage:
    return ChatAssistantMessage(role="assistant", content=None, tool_calls=[tool_call])


def _policy_text(sink_action: str, extra_sources: str = "") -> str:
    return f"""
version: "2.0"
defaults:
  sink_action: allow
sources:
  - name: "tool:echo_tool"
    trust: trusted
{extra_sources}
sinks:
  test-suite.danger_tool:
    rules:
      - name: default
        action: {sink_action}
  test-suite.probe:
    rules:
      - name: default
        action: allow
"""


def _configure(tmp_path, sink_action: str, mode: str = "enforce", extra_sources: str = ""):
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(_policy_text(sink_action, extra_sources))
    reporter = InMemoryReporter()
    interbolt.configure(policy=Policy.from_file(str(policy_path)), mode=mode, reporter=reporter)
    return reporter


def test_allow_path_executes_tool_and_taints_result(tmp_path):
    _configure(tmp_path, "allow")
    with interbolt.get_runtime().agent_context_sync(DEFAULT_AGENT_ID):
        executor = InterboltToolsExecutor(suite_name="test-suite")
        tool_call = FunctionCall(function="danger_tool", args={"value": "hi"}, id="1")
        _, _, _, messages, _ = executor.query("q", _runtime(), messages=[_assistant_message(tool_call)])

    result = messages[-1]
    assert result["error"] is None
    assert result["content"][0]["content"] == "done"


def test_block_path_does_not_execute_tool(tmp_path):
    _configure(tmp_path, "block")
    with interbolt.get_runtime().agent_context_sync(DEFAULT_AGENT_ID):
        executor = InterboltToolsExecutor(suite_name="test-suite")
        tool_call = FunctionCall(function="danger_tool", args={"value": "hi"}, id="1")
        _, _, _, messages, _ = executor.query("q", _runtime(), messages=[_assistant_message(tool_call)])

    result = messages[-1]
    assert result["error"] == "Blocked by security policy."
    assert result["content"][0]["content"] == ""
    assert "rule" not in result["error"].lower()
    assert "when" not in result["error"].lower()


def test_approval_denied_path_does_not_execute_tool(tmp_path):
    _configure(tmp_path, "require_approval")
    with interbolt.get_runtime().agent_context_sync(DEFAULT_AGENT_ID):
        executor = InterboltToolsExecutor(suite_name="test-suite")
        tool_call = FunctionCall(function="danger_tool", args={"value": "hi"}, id="1")
        _, _, _, messages, _ = executor.query("q", _runtime(), messages=[_assistant_message(tool_call)])

    result = messages[-1]
    assert result["error"] == "Blocked by security policy."
    assert result["content"][0]["content"] == ""


def test_dry_run_executes_everything_but_emits_non_allow_decisions(tmp_path):
    reporter = _configure(tmp_path, "block", mode="dry_run")
    with interbolt.get_runtime().agent_context_sync(DEFAULT_AGENT_ID):
        executor = InterboltToolsExecutor(suite_name="test-suite")
        tool_call = FunctionCall(function="danger_tool", args={"value": "hi"}, id="1")
        _, _, _, messages, _ = executor.query("q", _runtime(), messages=[_assistant_message(tool_call)])

    result = messages[-1]
    assert result["error"] is None
    assert result["content"][0]["content"] == "done"
    assert len(reporter.events) == 1
    # dry_run forces `decision.action` to allow, but the emitted `Event`'s
    # `outcome` still records what the policy actually computed.
    assert reporter.events[0].outcome.value == "block"


class _ProbingInner:
    """Fake inner pipeline: records run.tainted at the start of each run, then taints."""

    def __init__(self) -> None:
        self.name = "probe-inner"
        self.run_tainted_at_start: list[bool] = []

    def query(self, query, runtime, env=None, messages=None, extra_args=None):
        decision = interbolt.get_runtime().check(tool="test-suite.probe", args={}, agent_id=DEFAULT_AGENT_ID)
        self.run_tainted_at_start.append(decision.run_tainted)
        taint("payload", source="tool:danger_tool")
        return query, runtime, env, messages or [], extra_args or {}


def test_run_scoped_pipeline_isolates_run_id_and_run_tainted(tmp_path):
    _configure(tmp_path, "allow", extra_sources='  - name: "tool:danger_tool"\n    trust: untrusted')
    inner = _ProbingInner()
    run_index_path = tmp_path / "run_index.jsonl"
    pipeline = RunScopedPipeline(inner, run_index_path)

    pipeline.query("q", _runtime(), messages=[])
    pipeline.query("q", _runtime(), messages=[])

    assert inner.run_tainted_at_start == [False, False]
    lines = [json.loads(line) for line in run_index_path.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["run_id"] != lines[1]["run_id"]
    # No TraceLogger active here, so Logger.get() falls back to NullLogger
    # (no .context attribute) -- the getattr guard must not raise, and the
    # case-identity fields must be present but None.
    assert lines[0]["user_task_id"] is None
    assert lines[0]["injection_task_id"] is None


def test_run_scoped_pipeline_carries_case_identity_from_trace_logger(tmp_path):
    """Verifies the Logger().get().context side-channel actually works.

    RunScopedPipeline.query reads user_task_id/injection_task_id off
    Logger().get().context instead of taking them as a query() argument
    (AgentDojo's own pipeline.query() call sites never pass task ids in).
    This only works if AgentDojo's real TraceLogger has already pushed its
    context onto LOGGER_STACK by the time query() runs -- which is true
    for the live benchmark loop (TraceLogger's `with` block in
    agentdojo.benchmark.run_task_with_injection_tasks fully encloses the
    pipeline.query() call), but is worth pinning down here against the
    real TraceLogger class, not a stand-in, so a future AgentDojo change
    to that timing fails this test instead of silently degrading
    run_index.jsonl to all-None join keys.
    """
    _configure(tmp_path, "allow", extra_sources='  - name: "tool:danger_tool"\n    trust: untrusted')
    inner = _ProbingInner()
    run_index_path = tmp_path / "run_index.jsonl"
    pipeline = RunScopedPipeline(inner, run_index_path)

    delegate = OutputLogger(logdir=str(tmp_path))
    with TraceLogger(
        delegate,
        suite_name="banking",
        user_task_id="user_task_0",
        injection_task_id="injection_task_1",
        attack_type="important_instructions",
        pipeline_name="test-pipeline",
        injections={},
        benchmark_version="v1.2.2",
    ):
        pipeline.query("q", _runtime(), messages=[])

    lines = [json.loads(line) for line in run_index_path.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]["user_task_id"] == "user_task_0"
    assert lines[0]["injection_task_id"] == "injection_task_1"
