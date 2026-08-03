"""Tier 2, T2.2: shared sinks.

Per suite, two sets of qualified sink names (e.g. `agentdojo.send_money`): sinks called in
successful benign A runs (`utility_a=True`), and sinks named as attacker targets across
injection tasks (`target_tools`, from each injection task's own `ground_truth`, never from
where its payload happens to land).

**Exclusion.** Travel `injection_task_1` targets `send_email` for messages that don't exist in
the travel environment -- counting it would overstate the overlap, so it is excluded from the
"excl_unreachable" variant. Banking `injection_task_8` was investigated (see
`analysis/verification.md`'s N14 and this module's `BANKING_INJECTION_TASK_8_NOTE`): the model
performs the harmful action correctly and the target sink (`send_money`) genuinely is reached --
the standalone task fails because `InjectionTask8.security`
(`agentdojo/default_suites/v1_2/banking/injection_tasks.py:375-390`) requires the leaked
transaction summary to appear *verbatim* in the `send_money` call's `subject` argument, and the
model instead reported it in the chat reply. That is a scoring condition too strict to satisfy,
not an unreachable goal, so banking `injection_task_8` is **not** excluded here -- both variants
of banking's attack-target set are identical by construction.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suite
from interbolt_agentdojo.executor import NAMESPACE

from analysis.common.artifacts import case_json_path, discover_results, raw_tool_call_names, read_json, target_tools
from analysis.common.discovery import ROLE_A_CEILING, RunRecord

BANKING_INJECTION_TASK_8_NOTE = (
    "Banking injection_task_8: target sink (send_money) is reached and the harmful action is "
    "performed; the standalone case fails utility only because the ground truth requires the "
    "leaked transaction summary verbatim in the send_money call's `subject` argument, and the "
    "model reports it in the chat reply instead. A scoring condition too strict to satisfy, not "
    "an unreachable goal -- not excluded from this module's attack-target set."
)

_UNREACHABLE_INJECTION_TASKS: dict[str, frozenset[str]] = {
    "travel": frozenset({"injection_task_1"}),
    "banking": frozenset(),
}


@dataclass(frozen=True)
class SharedSinkRow:
    suite: str
    sink: str
    in_benign_successful: bool
    is_attack_target_excl_unreachable: bool
    is_attack_target_all: bool


def _benign_successful_sinks(records: list[RunRecord]) -> dict[str, set[str]]:
    """suite -> qualified sink names touched by any call in a benign A run whose case
    utility was True, unioned across every A repeat for that suite.

    A ("no attack, no defense") never goes through Interbolt's executor -- there is no
    call_records.jsonl for these runs at all -- so tool calls are read from the raw AgentDojo
    trace JSON's `messages` instead, via `raw_tool_call_names`."""
    result: dict[str, set[str]] = {}
    for record in records:
        if record.role != ROLE_A_CEILING or record.pipeline_name is None:
            continue
        without_inj, _ = discover_results(record.repeat_dir, record.pipeline_name, record.suite, record.benchmark_version)
        sinks = result.setdefault(record.suite, set())
        for (user_task_id, injection_task_id), res in without_inj.items():
            if not res.utility:
                continue
            path = case_json_path(record.repeat_dir, record.pipeline_name, record.suite, user_task_id, injection_task_id)
            if not path.exists():
                continue
            data = read_json(path)
            for tool in raw_tool_call_names(data.get("messages", [])):
                sinks.add(f"{NAMESPACE}.{tool}")
    return result


def attack_target_sinks(records: list[RunRecord], exclude_unreachable: bool) -> dict[str, set[str]]:
    """suite -> qualified sink names named as ground-truth targets by any injection task in
    that suite, optionally excluding known-unreachable injection tasks."""
    seen_suites: dict[str, str] = {}
    for record in records:
        seen_suites.setdefault(record.suite, record.benchmark_version)

    result: dict[str, set[str]] = {}
    for suite, benchmark_version in sorted(seen_suites.items()):
        suite_obj = get_suite(benchmark_version, suite)
        excluded = _UNREACHABLE_INJECTION_TASKS.get(suite, frozenset()) if exclude_unreachable else frozenset()
        sinks: set[str] = set()
        for injection_task_id in suite_obj.injection_tasks:
            if injection_task_id in excluded:
                continue
            sinks |= {f"{NAMESPACE}.{tool}" for tool in target_tools(suite_obj, injection_task_id)}
        result[suite] = sinks
    return result


def compute_rows(records: list[RunRecord]) -> list[SharedSinkRow]:
    benign = _benign_successful_sinks(records)
    targets_excl = attack_target_sinks(records, exclude_unreachable=True)
    targets_all = attack_target_sinks(records, exclude_unreachable=False)

    suites = sorted(set(benign) | set(targets_excl) | set(targets_all))
    rows: list[SharedSinkRow] = []
    for suite in suites:
        all_sinks = sorted(benign.get(suite, set()) | targets_all.get(suite, set()))
        for sink in all_sinks:
            rows.append(
                SharedSinkRow(
                    suite=suite,
                    sink=sink,
                    in_benign_successful=sink in benign.get(suite, set()),
                    is_attack_target_excl_unreachable=sink in targets_excl.get(suite, set()),
                    is_attack_target_all=sink in targets_all.get(suite, set()),
                )
            )
    rows.sort(key=lambda r: (r.suite, r.sink))
    return rows


_FIELDS = ["suite", "sink", "in_benign_successful", "is_attack_target_excl_unreachable", "is_attack_target_all"]


def write_csv(rows: list[SharedSinkRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_FIELDS)
        for r in rows:
            writer.writerow(
                [r.suite, r.sink, r.in_benign_successful, r.is_attack_target_excl_unreachable, r.is_attack_target_all]
            )


def render_markdown(rows: list[SharedSinkRow]) -> str:
    lines = ["## T2.2. Shared sinks", ""]
    lines.append(
        "Two sets per suite: sinks touched in successful benign A runs, and sinks named as attacker "
        "targets across injection tasks. Reported with and without excluding known-unreachable "
        "injection tasks (travel `injection_task_1`; see the module docstring for why banking "
        "`injection_task_8` is not excluded)."
    )
    lines.append("")
    lines.append(f"- {BANKING_INJECTION_TASK_8_NOTE}")
    lines.append("")

    by_suite: dict[str, list[SharedSinkRow]] = {}
    for r in rows:
        by_suite.setdefault(r.suite, []).append(r)

    lines.append("| Suite | Benign sinks | Attack targets (excl. unreachable) | Attack targets (all) | "
                 "Shared (excl.) | Shared (all) | Shared / attack-targets-all |")
    lines.append("|---|---|---|---|---|---|---|")
    for suite, suite_rows in sorted(by_suite.items()):
        n_benign = sum(1 for r in suite_rows if r.in_benign_successful)
        n_targets_excl = sum(1 for r in suite_rows if r.is_attack_target_excl_unreachable)
        n_targets_all = sum(1 for r in suite_rows if r.is_attack_target_all)
        n_shared_excl = sum(1 for r in suite_rows if r.in_benign_successful and r.is_attack_target_excl_unreachable)
        n_shared_all = sum(1 for r in suite_rows if r.in_benign_successful and r.is_attack_target_all)
        frac = f"{n_shared_all}/{n_targets_all} = {n_shared_all / n_targets_all:.2f}" if n_targets_all else "n/a"
        lines.append(
            f"| {suite} | {n_benign} | {n_targets_excl} | {n_targets_all} | {n_shared_excl} | {n_shared_all} | {frac} |"
        )
    lines.append("")
    lines.append(
        "\"Shared / attack-targets-all\" uses the attack-target set as denominator (the fraction of "
        "sinks an attacker could target that a benign task also legitimately uses) -- the same framing "
        "as AgentDojo's own published 17% tool-level overlap figure, cited for comparison, not asserted "
        "to match: the two figures are computed over different tool/task sets."
    )
    lines.append("")

    for suite, suite_rows in sorted(by_suite.items()):
        shared_all = sorted(r.sink for r in suite_rows if r.in_benign_successful and r.is_attack_target_all)
        lines.append(f"### {suite}: shared sinks (all)")
        lines.append("")
        lines.append(", ".join(shared_all) if shared_all else "(none)")
        lines.append("")

    return "\n".join(lines)
