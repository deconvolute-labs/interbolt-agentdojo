#!/usr/bin/env python3
"""Compare utility/security verdicts between two runs.

Usage:
    python compare_utility_security.py <path_a> <path_b>

Each path should be the parent directory containing `user_task_*` and/or
`injection_task_*` subdirectories, e.g.:

    runs/published/travel-gpt-4o-mini/C_utility_targeted/repeat_0/\
gpt-4o-mini-2024-07-18-interbolt-targeted-enforce/travel

    runs/published/banking-gpt-4o-mini/D_asr_system_strict/repeat_0/\
gpt-4o-mini-2024-07-18-interbolt-strict-enforce/banking

Each task dir can hold its result json in one of these layouts:
  - <task_dir>/none.json
  - <task_dir>/none/none.json
  - <task_dir>/important_instructions/injection_task_M.json (user_task_* dirs
    only; one file per attack variant, each compared as its own record keyed
    "<user_task_X>/injection_task_M")
"""

import json
import sys
from pathlib import Path


def find_none_json(task_dir: Path) -> Path | None:
    direct = task_dir / "none.json"
    if direct.is_file():
        return direct
    nested = task_dir / "none" / "none.json"
    if nested.is_file():
        return nested
    return None


def natural_key(dir_name: str) -> int:
    return int(dir_name.rsplit("_", 1)[-1])


def load_task_records(base: Path) -> dict[str, Path]:
    records: dict[str, Path] = {}

    for d in sorted(base.glob("injection_task_*"), key=lambda p: natural_key(p.name)):
        if not d.is_dir():
            continue
        none_json = find_none_json(d)
        if none_json is None:
            print(f"WARNING: no none.json found for {d}")
            continue
        records[d.name] = none_json

    for d in sorted(base.glob("user_task_*"), key=lambda p: natural_key(p.name)):
        if not d.is_dir():
            continue
        important_dir = d / "important_instructions"
        if important_dir.is_dir():
            injection_files = sorted(
                important_dir.glob("injection_task_*.json"),
                key=lambda p: natural_key(p.stem),
            )
            if not injection_files:
                print(f"WARNING: no injection_task_*.json found in {important_dir}")
                continue
            for f in injection_files:
                records[f"{d.name}/{f.stem}"] = f
        else:
            none_json = find_none_json(d)
            if none_json is None:
                print(f"WARNING: no none.json found for {d}")
                continue
            records[d.name] = none_json

    if not records:
        raise ValueError(f"Error: Could not load any tasks from {base}!")
    return records


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <path_a> <path_b>")
        sys.exit(1)

    base_a = Path(sys.argv[1])
    base_b = Path(sys.argv[2])

    records_a = load_task_records(base_a)
    records_b = load_task_records(base_b)

    print(f"Path A: {base_a} ({len(records_a)} task records)")
    print(f"Path B: {base_b} ({len(records_b)} task records)")

    if len(records_a) != len(records_b):
        print(
            f"WARNING: task count mismatch: "
            f"{len(records_a)} in A vs {len(records_b)} in B"
        )

    only_in_a = sorted(set(records_a) - set(records_b))
    only_in_b = sorted(set(records_b) - set(records_a))
    if only_in_a:
        print(f"Only in A: {only_in_a}")
    if only_in_b:
        print(f"Only in B: {only_in_b}")

    common = sorted(set(records_a) & set(records_b))

    print(f"\nComparing {len(common)} common task records...\n")

    disagreements = []
    both_blocked = []
    both_not_blocked = []
    blocked_disagree = []

    for task_id in common:
        data_a = json.loads(records_a[task_id].read_text())
        data_b = json.loads(records_b[task_id].read_text())

        util_a, sec_a = data_a.get("utility"), data_a.get("security")
        util_b, sec_b = data_b.get("utility"), data_b.get("security")

        util_mismatch = util_a != util_b
        sec_mismatch = sec_a != sec_b

        if util_mismatch or sec_mismatch:
            disagreements.append(task_id)
            print(f"{task_id}: DISAGREE")
            if util_mismatch:
                print(f"  utility:  A={util_a}  B={util_b}")
            if sec_mismatch:
                print(f"  security: A={sec_a}  B={sec_b}")

        if sec_a == sec_b:
            (both_blocked if sec_a else both_not_blocked).append(task_id)
        else:
            blocked_disagree.append(task_id)

    print(f"\n{len(disagreements)} of {len(common)} task records disagree (utility and/or security).")
    if disagreements:
        print(f"Disagreeing tasks: {disagreements}")
    else:
        print("All utility/security values agree.")

    print("\n--- Blocked (security) agreement summary ---")
    print(f"Both blocked ({len(both_blocked)}): {both_blocked}")
    print(f"Both NOT blocked ({len(both_not_blocked)}): {both_not_blocked}")
    print(f"Disagree on blocked status ({len(blocked_disagree)}): {blocked_disagree}")


if __name__ == "__main__":
    main()
