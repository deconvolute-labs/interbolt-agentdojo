#!/usr/bin/env python3
"""Compare utility/security verdicts in none.json files between two runs.

Usage:
    python compare_utility_security.py <path_a> <path_b>

Each path should be the parent directory containing `user_task_*`
subdirectories, e.g.:

    runs/published/travel-gpt-4o-mini/C_utility_targeted/repeat_0/\
gpt-4o-mini-2024-07-18-interbolt-targeted-enforce/travel

For each user_task_* dir, the script looks for none.json either directly
inside it (user_task_X/none.json) or inside a `none` subdirectory
(user_task_X/none/none.json).
"""

import json
import sys
from pathlib import Path


def find_none_json(user_task_dir: Path) -> Path | None:
    direct = user_task_dir / "none.json"
    if direct.is_file():
        return direct
    nested = user_task_dir / "none" / "none.json"
    if nested.is_file():
        return nested
    return None


def load_user_tasks(base: Path) -> dict[str, Path]:
    tasks = {}
    for d in sorted(base.glob("user_task_*")):
        if not d.is_dir():
            continue
        none_json = find_none_json(d)
        if none_json is None:
            print(f"WARNING: no none.json found for {d}")
            continue
        tasks[d.name] = none_json
    if not tasks:
        raise ValueError("Error: Could not load any tasks!")
    return tasks


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <path_a> <path_b>")
        sys.exit(1)

    base_a = Path(sys.argv[1])
    base_b = Path(sys.argv[2])

    tasks_a = load_user_tasks(base_a)
    tasks_b = load_user_tasks(base_b)

    print(f"Path A: {base_a} ({len(tasks_a)} user_task dirs)")
    print(f"Path B: {base_b} ({len(tasks_b)} user_task dirs)")

    if len(tasks_a) != len(tasks_b):
        print(
            f"WARNING: user_task count mismatch: "
            f"{len(tasks_a)} in A vs {len(tasks_b)} in B"
        )

    only_in_a = sorted(set(tasks_a) - set(tasks_b))
    only_in_b = sorted(set(tasks_b) - set(tasks_a))
    if only_in_a:
        print(f"Only in A: {only_in_a}")
    if only_in_b:
        print(f"Only in B: {only_in_b}")

    common = sorted(set(tasks_a) & set(tasks_b), key=lambda s: int(s.split("_")[-1]))

    print(f"\nComparing {len(common)} common user_task dirs...\n")

    disagreements = []
    for task_id in common:
        data_a = json.loads(tasks_a[task_id].read_text())
        data_b = json.loads(tasks_b[task_id].read_text())

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

    print(f"\n{len(disagreements)} of {len(common)} user_task dirs disagree.")
    if disagreements:
        print(f"Disagreeing tasks: {disagreements}")
    else:
        print("All utility/security values agree.")


if __name__ == "__main__":
    main()
