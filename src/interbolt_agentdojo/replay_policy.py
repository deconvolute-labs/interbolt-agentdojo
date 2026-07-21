"""Offline policy replay: re-evaluate a candidate policy against a recorded call corpus.

No live run, no API calls: purely `interbolt.policy.evaluate` invoked
against `call_records.jsonl` (written by `executor.py`'s `_record_call`,
not `interbolt_events.jsonl` -- interbolt's own emitted `Event`s never
carry `args`, so `call_records.jsonl` is the self-contained corpus this
depends on). See README's "Replay epistemics" section for what this can
and cannot tell you.

    uv run python -m interbolt_agentdojo.replay_policy \\
      --corpus runs/<name>/repeat_0/call_records.jsonl \\
      --policy policies/targeted/banking.yaml \\
      [--compare policies/strict.yaml] [--json]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from interbolt import Label, Policy, TrustLevel
from interbolt.constants import TRIFECTA_FROM_UNTRUSTED
from interbolt.policy.evaluate import build_context, evaluate_sink, resolve_labels


def _load_corpus(path: Path) -> list[dict]:
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _evaluate_record(record: dict, policy: Policy) -> tuple[str | None, str, str | None]:
    labels = tuple(Label(**d) for d in record["label_lineages"])
    resolved = resolve_labels(labels, policy.sources_table)
    trifecta = frozenset({TRIFECTA_FROM_UNTRUSTED}) if any(r.trust is TrustLevel.UNTRUSTED for r in resolved) else frozenset()
    context = build_context(
        tool=record["tool"],
        args=record["args"],
        resolved_labels=resolved,
        trifecta=trifecta,
        run_tainted=record["run_tainted"],
    )
    compiled_sink = policy.compiled_sinks.get(record["tool"])
    if compiled_sink is None:
        return None, policy.document.defaults.sink_action.value, None
    matched_rule, action, matched_condition = evaluate_sink(
        compiled_sink, context, default_action=policy.document.defaults.sink_action
    )
    return matched_rule, action.value, matched_condition


def _summarize(records: list[dict], policy: Policy) -> dict:
    counts: Counter = Counter()
    per_sink: dict[str, Counter] = {}
    per_record = []
    for record in records:
        matched_rule, action, _ = _evaluate_record(record, policy)
        counts[action] += 1
        per_sink.setdefault(record["tool"], Counter())[action] += 1
        per_record.append(
            {"seq": record["seq"], "tool": record["tool"], "action": action, "matched_rule": matched_rule}
        )
    return {
        "counts": dict(counts),
        "per_sink": {sink: dict(c) for sink, c in per_sink.items()},
        "per_record": per_record,
    }


def _print_summary(name: str, summary: dict) -> None:
    print(f"== {name} ==")
    print("Action counts:", summary["counts"])
    print("Per-sink breakdown:")
    for sink, counts in summary["per_sink"].items():
        print(f"  {sink}: {counts}")


def _print_delta(base_name: str, base: dict, compare_name: str, compare: dict) -> None:
    compare_by_seq = {r["seq"]: r for r in compare["per_record"]}
    print(f"== Delta: {base_name} -> {compare_name} ==")
    for base_record in base["per_record"]:
        compare_record = compare_by_seq.get(base_record["seq"])
        if compare_record is None or compare_record["action"] == base_record["action"]:
            continue
        print(
            f"  seq={base_record['seq']} tool={base_record['tool']} "
            f"{base_record['action']} ({base_record['matched_rule']}) -> "
            f"{compare_record['action']} ({compare_record['matched_rule']})"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--compare", default=None, type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    records = _load_corpus(args.corpus)
    policy = Policy.from_file(str(args.policy))
    summary = _summarize(records, policy)

    output = {args.policy.stem: summary}
    compare_summary = None
    if args.compare:
        compare_policy = Policy.from_file(str(args.compare))
        compare_summary = _summarize(records, compare_policy)
        output[args.compare.stem] = compare_summary

    if args.json:
        print(json.dumps(output, indent=2))
        return

    _print_summary(args.policy.stem, summary)
    if compare_summary is not None:
        print()
        _print_summary(args.compare.stem, compare_summary)
        print()
        _print_delta(args.policy.stem, summary, args.compare.stem, compare_summary)


if __name__ == "__main__":
    main()
