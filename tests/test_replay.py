"""replay_policy.py tests: replay is a pure function of (call_records, policy).

No network calls, and no live interbolt run needed for the replay half --
only to build the tiny synthetic corpus via the executor's own recording
path, exercising the same code the executor tests do.
"""

from __future__ import annotations

from pathlib import Path

import interbolt
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime, make_function
from agentdojo.types import ChatAssistantMessage
from interbolt import InMemoryReporter, Policy

from interbolt_agentdojo.executor import DEFAULT_AGENT_ID, InterboltToolsExecutor
from interbolt_agentdojo.replay_policy import _evaluate_record, _load_corpus


def get_data(x: str) -> str:
    """A read tool whose output is untrusted.

    :param x: An argument.
    """
    return "data"


def danger_tool(value: str) -> str:
    """A state-changing tool.

    :param value: An argument.
    """
    return "done"


_RECORDING_POLICY = """
version: "2.0"
defaults:
  sink_action: allow
sources:
  - name: "tool:get_data"
    trust: untrusted
sinks: {}
"""

_ALLOW_ALL_POLICY = """
version: "2.0"
defaults:
  sink_action: allow
sources: []
sinks: {}
"""

_STRICT_POLICY = """
version: "2.0"
defaults:
  sink_action: allow
sources:
  - name: "tool:get_data"
    trust: untrusted
sinks:
  test-suite.danger_tool:
    rules:
      - name: block_when_tainted
        when: run.tainted
        action: block
      - name: default
        action: allow
"""


def _record_corpus(tmp_path: Path) -> Path:
    policy_path = tmp_path / "recording.yaml"
    policy_path.write_text(_RECORDING_POLICY)
    interbolt.configure(policy=Policy.from_file(str(policy_path)), mode="dry_run", reporter=InMemoryReporter())

    call_records_path = tmp_path / "call_records.jsonl"
    runtime = FunctionsRuntime(functions=[make_function(get_data), make_function(danger_tool)])
    executor = InterboltToolsExecutor(call_records_path=call_records_path, suite_name="test-suite")

    with interbolt.get_runtime().agent_context_sync(DEFAULT_AGENT_ID):
        get_call = FunctionCall(function="get_data", args={"x": "1"}, id="1")
        _, _, _, messages, _ = executor.query(
            "q", runtime, messages=[ChatAssistantMessage(role="assistant", content=None, tool_calls=[get_call])]
        )
        danger_call = FunctionCall(function="danger_tool", args={"value": "hi"}, id="2")
        executor.query(
            "q",
            runtime,
            messages=[*messages, ChatAssistantMessage(role="assistant", content=None, tool_calls=[danger_call])],
        )

    return call_records_path


def test_replay_action_deltas_between_allow_all_and_strict(tmp_path):
    call_records_path = _record_corpus(tmp_path)
    records = _load_corpus(call_records_path)
    assert len(records) == 2

    allow_all_path = tmp_path / "allow_all.yaml"
    allow_all_path.write_text(_ALLOW_ALL_POLICY)
    strict_path = tmp_path / "strict.yaml"
    strict_path.write_text(_STRICT_POLICY)

    allow_all_policy = Policy.from_file(str(allow_all_path))
    strict_policy = Policy.from_file(str(strict_path))

    danger_record = next(r for r in records if r["tool"] == "test-suite.danger_tool")
    assert danger_record["run_tainted"] is True

    _, allow_all_action, _ = _evaluate_record(danger_record, allow_all_policy)
    _, strict_action, _ = _evaluate_record(danger_record, strict_policy)

    assert allow_all_action == "allow"
    assert strict_action == "block"
