"""Artifact readers: thin wrappers over the already-correct `compute_results.py`
loaders (do not reimplement the join/discovery logic they already get right),
plus a few new pure readers for formats `compute_results.py` never needed to
read: policy YAML and the summary CSV.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from interbolt_agentdojo.compute_results import (
    _case_to_run_id,
    _classify_case,
    _discover_results,
    _events_by_run_id,
    _interbolt_blocked_target_sink,
    _interbolt_event_summary,
    _load_call_records,
    _load_jsonl,
    _quartet_repeat_metrics,
    _reached_target_sink,
    _selected_run_ids,
    _target_tools,
)

# Re-exported under public names -- these are the exact join/discovery
# functions that already produced the published, verified CSV.
load_jsonl = _load_jsonl
load_call_records = _load_call_records
events_by_run_id = _events_by_run_id
discover_results = _discover_results
case_to_run_id = _case_to_run_id

# Same, for the taxonomy classifier the quartet pipeline already gets right.
classify_case = _classify_case
reached_target_sink = _reached_target_sink
target_tools = _target_tools
interbolt_blocked_target_sink = _interbolt_blocked_target_sink

# Repeat-level aggregate helpers -- reused by Phase 1's checks as the
# "expected" side of a cross-check, and by the case-table builders for
# retry-dedup (`selected_run_ids`) and block/approval/error counting.
selected_run_ids = _selected_run_ids
interbolt_event_summary = _interbolt_event_summary
quartet_repeat_metrics = _quartet_repeat_metrics


def suite_scoped_dir(root: Path, suite: str) -> Path:
    """`root/suite`, unless `root`'s own name already is `suite` (the caller
    pointed --results-root/--policies-root directly at a suite subdirectory) --
    avoids doubling the suite segment in that case."""
    root = Path(root)
    return root if root.name == suite else root / suite


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def load_policy_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """(header, rows) preserving raw string cells, for verbatim display."""
    with Path(path).open(newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def case_json_path(
    repeat_dir: Path, pipeline_name: str, suite: str, user_task_id: str,
    injection_task_id: str | None, attack_type: str | None = None,
) -> Path:
    """Raw AgentDojo trace JSON path for one case. `injection_task_id=None` covers both a
    genuine benign case and an injection task's own standalone pseudo-case (its `user_task_id`
    is the injection task id itself in that case, e.g. "injection_task_1")."""
    base = Path(repeat_dir) / pipeline_name / suite / user_task_id
    if injection_task_id is None:
        return base / "none" / "none.json"
    return base / (attack_type or "important_instructions") / f"{injection_task_id}.json"


def raw_tool_call_names(messages: list[dict]) -> list[str]:
    """Unqualified tool function names called, in order, from a raw run JSON's `messages`.

    Needed for run roles that never go through Interbolt's executor at all -- A ("no attack, no
    defense") has no `call_records.jsonl`/`interbolt_events.jsonl`, so the only record of what was
    called is this message log."""
    names: list[str] = []
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                names.append(tc["function"])
    return names


def count_blocks(events: list[dict]) -> int:
    """Count of `decision.action == "block"` events -- excludes require_approval,
    which is tracked separately (approvals are auto-denied, not blocked)."""
    return sum(1 for e in events if e["decision"]["action"] == "block")


@dataclass(frozen=True)
class CallDecision:
    seq: int
    tool: str
    args: dict
    action: str
    matched_rule: str | None
    outcome: str  # raw interbolt_events.jsonl "outcome" field, e.g. "allow", "block", "evaluation_error"
    run_tainted: bool  # call_records.jsonl's own "run_tainted" flag at this call


def run_trajectory(repeat_dir: Path, run_id: str) -> list[CallDecision]:
    """The ordered per-call sequence for one run_id: call_records.jsonl (sorted by `seq`)
    zipped against interbolt_events.jsonl (file order) for the same run_id.

    Empirically, for a given run_id the two logs are 1:1 in the same order -- every
    dispatched call gets exactly one policy decision, recorded in dispatch order. This
    also means call_records.jsonl already excludes AgentDojo's iteration-cap trailing
    tool call (the one with no matching tool response): it was never dispatched to
    Interbolt, so it was never logged here. Downstream alignment work (T2.1's
    strict-vs-targeted divergence) gets that exclusion for free by sourcing from this
    function rather than the raw message log.

    Fails loudly (AssertionError) if a run's two logs disagree in length or per-position
    tool name -- that would mean the alignment assumption this helper encodes is wrong
    for that run, and silently proceeding would produce a misleading trajectory.
    """
    calls = sorted(
        (c for c in load_call_records(repeat_dir).get(run_id, [])),
        key=lambda c: c["seq"],
    )
    events = [e for e in load_jsonl(repeat_dir / "interbolt_events.jsonl") if e["decision"]["run_id"] == run_id]
    if len(calls) != len(events):
        raise AssertionError(
            f"run_trajectory: call_records/interbolt_events length mismatch for run_id={run_id!r} "
            f"in {repeat_dir}: {len(calls)} calls vs {len(events)} events"
        )
    trajectory: list[CallDecision] = []
    for i, (call, event) in enumerate(zip(calls, events)):
        decision = event["decision"]
        if call["tool"] != decision["tool"]:
            raise AssertionError(
                f"run_trajectory: tool mismatch at position {i} for run_id={run_id!r} in {repeat_dir}: "
                f"call_records={call['tool']!r} vs interbolt_events={decision['tool']!r}"
            )
        trajectory.append(
            CallDecision(
                seq=call["seq"],
                tool=call["tool"],
                args=call["args"],
                action=decision["action"],
                matched_rule=decision.get("matched_rule"),
                outcome=event["outcome"],
                run_tainted=call["run_tainted"],
            )
        )
    return trajectory
