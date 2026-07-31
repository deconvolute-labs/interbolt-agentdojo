#!/usr/bin/env python3
"""Compare policy decisions (allow/block) between two runs.

"Blocking" decisions live in interbolt_events.jsonl (the policy's decision
log), not the AgentDojo result files, so this compares policy behavior
rather than utility/security verdicts (see compare_utility_security.py for
that).

Since run_id is randomly generated per run, it can't be compared directly
across two separate policy runs. Instead we join through run_index.jsonl to
recover the (user_task_id, injection_task_id) case behind each run_id.

IMPORTANT: comparing the *sets of blocked calls* between two runs is wrong,
because a call only shows up in the log if the model attempted it. The two
runs are separate rollouts: the moment one policy blocks something the other
allows (or vice versa), the model sees a different tool result and the
trajectories diverge from there on -- every later call becomes
incomparable. A tool that only appears as blocked in one run's log is very
often just a call the other run's trajectory never reached, not a policy
disagreement.

So instead we compare, for each (case, tool) pair, the action taken on the
Nth attempted call to that tool -- but only where *both* runs actually
attempted that Nth call. Those are the only apples-to-apples comparisons:
identical case, identical tool, identical position in the trajectory,
attempted by both agents. If the recorded action differs there, that's a
genuine policy divergence. Calls attempted by only one run are reported
separately as trajectory differences, not divergences.

Usage:
    python compare_blocking.py <path_a> <path_b>

Each path can be any directory inside a run's tree, e.g. the AgentDojo result
dir used by compare_utility_security.py:

    runs/published/banking-gpt-4o-mini/D_asr_system_strict/repeat_0/\
gpt-4o-mini-2024-07-18-interbolt-strict-enforce/banking

    runs/published/banking-gpt-4o-mini/D_asr_system_targeted/repeat_0/\
gpt-4o-mini-2024-07-18-interbolt-banking-enforce/banking

The script walks upward from each path to find the ancestor directory that
holds `run_index.jsonl` and `interbolt_events.jsonl` (typically the
`repeat_N` directory).
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

REQUIRED_FILES = ("run_index.jsonl", "interbolt_events.jsonl")


def find_run_dir(start: Path) -> Path:
    for candidate in [start, *start.resolve().parents]:
        if all((candidate / name).is_file() for name in REQUIRED_FILES):
            return candidate
    raise ValueError(
        f"Could not find a directory containing {REQUIRED_FILES} "
        f"at or above {start}"
    )


def load_run_to_case(run_index_path: Path) -> dict[str, str]:
    run_to_case: dict[str, str] = {}
    for line in run_index_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        user_task_id = row["user_task_id"]
        injection_task_id = row.get("injection_task_id")
        case = (
            f"{user_task_id}/{injection_task_id}"
            if injection_task_id
            else user_task_id
        )
        run_to_case[row["run_id"]] = case
    return run_to_case


def load_call_sequences(
    events_path: Path, run_to_case: dict[str, str]
) -> dict[tuple[str, str], list[str]]:
    """(case, tool) -> ordered list of actions, one per attempted call.

    Events are grouped by run_id and ordered by timestamp before being
    appended, so repeated calls to the same tool within a case line up by
    the order they actually happened in that run.
    """
    raw_events: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    unmapped_runs: set[str] = set()

    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        decision = event.get("decision") or {}
        run_id = decision.get("run_id")
        case = run_to_case.get(run_id)
        if case is None:
            unmapped_runs.add(run_id)
            continue
        raw_events[run_id].append(
            (event.get("timestamp", ""), decision.get("tool"), decision.get("action"))
        )

    if unmapped_runs:
        print(
            f"WARNING: {len(unmapped_runs)} run_id(s) in {events_path} "
            f"have no entry in run_index.jsonl: {sorted(unmapped_runs)}"
        )

    sequences: dict[tuple[str, str], list[str]] = defaultdict(list)
    for run_id, events in raw_events.items():
        case = run_to_case[run_id]
        for _, tool, action in sorted(events, key=lambda e: e[0]):
            sequences[(case, tool)].append(action)
    return sequences


def natural_key(case: str):
    parts = case.split("/")
    key = []
    for part in parts:
        prefix, _, num = part.rpartition("_")
        key.append((prefix, int(num) if num.isdigit() else num))
    return key


def load_policy(path: Path) -> tuple[dict[tuple[str, str], list[str]], set[str]]:
    run_dir = find_run_dir(path)
    run_to_case = load_run_to_case(run_dir / "run_index.jsonl")
    sequences = load_call_sequences(run_dir / "interbolt_events.jsonl", run_to_case)
    return sequences, set(run_to_case.values())


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <path_a> <path_b>")
        sys.exit(1)

    path_a = Path(sys.argv[1])
    path_b = Path(sys.argv[2])

    seq_a, cases_a = load_policy(path_a)
    seq_b, cases_b = load_policy(path_b)

    print(f"Policy A: {path_a} ({len(cases_a)} cases)")
    print(f"Policy B: {path_b} ({len(cases_b)} cases)")

    only_in_a = sorted(cases_a - cases_b, key=natural_key)
    only_in_b = sorted(cases_b - cases_a, key=natural_key)
    if only_in_a:
        print(f"Cases only in A: {only_in_a}")
    if only_in_b:
        print(f"Cases only in B: {only_in_b}")

    common_cases = cases_a & cases_b
    all_keys = sorted(
        (k for k in set(seq_a) | set(seq_b) if k[0] in common_cases),
        key=lambda k: (natural_key(k[0]), k[1]),
    )

    divergences = []  # (case, tool, occurrence_index, action_a, action_b)
    trajectory_only = []  # (case, tool, occurrence_index, "A"|"B", action)

    for case, tool in all_keys:
        list_a = seq_a.get((case, tool), [])
        list_b = seq_b.get((case, tool), [])
        n = min(len(list_a), len(list_b))
        for i in range(n):
            if list_a[i] != list_b[i]:
                divergences.append((case, tool, i, list_a[i], list_b[i]))
        for i in range(n, len(list_a)):
            trajectory_only.append((case, tool, i, "A", list_a[i]))
        for i in range(n, len(list_b)):
            trajectory_only.append((case, tool, i, "B", list_b[i]))

    print(
        f"\nComparing {len(all_keys)} (case, tool) pairs attempted in the "
        f"{len(common_cases)} common cases...\n"
    )

    if divergences:
        print(f"--- {len(divergences)} genuine policy divergences ---")
        print("(same case, same tool, same call position, different action)\n")
        for case, tool, i, action_a, action_b in divergences:
            print(f"{case} call#{i + 1} {tool}: A={action_a}  B={action_b}")
    else:
        print("--- 0 genuine policy divergences ---")
        print("Every call both agents attempted at the same trajectory "
              "position got the same decision from both policies.")

    divergent_cases = sorted({d[0] for d in divergences}, key=natural_key)
    trajectory_only_cases = sorted(
        {t[0] for t in trajectory_only} - set(divergent_cases), key=natural_key
    )

    print(f"\n{len(divergences)} divergent (case, tool, call#) triples "
          f"across {len(divergent_cases)} cases.")
    if divergent_cases:
        print(f"Cases with a genuine divergence: {divergent_cases}")

    print(
        f"\n{len(trajectory_only)} calls were attempted by only one policy "
        f"(trajectory difference, not a divergence), across "
        f"{len(trajectory_only_cases)} cases with no genuine divergence of "
        f"their own."
    )


if __name__ == "__main__":
    main()
