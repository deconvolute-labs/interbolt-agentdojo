"""Spec item 4: is AgentDojo's own scoring retained, and what's the source-of-truth rule?"""

from __future__ import annotations

from analysis.common.artifacts import discover_results
from analysis.common.discovery import RunRecord


def render_scoring_source_section(records: list[RunRecord]) -> str:
    lines = ["## 4. Scoring source of truth", ""]

    total = 0
    scored = 0
    for r in records:
        if r.pipeline_name is None:
            continue
        without_injections, with_injections = discover_results(r.repeat_dir, r.pipeline_name, r.suite, r.benchmark_version)
        for result in {**without_injections, **with_injections}.values():
            total += 1
            if result.utility is not None and result.security is not None:
                scored += 1

    pct = (scored / total * 100) if total else 0.0
    lines.append(
        f"**{scored}/{total} ({pct:.1f}%) discovered AgentDojo per-case result records have "
        f"non-null `utility` and `security` fields.**"
    )
    lines.append("")
    lines.append(
        "Per the spec's own precedence rule, restated and enforced here: **AgentDojo's own "
        "`utility`/`security` booleans are the source of truth for scoring; Interbolt's "
        "`interbolt_events.jsonl`/`call_records.jsonl` are the source of truth for decisions.** "
        "No scoring boolean should ever be recomputed from a tool-call trajectory when AgentDojo "
        "already scored it directly. This is exactly what `compute_results.py` already does -- "
        "`_classify_case` consumes `result.security` (an AgentDojo-scored boolean) directly, and "
        "only uses `call_records.jsonl`/`interbolt_events.jsonl` to answer a non-scoring question "
        "(\"was the target sink reached / blocked\") via `_reached_target_sink` / "
        "`_interbolt_blocked_target_sink`."
    )
    return "\n".join(lines)
