"""Shared raw-run-JSON parsing for the two case-study panels (Figure 2 / CS1, Figure 5 / CS3).
Self-contained: reads a single AgentDojo trace JSON's `messages` array directly (assistant
`tool_calls` + the matching `tool` response, including its `error` field when a policy blocked
the call). No dependency on `call_records.jsonl`/`interbolt_events.jsonl`/`run_trajectory` --
this is one hand-picked case per figure, not a pipeline over all cases.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolStep:
    tool: str
    args: dict
    blocked: bool
    error: str | None
    result: str | None


def _tool_content_text(content) -> str:
    if isinstance(content, list):
        return "\n".join(c.get("content", "") for c in content if c.get("type") == "text").strip()
    return str(content or "").strip()


def load_run(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def tool_trajectory(messages: list[dict]) -> list[ToolStep]:
    steps: list[ToolStep] = []
    for i, m in enumerate(messages):
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            continue
        for tc in m["tool_calls"]:
            blocked = False
            error: str | None = None
            result: str | None = None
            # The matching tool response is the next "tool"-role message in AgentDojo's
            # single-call-per-turn transcripts; its `error` field marks a policy block.
            for followup in messages[i + 1 :]:
                if followup.get("role") == "tool":
                    error = followup.get("error")
                    blocked = bool(error)
                    if not blocked:
                        result = _tool_content_text(followup.get("content"))
                    break
                if followup.get("role") == "assistant":
                    break
            steps.append(
                ToolStep(tool=tc["function"], args=tc.get("args") or {}, blocked=blocked, error=error, result=result)
            )
    return steps


def final_assistant_message(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            parts = [c["content"] for c in m["content"] if c.get("type") == "text"]
            if parts:
                return "\n".join(parts).strip()
    return ""


def injected_text(injections: dict) -> str:
    for v in injections.values():
        text = v.strip()
        if text:
            return text
    return ""


def format_args(tool: str, args: dict) -> str:
    if not args:
        return f"{tool}()"
    parts = [f"{k}={v!r}" for k, v in args.items()]
    return f"{tool}({', '.join(parts)})"
