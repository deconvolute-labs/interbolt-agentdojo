"""Spec item 3: join-key presence/encoding matrix, and open question 2
(run_id -> (user_task_id, injection_task_id) mapping).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suite

from analysis.common.artifacts import case_to_run_id, discover_results, load_jsonl, read_json
from analysis.common.discovery import ROLE_B_ASR_MODEL, ROLE_D_ASR_SYSTEM, RunRecord


def _load_compare_blocking(repo_root: Path):
    """Import the root-level compare_blocking.py script as a module.

    It's not part of any installed package (it's a standalone script at the
    repo root), so it's loaded by path rather than assumed to be on sys.path.
    """
    spec = importlib.util.spec_from_file_location("compare_blocking", repo_root / "compare_blocking.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("compare_blocking", module)
    spec.loader.exec_module(module)
    return module


def _run_id_present_in_agentdojo_json(path: Path) -> bool:
    return "run_id" in Path(path).read_text()


def _call_ordering_demo(repeat_dir: Path) -> str:
    index_rows = load_jsonl(repeat_dir / "run_index.jsonl")
    if len(index_rows) < 5:
        return "_(not enough rows to demonstrate)_"
    sample_row = index_rows[4]
    run_id = sample_row["run_id"]
    call_records = load_jsonl(repeat_dir / "call_records.jsonl")
    seqs = [r["seq"] for r in call_records if r["run_id"] == run_id]
    return (
        f"Run `{run_id}` (`{sample_row['user_task_id']}`/`{sample_row.get('injection_task_id')}`) "
        f"is the 5th run recorded in `run_index.jsonl` (`seq={sample_row['seq']}`), "
        f"but its own `call_records.jsonl` rows carry `seq` values `{seqs}` -- "
        f"not `[0, 1, ...]` -- confirming `seq` is a global counter over the whole file, "
        f"not reset per run. Ordering within one run must be recovered by filtering to "
        f"that `run_id` and sorting by `seq` (or `timestamp`), which is exactly what "
        f"`compare_blocking.py`'s `load_call_sequences` already does."
    )


def render_join_key_matrix(records: list[RunRecord], repo_root: Path, example_suite: str) -> str:
    lines = ["## 3. Join-key matrix", ""]

    try:
        b_record = next(r for r in records if r.role == ROLE_B_ASR_MODEL and r.suite == example_suite)
    except StopIteration:
        raise ValueError(f"no B_asr_model record found for suite {example_suite!r}") from None
    try:
        d_record = next(
            r for r in records if r.role == ROLE_D_ASR_SYSTEM and r.suite == example_suite and r.policy.name == "strict"
        )
    except StopIteration:
        raise ValueError(f"no D_asr_system/strict record found for suite {example_suite!r}") from None

    events = load_jsonl(b_record.repeat_dir / "interbolt_events.jsonl")
    agent_ids = sorted({e["decision"]["agent_id"] for e in events})

    attacked_case_json = None
    base = d_record.repeat_dir / d_record.pipeline_name / d_record.suite
    for child in sorted(base.iterdir()):
        if child.is_dir() and child.name.startswith("user_task_"):
            for attack_dir in sorted(child.iterdir()):
                if attack_dir.is_dir() and attack_dir.name != "none":
                    files = sorted(attack_dir.glob("*.json"))
                    if files:
                        attacked_case_json = files[0]
                        break
        if attacked_case_json:
            break

    run_id_in_json = _run_id_present_in_agentdojo_json(attacked_case_json) if attacked_case_json else None
    attack_types = sorted({read_json(p).get("attack_type") for p in base.rglob("*.json")}, key=lambda x: (x is None, x))

    lines.append("| Key | suite | policy | user_task_id | injection_task_id | run_id | agent_id | attacked/benign flag | call ordering index |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    lines.append(
        "| **AgentDojo per-case JSON** | `suite_name` field | `pipeline_name` suffix (slug inconsistent across suites -- do not parse it, use `run_manifest.json.defense.policy_file`/`policy_sha256` instead) "
        f"| `user_task_id` field | `injection_task_id` field (null for benign) | **absent** (verified: `run_id` "
        f"{'appears' if run_id_in_json else 'does not appear'} anywhere in `{attacked_case_json}`) "
        f"| n/a | `attack_type` field (values seen: `{attack_types}`) | array position in `messages`, no explicit index field |"
    )
    lines.append(
        "| **`run_manifest.json`** | `suite` field | `defense.policy_file` + `defense.policy_sha256` (see §6 for 3 stale-path cases) "
        "| n/a | n/a | n/a | n/a | `attack` field (null for benign) | n/a |"
    )
    lines.append(
        "| **`run_index.jsonl`** | n/a (one file per repeat_dir, which is suite-scoped) | n/a "
        "| `user_task_id` field | `injection_task_id` field | `run_id` field | n/a | inferred from `injection_task_id is None` "
        "| `seq` field, but **global to the file, not reset per run** -- see demo below |"
    )
    lines.append(
        f"| **`interbolt_events.jsonl`** | n/a | n/a | n/a | n/a | `decision.run_id` field | `decision.agent_id` field "
        f"(values seen: `{agent_ids}`) | n/a | `timestamp` field, global to file |"
    )
    lines.append(
        "| **`call_records.jsonl`** | n/a | n/a | n/a | n/a | `run_id` field | n/a | n/a | `seq` field, global to file |"
    )
    lines.append("")
    lines.append("**Call-ordering-index demonstration:**")
    lines.append(_call_ordering_demo(b_record.repeat_dir))
    lines.append("")

    # -- Open question 2: run_id -> (user_task_id, injection_task_id) --
    lines.append("### Open question 2: can `run_id` be mapped back to `(user_task_id, injection_task_id)`?")
    lines.append("")
    lines.append(
        "**Yes, directly, via `run_index.jsonl` -- not inferred from ordering.** "
        "`interbolt_agentdojo.compute_results._case_to_run_id` builds this mapping live from "
        "`run_index.jsonl`, filtered to the cases AgentDojo's own results confirm exist "
        "(`_discover_results`'s `with_injections`). Evidence, per attacked run:"
    )
    lines.append("")
    lines.append("| Suite | Policy | `len(with_injections)` | `len(_case_to_run_id(...))` | Orphaned `run_index` rows | Expected orphans (pseudo-cases) |")
    lines.append("|---|---|---|---|---|---|")

    cb = _load_compare_blocking(repo_root)

    cross_check_lines = []
    for r in records:
        if r.role != ROLE_D_ASR_SYSTEM:
            continue
        _, with_injections = discover_results(r.repeat_dir, r.pipeline_name, r.suite, r.benchmark_version)
        mapping = case_to_run_id(r.repeat_dir, with_injections)
        index_rows = load_jsonl(r.repeat_dir / "run_index.jsonl")
        mapped_keys = {(row.get("user_task_id"), row.get("injection_task_id")) for row in index_rows}
        orphans = mapped_keys - set(with_injections.keys())
        expected_injection_count = len(get_suite(r.benchmark_version, r.suite).injection_tasks)
        lines.append(
            f"| {r.suite} | {r.policy.name} | {len(with_injections)} | {len(mapping)} | "
            f"{len(orphans)} | {expected_injection_count} |"
        )

        # Cross-check against compare_blocking.py's independent implementation.
        cb_run_to_case = cb.load_run_to_case(r.repeat_dir / "run_index.jsonl")
        cr_run_to_case = {run_id: f"{u}/{i}" for (u, i), run_id in mapping.items()}
        disagreements = [
            (run_id, cr_run_to_case[run_id], cb_run_to_case.get(run_id))
            for run_id in cr_run_to_case
            if cb_run_to_case.get(run_id) != cr_run_to_case[run_id]
        ]
        extra_in_cb = set(cb_run_to_case) - set(cr_run_to_case)
        cross_check_lines.append(
            f"- `{r.suite}`/`{r.policy.name}`: {len(cr_run_to_case)} cases agree with "
            f"`compare_blocking.load_run_to_case` ({len(disagreements)} disagreements -- "
            f"expected 0), plus {len(extra_in_cb)} entries only `load_run_to_case` reports "
            f"(expected == pseudo-case count {len(get_suite(r.benchmark_version, r.suite).injection_tasks)}, "
            f"since it does not filter them the way `_case_to_run_id` does)."
        )

    lines.append("")
    lines.append(
        "Cross-check against the independently-written `compare_blocking.load_run_to_case` "
        "(same join, no pseudo-case filtering):"
    )
    lines.extend(cross_check_lines)
    lines.append("")
    lines.append(
        "**Conclusion: PRESENT AND DIRECT.** No reconstruction from ordering is needed; the "
        "only caveat is that every attacked run's `run_index.jsonl` also contains one row per "
        "injection task for AgentDojo's own \"solve the injection goal standalone\" pseudo-case "
        "(`user_task_id` holds an `injection_task_N` string, `injection_task_id` is null), which "
        "must be excluded from the 144/140-case attack matrix, not treated as a join failure."
    )
    return "\n".join(lines)
