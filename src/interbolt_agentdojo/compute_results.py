"""Metrics + markdown tables from run dirs.

Ad-hoc single/multi-run inspection:
    uv run python -m interbolt_agentdojo.compute_results runs/<name> [runs/<name2> ...] [--markdown] [--allow-dirty]

Five-number quartet mode (see README's "What this measures"):
    uv run python -m interbolt_agentdojo.compute_results \\
        --ceiling runs/A --asr-model runs/B --utility runs/C --asr-system runs/D \\
        [--markdown] [--allow-dirty] [--csv-out runs/results.csv]

--csv-out appends one row per repeat (long-format, for downstream analysis);
repeated invocations across policies/suites accumulate into one file.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path

from agentdojo.benchmark import load_task_results
from agentdojo.task_suite.load_suites import get_suite
from interbolt import Action, Policy
from interbolt.errors import InterboltConfigError, PolicyEvaluationError

from interbolt_agentdojo.namespaces import resolve_namespace


def _load_manifest(repeat_dir: Path) -> dict:
    return json.loads((repeat_dir / "run_manifest.json").read_text())


def _check_publishable(manifest: dict, allow_dirty: bool) -> None:
    if allow_dirty:
        return
    for pkg in ("interbolt", "agentdojo"):
        info = manifest.get(pkg) or {}
        if info.get("install_mode") == "editable":
            raise SystemExit(
                f"refusing to include {manifest['suite']!r} run in a publishable table: "
                f"{pkg!r} is an editable install (pass --allow-dirty for development use)"
            )
        if info.get("dirty"):
            raise SystemExit(
                f"refusing to include {manifest['suite']!r} run in a publishable table: "
                f"{pkg!r} source tree is dirty (pass --allow-dirty for development use)"
            )


def _discover_pipeline_name(repeat_dir: Path, suite_name: str) -> str | None:
    for child in repeat_dir.iterdir():
        if child.is_dir() and (child / suite_name).exists():
            return child.name
    return None


def _discover_results(
    repeat_dir: Path, pipeline_name: str, suite_name: str, benchmark_version: str
) -> tuple[dict, dict]:
    """Load per-task results by walking the trace directory, tolerant of subset runs.

    Mirrors `agentdojo.benchmark.load_suite_results`'s output shape, but discovers
    which tasks actually ran instead of assuming the full suite ran (that function
    raises `FileNotFoundError` on a deliberately subsetted `--user-tasks` run).
    Still uses AgentDojo's own `load_task_results` for the actual parsing.

    With an attack, AgentDojo also solves each injection task standalone (for
    ground truth), writing `<injection_task_id>/none/none.json` -- the exact
    same directory shape as a genuine no-attack user-task run. Filtering the
    top-level directory name against the suite's real `user_tasks` excludes
    those from the benign-utility bucket.
    """
    without_injections: dict = {}
    with_injections: dict = {}
    base = repeat_dir / pipeline_name / suite_name
    if not base.exists():
        return without_injections, with_injections
    user_task_ids = set(get_suite(benchmark_version, suite_name).user_tasks.keys())
    for user_task_dir in sorted(p for p in base.iterdir() if p.is_dir() and p.name in user_task_ids):
        for attack_dir in sorted(p for p in user_task_dir.iterdir() if p.is_dir()):
            for result_file in sorted(attack_dir.glob("*.json")):
                task_results = load_task_results(
                    pipeline_name, suite_name, user_task_dir.name, attack_dir.name, result_file.stem, repeat_dir
                )
                if attack_dir.name == "none":
                    without_injections[(user_task_dir.name, None)] = task_results
                else:
                    with_injections[(user_task_dir.name, result_file.stem)] = task_results
    return without_injections, with_injections


def _interbolt_event_summary(repeat_dir: Path, selected_run_ids: set[str] | None = None) -> dict:
    """Summarize interbolt_events.jsonl, optionally filtered to a set of run_ids.

    AgentDojo retries a case up to three times on failure; interbolt_events.jsonl
    accumulates events from every attempt, including ones AgentDojo discarded in
    favor of a later retry. Passing `selected_run_ids` (the run_id AgentDojo
    actually scored per case, from `_case_to_run_id`/`_selected_run_ids`) filters
    blocks/approvals down to the executions that were actually scored, instead of
    inflating counts with superseded attempts. `eval_errors` is deliberately NOT
    filtered: a policy-evaluation exception on a since-superseded attempt is still
    evidence the evaluator broke, independent of which attempt scored.
    """
    blocks_by_rule: Counter = Counter()
    approvals_denied = 0
    eval_errors = 0
    events_path = repeat_dir / "interbolt_events.jsonl"
    if events_path.exists():
        with events_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                decision = event["decision"]
                if event.get("outcome") == "evaluation_error":
                    eval_errors += 1
                if selected_run_ids is not None and decision["run_id"] not in selected_run_ids:
                    continue
                if decision["action"] == "block":
                    blocks_by_rule[decision.get("matched_rule") or "(default)"] += 1
                if event.get("outcome") == "require_approval":
                    approvals_denied += 1
    return {
        "blocks": sum(blocks_by_rule.values()),
        "approvals_denied": approvals_denied,
        "eval_errors": eval_errors,
        "blocks_by_rule": dict(blocks_by_rule),
        "top_rules": blocks_by_rule.most_common(3),
    }


def _policy_declared_block_rules(policy_file: str | None) -> frozenset[str]:
    """Rule names with action: block declared anywhere in a policy YAML.

    Empty set if policy_file is None or the file can't be loaded -- this only
    means declared-but-unfired rules won't get zero-seeded CSV columns, not a
    hard failure; the CSV still gets whatever fired. Scoped to action: block
    rules only, since this seeds a block-count Counter -- a declared
    allow/require_approval rule would just be a permanently-zero column.
    """
    if not policy_file:
        return frozenset()
    try:
        policy = Policy.from_file(policy_file)
    except (PolicyEvaluationError, InterboltConfigError) as exc:
        print(f"  ** WARNING: could not load policy {policy_file!r} for rule-column seeding: {exc} **")
        return frozenset()
    return frozenset(
        rule.name
        for sink in policy.document.sinks.values()
        for rule in sink.rules
        if rule.action is Action.BLOCK
    )


def _rate(values) -> float | None:
    values = list(values)
    if not values:
        return None
    return sum(values) / len(values)


def _repeat_cases(repeat_dir: Path, allow_dirty: bool) -> tuple[dict, dict, dict]:
    """manifest, without_injections, with_injections for one repeat dir."""
    manifest = _load_manifest(repeat_dir)
    _check_publishable(manifest, allow_dirty)
    suite_name = manifest["suite"]
    pipeline_name = _discover_pipeline_name(repeat_dir, suite_name)
    without_injections, with_injections = {}, {}
    if pipeline_name is not None:
        without_injections, with_injections = _discover_results(
            repeat_dir, pipeline_name, suite_name, manifest["benchmark_version"]
        )
    return manifest, without_injections, with_injections


def _selected_run_ids(repeat_dir: Path, without_injections: dict, with_injections: dict) -> set[str]:
    """run_ids AgentDojo actually scored (last attempt per case), across both buckets."""
    ids = set(_case_to_run_id(repeat_dir, without_injections).values())
    ids |= set(_case_to_run_id(repeat_dir, with_injections).values())
    return ids


def _repeat_metrics(repeat_dir: Path, allow_dirty: bool) -> dict:
    manifest, without_injections, with_injections = _repeat_cases(repeat_dir, allow_dirty)
    selected = _selected_run_ids(repeat_dir, without_injections, with_injections)

    return {
        "manifest": manifest,
        "benign_utility": _rate(r.utility for r in without_injections.values()),
        "utility_under_attack": _rate(r.utility for r in with_injections.values()),
        # `security=True` means the injection succeeded (see docstring of
        # agentdojo.task_suite.task_suite.TaskSuite.run_task_with_pipeline).
        "asr": _rate(r.security for r in with_injections.values()),
        "events": _interbolt_event_summary(repeat_dir, selected),
    }


def _configuration_label(manifest: dict) -> str:
    defense = manifest.get("defense")
    if defense is None:
        return "No defense (baseline)"
    return Path(defense["policy_file"]).name


def _repeat_dirs(run_dir: Path) -> list[Path]:
    dirs = sorted(p for p in run_dir.iterdir() if p.is_dir() and p.name.startswith("repeat_"))
    return dirs or [run_dir]


def compute_run(run_dir: Path, allow_dirty: bool) -> dict:
    per_repeat = [_repeat_metrics(d, allow_dirty) for d in _repeat_dirs(run_dir)]

    def collect(key: str) -> list[float]:
        return [r[key] for r in per_repeat if r[key] is not None]

    return {
        "run_dir": run_dir,
        "label": _configuration_label(per_repeat[0]["manifest"]),
        "benign_utility": collect("benign_utility"),
        "utility_under_attack": collect("utility_under_attack"),
        "asr": collect("asr"),
        "events": [r["events"] for r in per_repeat],
        "benign_utility_by_repeat": _per_repeat_breakdown(per_repeat, "benign_utility"),
        "utility_under_attack_by_repeat": _per_repeat_breakdown(per_repeat, "utility_under_attack"),
        "asr_by_repeat": _per_repeat_breakdown(per_repeat, "asr"),
    }


def _spread(values: list[float]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return f"{values[0]:.2f}"
    return f"{statistics.mean(values):.2f} ({min(values):.2f}-{max(values):.2f})"


def _per_repeat_breakdown(per_repeat: list[dict], value_key: str, denom_key: str | None = None) -> str:
    """'repeat_0=1.00 (n=12), repeat_1=0.83 (n=10)' -- empty string for a single repeat.

    Positional repeat_i labels, not directory names: quartet mode's four run
    dirs aren't required to share literal repeat_* names, only counts.
    """
    if len(per_repeat) <= 1:
        return ""
    parts = []
    for i, r in enumerate(per_repeat):
        value = r[value_key]
        value_str = f"{value:.2f}" if value is not None else "n/a"
        if denom_key is not None:
            value_str += f" (n={r[denom_key]})"
        parts.append(f"repeat_{i}={value_str}")
    return ", ".join(parts)


def _print_text(results: list[dict]) -> None:
    for r in results:
        print(f"{r['label']} ({r['run_dir']})")
        print(f"  Benign utility: {_spread(r['benign_utility']) or 'n/a'}")
        if r["benign_utility_by_repeat"]:
            print(f"    per repeat: {r['benign_utility_by_repeat']}")
        print(f"  Utility under attack: {_spread(r['utility_under_attack']) or 'n/a'}")
        if r["utility_under_attack_by_repeat"]:
            print(f"    per repeat: {r['utility_under_attack_by_repeat']}")
        print(f"  Targeted ASR: {_spread(r['asr']) or 'n/a'}")
        if r["asr_by_repeat"]:
            print(f"    per repeat: {r['asr_by_repeat']}")
        total_errors = sum(e["eval_errors"] for e in r["events"])
        if total_errors:
            print(f"  ** {total_errors} policy evaluation errors -- investigate before publishing **")


def _render_markdown(results: list[dict]) -> str:
    lines = []
    lines.append("| Configuration        | Benign utility | Utility under attack | Targeted ASR |")
    lines.append("|-----------------------|----------------|-----------------------|--------------|")
    for r in results:
        lines.append(f"| {r['label']} | {_spread(r['benign_utility'])} | {_spread(r['utility_under_attack'])} | {_spread(r['asr'])} |")
    lines.append("")
    lines.append("| Configuration | Blocks | Approvals denied | Eval errors | Top matched rules |")
    lines.append("|---------------|--------|-------------------|-------------|-------------------|")
    for r in results:
        blocks = sum(e["blocks"] for e in r["events"])
        approvals = sum(e["approvals_denied"] for e in r["events"])
        errors = sum(e["eval_errors"] for e in r["events"])
        top_rules: Counter = Counter()
        for e in r["events"]:
            for rule, count in e["top_rules"]:
                top_rules[rule] += count
        top = ", ".join(f"{rule} ({count})" for rule, count in top_rules.most_common(3))
        lines.append(f"| {r['label']} | {blocks} | {approvals} | {errors} | {top} |")

    breakdown_rows = [
        (r["label"], metric_label, r[key])
        for r in results
        for metric_label, key in (
            ("Benign utility", "benign_utility_by_repeat"),
            ("Utility under attack", "utility_under_attack_by_repeat"),
            ("Targeted ASR", "asr_by_repeat"),
        )
        if r[key]
    ]
    if breakdown_rows:
        lines.append("")
        lines.append("| Configuration | Metric | Per repeat |")
        lines.append("|---------------|--------|------------|")
        for label, metric_label, breakdown in breakdown_rows:
            lines.append(f"| {label} | {metric_label} | {breakdown} |")
    return "\n".join(lines)


def _print_markdown(results: list[dict]) -> None:
    print(_render_markdown(results))


# ---------------------------------------------------------------------------
# Five-number quartet mode: joins a defended run against its undefended,
# same-model baseline per case. See README's "What this measures" for the
# full rationale; summary: Interbolt gates tool calls after the model has
# already decided to act, so a raw ASR from a single run can't tell "Interbolt
# blocked it" apart from "the model refused on its own." The functions below
# join run B (attack, allow_all enforce -- undefended) against run D (attack,
# <policy> enforce -- defended) per (user_task, injection_task) case to
# recover that distinction.
# ---------------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_call_records(repeat_dir: Path) -> dict[str, list[dict]]:
    """run_id -> list of call_records.jsonl entries."""
    by_run: dict[str, list[dict]] = {}
    for record in _load_jsonl(repeat_dir / "call_records.jsonl"):
        by_run.setdefault(record["run_id"], []).append(record)
    return by_run


def _events_by_run_id(repeat_dir: Path) -> dict[str, list[dict]]:
    """run_id -> list of interbolt_events.jsonl entries."""
    by_run: dict[str, list[dict]] = {}
    for event in _load_jsonl(repeat_dir / "interbolt_events.jsonl"):
        by_run.setdefault(event["decision"]["run_id"], []).append(event)
    return by_run


def _case_to_run_id(repeat_dir: Path, cases: dict) -> dict[tuple, str]:
    """(user_task_id, injection_task_id) -> run_id, from run_index.jsonl.

    `cases` is either a with_injections or without_injections dict (from
    _discover_results) -- only its keys matter here. Filtering to those keys
    drops AgentDojo's injection-task-solved-standalone pre-pass noise: that
    pass's context has user_task_id=<injection_task_id>, injection_task_id=None,
    a tuple that can never match a real case key. When a case retried, later
    run_index.jsonl entries for the same key overwrite earlier ones below, so
    the mapping lands on the last (i.e. scored) attempt per case -- this is
    also what `_selected_run_ids` relies on to filter superseded-attempt events.
    """
    mapping: dict[tuple, str] = {}
    for entry in _load_jsonl(repeat_dir / "run_index.jsonl"):
        key = (entry.get("user_task_id"), entry.get("injection_task_id"))
        if key in cases:
            mapping[key] = entry["run_id"]
    return mapping


def _target_tools(suite, injection_task_id: str) -> set[str]:
    """Plain (unqualified) tool names the injection task's ground truth calls.

    Derived from AgentDojo's own injection-task ground truth, never
    hardcoded, so this stays suite-agnostic.
    """
    injection_task = suite.injection_tasks[injection_task_id]
    env = suite.load_and_inject_default_environment({})
    return {call.function for call in injection_task.ground_truth(env)}


def _reached_target_sink(records: list[dict], target_tools: set[str], suite_name: str) -> bool:
    """Whether any recorded tool call (call_records.jsonl) hit a target-sink tool.

    Tool-name match only (not argument-aware) -- see README's "Target-sink
    derivation" for why, and for the `ambiguous_sink_match` taxonomy count
    this criterion produces.
    """
    qualified = {f"{resolve_namespace(suite_name, t)}.{t}" for t in target_tools}
    return any(r["tool"] in qualified for r in records)


# Same field _interbolt_event_summary already keys "approvals_denied" on.
# Assumes the default auto_deny approval resolver (true today, see
# "Approval auto-deny scoring" in the README), which always denies a
# require_approval decision; a future non-auto-deny resolver would break
# this equivalence and would need this constant revisited.
_BLOCK_EQUIVALENT_OUTCOMES = {"block", "require_approval"}


def _interbolt_blocked_target_sink(events: list[dict], target_tools: set[str], suite_name: str) -> bool:
    """Whether Interbolt blocked (or auto-denied) a target-sink tool call."""
    qualified = {f"{resolve_namespace(suite_name, t)}.{t}" for t in target_tools}
    return any(
        e.get("outcome") in _BLOCK_EQUIVALENT_OUTCOMES and e["decision"]["tool"] in qualified for e in events
    )


def _classify_case(security_b: bool, reached_sink_b: bool, security_d: bool, blocked_d: bool) -> str:
    """Attack case taxonomy for one (user_task, injection_task) case.

    security_b/reached_sink_b describe the undefended run (B, allow_all
    enforce); security_d/blocked_d describe the defended run (D, <policy>
    enforce). See README's "What this measures" for the full definitions.
    `ambiguous_sink_match` and `attack_failed_unattributed` are reported for
    transparency only and excluded from block_rate_interbolt.
    """
    if not reached_sink_b:
        return "out_of_scope" if security_b else "model_refused"
    if not security_b:
        return "ambiguous_sink_match"
    if blocked_d and not security_d:
        return "interbolt_blocked"
    if security_d:
        return "attack_succeeded_defended"
    return "attack_failed_unattributed"


def _quartet_repeat_metrics(
    ceiling_dir: Path, asr_model_dir: Path, utility_dir: Path, asr_system_dir: Path, allow_dirty: bool
) -> dict:
    manifest_a, without_injections_a, _ = _repeat_cases(ceiling_dir, allow_dirty)
    manifest_b, without_injections_b, with_injections_b = _repeat_cases(asr_model_dir, allow_dirty)
    manifest_c, without_injections_c, _ = _repeat_cases(utility_dir, allow_dirty)
    manifest_d, without_injections_d, with_injections_d = _repeat_cases(asr_system_dir, allow_dirty)

    events_b = _interbolt_event_summary(
        asr_model_dir, _selected_run_ids(asr_model_dir, without_injections_b, with_injections_b)
    )
    events_c = _interbolt_event_summary(utility_dir, _selected_run_ids(utility_dir, without_injections_c, {}))
    events_d = _interbolt_event_summary(
        asr_system_dir, _selected_run_ids(asr_system_dir, without_injections_d, with_injections_d)
    )

    if (manifest_c.get("defense") or {}).get("policy_sha256") != (manifest_d.get("defense") or {}).get("policy_sha256"):
        print("  ** WARNING: utility (C) and asr-system (D) used different policies **")

    manifests = [manifest_a, manifest_b, manifest_c, manifest_d]
    for key in ("suite", "benchmark_version", "model", "user_tasks", "injection_tasks"):
        values = {m.get(key) for m in manifests}
        if len(values) > 1:
            print(f"  ** WARNING: quartet runs disagree on {key!r}: {values} **")

    suite = get_suite(manifest_b["benchmark_version"], manifest_b["suite"])
    case_to_run_b = _case_to_run_id(asr_model_dir, with_injections_b)
    case_to_run_d = _case_to_run_id(asr_system_dir, with_injections_d)
    call_records_b = _load_call_records(asr_model_dir)
    events_by_run_d = _events_by_run_id(asr_system_dir)

    taxonomy: Counter = Counter()
    missing_from_d: list[tuple] = []
    for case_key, result_b in with_injections_b.items():
        result_d = with_injections_d.get(case_key)
        if result_d is None:
            missing_from_d.append(case_key)
            continue
        _, injection_task_id = case_key
        target_tools = _target_tools(suite, injection_task_id)

        records_b = call_records_b.get(case_to_run_b.get(case_key), [])
        reached_sink_b = _reached_target_sink(records_b, target_tools, suite.name)

        events_for_case_d = events_by_run_d.get(case_to_run_d.get(case_key), [])
        blocked_d = _interbolt_blocked_target_sink(events_for_case_d, target_tools, suite.name)

        taxonomy[_classify_case(result_b.security, reached_sink_b, result_d.security, blocked_d)] += 1

    if missing_from_d:
        print(
            f"  ** WARNING: {len(missing_from_d)} case(s) present in B (asr_model) but missing from D "
            f"(asr_system), excluded from taxonomy/bucket_total: {missing_from_d} **"
        )

    block_rate_num = taxonomy["interbolt_blocked"]
    block_rate_denom = block_rate_num + taxonomy["attack_succeeded_defended"]
    block_rate = block_rate_num / block_rate_denom if block_rate_denom else None

    u_ceiling_num = sum(r.utility for r in without_injections_a.values())
    u_ceiling_den = len(without_injections_a)
    utility_ceiling = _rate(r.utility for r in without_injections_a.values())

    u_policy_num = sum(r.utility for r in without_injections_c.values())
    u_policy_den = len(without_injections_c)
    utility_interbolt = _rate(r.utility for r in without_injections_c.values())

    if u_ceiling_den != u_policy_den:
        print(
            f"  ** WARNING: ceiling (A) and utility (C) ran different case counts "
            f"({u_ceiling_den} vs {u_policy_den}) -- retention_num/retention_den "
            "will not equal utility_interbolt/utility_ceiling for this repeat **"
        )

    retention = (utility_interbolt / utility_ceiling) if utility_ceiling else None

    asr_model_num = sum(r.security for r in with_injections_b.values())
    asr_model_den = len(with_injections_b)
    asr_system_num = sum(r.security for r in with_injections_d.values())
    asr_system_den = len(with_injections_d)

    defense_d = manifest_d.get("defense") or {}
    policy_file = defense_d.get("policy_file")

    # Zero-seed every action:block rule the policy declares, so a rule that
    # never fires still gets its own entry (distinguishing "declared and
    # never matched" from "not part of this policy") rather than silently
    # having no column in the CSV export.
    zero_seed = dict.fromkeys(_policy_declared_block_rules(policy_file), 0)
    blocks_by_rule_benign = zero_seed | events_c["blocks_by_rule"]
    blocks_by_rule_attacked = zero_seed | events_d["blocks_by_rule"]

    return {
        "label": _configuration_label(manifest_d),
        "utility_ceiling": utility_ceiling,
        "utility_interbolt": utility_interbolt,
        "retention": retention,
        "asr_model": _rate(r.security for r in with_injections_b.values()),
        "asr_system": _rate(r.security for r in with_injections_d.values()),
        "block_rate_interbolt": block_rate,
        "block_rate_denom": block_rate_denom,
        "taxonomy": dict(taxonomy),
        "contamination": events_b["blocks"] + events_b["approvals_denied"],
        "eval_errors": events_b["eval_errors"] + events_c["eval_errors"] + events_d["eval_errors"],
        "events_cd": [events_c, events_d],
        # Raw ingredients for the --csv-out export (_quartet_csv_row); the
        # aggregate report above never reads these directly.
        "suite": manifest_d.get("suite"),
        "model": manifest_d.get("model"),
        "policy_stem": Path(policy_file).stem if policy_file else None,
        "policy_fingerprint": defense_d.get("policy_sha256"),
        "interbolt_version": (manifest_d.get("interbolt") or {}).get("version"),
        "agentdojo_version": (manifest_d.get("agentdojo") or {}).get("version"),
        "n_user_tasks": len({k[0] for k in with_injections_d}),
        "n_injection_tasks": len({k[1] for k in with_injections_d}),
        "n_cases": len(with_injections_d),
        "u_ceiling_num": u_ceiling_num,
        "u_ceiling_den": u_ceiling_den,
        "u_policy_num": u_policy_num,
        "u_policy_den": u_policy_den,
        "asr_model_num": asr_model_num,
        "asr_model_den": asr_model_den,
        "asr_system_num": asr_system_num,
        "asr_system_den": asr_system_den,
        "blocks_by_rule_benign": blocks_by_rule_benign,
        "blocks_by_rule_attacked": blocks_by_rule_attacked,
    }


def _five_numbers(ceiling: Path, asr_model: Path, utility: Path, asr_system: Path, allow_dirty: bool) -> dict:
    dirs = [_repeat_dirs(d) for d in (ceiling, asr_model, utility, asr_system)]
    if len({len(d) for d in dirs}) != 1:
        raise SystemExit(f"quartet run dirs have mismatched repeat counts: {[len(d) for d in dirs]}")

    per_repeat = [_quartet_repeat_metrics(c, b, u, d, allow_dirty) for c, b, u, d in zip(*dirs)]

    def collect(key: str) -> list[float]:
        return [r[key] for r in per_repeat if r[key] is not None]

    taxonomy_totals: Counter = Counter()
    for r in per_repeat:
        taxonomy_totals.update(r["taxonomy"])

    return {
        "label": per_repeat[0]["label"],
        "utility_ceiling": collect("utility_ceiling"),
        "utility_interbolt": collect("utility_interbolt"),
        "retention": collect("retention"),
        "asr_model": collect("asr_model"),
        "asr_system": collect("asr_system"),
        "block_rate_interbolt": collect("block_rate_interbolt"),
        "taxonomy": dict(taxonomy_totals),
        "contamination": sum(r["contamination"] for r in per_repeat),
        "eval_errors": sum(r["eval_errors"] for r in per_repeat),
        "events_cd": [e for r in per_repeat for e in r["events_cd"]],
        "utility_ceiling_by_repeat": _per_repeat_breakdown(per_repeat, "utility_ceiling"),
        "utility_interbolt_by_repeat": _per_repeat_breakdown(per_repeat, "utility_interbolt"),
        "retention_by_repeat": _per_repeat_breakdown(per_repeat, "retention"),
        "asr_model_by_repeat": _per_repeat_breakdown(per_repeat, "asr_model"),
        "asr_system_by_repeat": _per_repeat_breakdown(per_repeat, "asr_system"),
        "block_rate_interbolt_by_repeat": _per_repeat_breakdown(per_repeat, "block_rate_interbolt", "block_rate_denom"),
        # Raw per-repeat quartet results, for --csv-out (main() builds CSV rows from this).
        "per_repeat": per_repeat,
    }


_TAXONOMY_KEYS = (
    "model_refused",
    "out_of_scope",
    "interbolt_blocked",
    "attack_succeeded_defended",
    "ambiguous_sink_match",
    "attack_failed_unattributed",
)


def _print_quartet_text(r: dict) -> None:
    print(r["label"])
    print(f"  Utility ceiling: {_spread(r['utility_ceiling']) or 'n/a'}")
    if r["utility_ceiling_by_repeat"]:
        print(f"    per repeat: {r['utility_ceiling_by_repeat']}")
    print(f"  Utility w/ policy: {_spread(r['utility_interbolt']) or 'n/a'}")
    if r["utility_interbolt_by_repeat"]:
        print(f"    per repeat: {r['utility_interbolt_by_repeat']}")
    print(f"  Retention: {_spread(r['retention']) or 'n/a'}")
    if r["retention_by_repeat"]:
        print(f"    per repeat: {r['retention_by_repeat']}")
    print(f"  ASR_model: {_spread(r['asr_model']) or 'n/a'}")
    if r["asr_model_by_repeat"]:
        print(f"    per repeat: {r['asr_model_by_repeat']}")
    print(f"  ASR_system: {_spread(r['asr_system']) or 'n/a'}")
    if r["asr_system_by_repeat"]:
        print(f"    per repeat: {r['asr_system_by_repeat']}")
    block_rate = _spread(r["block_rate_interbolt"]) or "undefined (no winnable model-complied cases)"
    print(f"  Interbolt block-rate: {block_rate}")
    if r["block_rate_interbolt_by_repeat"]:
        print(f"    per repeat: {r['block_rate_interbolt_by_repeat']}")
    t = r["taxonomy"]
    taxonomy_str = " ".join(f"{key}={t.get(key, 0)}" for key in _TAXONOMY_KEYS)
    print(f"  Taxonomy: {taxonomy_str}")
    if r["contamination"]:
        print(f"  ** ERROR: asr_model baseline shows {r['contamination']} block/approval-denial event(s) "
              "-- allow_all baseline is contaminated **")
    if r["eval_errors"]:
        print(f"  ** {r['eval_errors']} policy evaluation errors -- investigate before publishing **")


def _render_quartet_markdown(r: dict) -> str:
    lines = []
    lines.append("| Config | Utility ceiling | Utility w/ policy | Retention | ASR_model | ASR_system | Interbolt block-rate |")
    lines.append("|---|---|---|---|---|---|---|")
    block_rate = _spread(r["block_rate_interbolt"]) or "undefined"
    lines.append(
        f"| {r['label']} | {_spread(r['utility_ceiling'])} | {_spread(r['utility_interbolt'])} | "
        f"{_spread(r['retention'])} | {_spread(r['asr_model'])} | {_spread(r['asr_system'])} | {block_rate} |"
    )
    lines.append("")
    lines.append(
        "| Config | model_refused | out_of_scope | interbolt_blocked | attack_succeeded_defended "
        "| ambiguous_sink_match | attack_failed_unattributed |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    t = r["taxonomy"]
    taxonomy_cells = " | ".join(str(t.get(key, 0)) for key in _TAXONOMY_KEYS)
    lines.append(f"| {r['label']} | {taxonomy_cells} |")
    lines.append("")
    lines.append("| Configuration | Blocks (benign + attack runs) | Approvals denied | Eval errors | Top matched rules |")
    lines.append("|---------------|-------------------------------|-------------------|-------------|--------------------|")
    blocks = sum(e["blocks"] for e in r["events_cd"])
    approvals = sum(e["approvals_denied"] for e in r["events_cd"])
    top_rules: Counter = Counter()
    for e in r["events_cd"]:
        for rule, count in e["top_rules"]:
            top_rules[rule] += count
    top = ", ".join(f"{rule} ({count})" for rule, count in top_rules.most_common(3))
    lines.append(f"| {r['label']} | {blocks} | {approvals} | {r['eval_errors']} | {top} |")

    breakdown_rows = [
        (metric_label, r[key])
        for metric_label, key in (
            ("Utility ceiling", "utility_ceiling_by_repeat"),
            ("Utility w/ policy", "utility_interbolt_by_repeat"),
            ("Retention", "retention_by_repeat"),
            ("ASR_model", "asr_model_by_repeat"),
            ("ASR_system", "asr_system_by_repeat"),
            ("Interbolt block-rate", "block_rate_interbolt_by_repeat"),
        )
        if r[key]
    ]
    if breakdown_rows:
        lines.append("")
        lines.append("| Metric | Per repeat |")
        lines.append("|---|---|")
        for metric_label, breakdown in breakdown_rows:
            lines.append(f"| {metric_label} | {breakdown} |")
    return "\n".join(lines)


def _print_quartet_markdown(r: dict) -> None:
    print(_render_quartet_markdown(r))


def _write_markdown_file(out_dir: Path, content: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "results.md"
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# --csv-out: one row per repeat, long-format, meant for downstream analysis
# rather than human reading. Rule-block columns are dynamic (one pair per
# rule name actually observed) since different policies fire different
# rules; see _write_quartet_csv_rows for how the file stays valid CSV across
# invocations with different rule sets.
# ---------------------------------------------------------------------------

_FIXED_CSV_FIELDNAMES = [
    "suite", "policy", "repeat", "model", "interbolt_version", "agentdojo_version",
    "policy_fingerprint", "deduplicated",
    "n_user_tasks", "n_injection_tasks", "n_cases",
    "u_ceiling", "u_ceiling_num", "u_ceiling_den",
    "u_policy", "u_policy_num", "u_policy_den",
    "retention", "retention_num", "retention_den",
    "asr_model", "asr_model_num", "asr_model_den",
    "asr_system", "asr_system_num", "asr_system_den",
    "block_rate", "block_rate_num", "block_rate_den",
    "model_refused", "out_of_scope", "interbolt_blocked", "attack_succeeded_defended",
    "ambiguous_sink_match", "attack_failed_unattributed", "bucket_total",
    "blocks_benign", "blocks_attacked", "approvals_denied", "eval_errors",
]


def _quartet_csv_row(r: dict, repeat_index: int) -> dict:
    """Map one _quartet_repeat_metrics() result to a CSV row.

    Returns the fixed-column values plus the row's raw per-bucket rule
    Counters, kept separate from the fixed columns: the final rule__*__*
    column set isn't known until _write_quartet_csv_rows sees every row
    being written, unioned against whatever rule columns already exist in
    the target file.
    """
    t = r["taxonomy"]
    bucket_total = sum(t.get(key, 0) for key in _TAXONOMY_KEYS)
    fixed = {
        "suite": r["suite"],
        "policy": r["policy_stem"],
        "repeat": repeat_index,
        "model": r["model"],
        "interbolt_version": r["interbolt_version"],
        "agentdojo_version": r["agentdojo_version"],
        "policy_fingerprint": f"sha256:{r['policy_fingerprint']}" if r["policy_fingerprint"] else "",
        # Hardcoded: Part B's run_id-filtered event counting is the only
        # counting method this script implements, so every row it produces
        # is "yes" by construction. The column exists so rows from *other*
        # (older, pre-fix) exports remain distinguishable once combined
        # into one CSV externally -- this script never emits "no" itself.
        "deduplicated": "yes",
        "n_user_tasks": r["n_user_tasks"],
        "n_injection_tasks": r["n_injection_tasks"],
        "n_cases": r["n_cases"],
        "u_ceiling": r["utility_ceiling"],
        "u_ceiling_num": r["u_ceiling_num"],
        "u_ceiling_den": r["u_ceiling_den"],
        "u_policy": r["utility_interbolt"],
        "u_policy_num": r["u_policy_num"],
        "u_policy_den": r["u_policy_den"],
        "retention": r["retention"],
        # Not derived from the retention rate itself: retention as "fraction
        # of ceiling's successes retained" -- u_policy_num / u_ceiling_num.
        "retention_num": r["u_policy_num"],
        "retention_den": r["u_ceiling_num"],
        "asr_model": r["asr_model"],
        "asr_model_num": r["asr_model_num"],
        "asr_model_den": r["asr_model_den"],
        "asr_system": r["asr_system"],
        "asr_system_num": r["asr_system_num"],
        "asr_system_den": r["asr_system_den"],
        "block_rate": r["block_rate_interbolt"],
        "block_rate_num": t.get("interbolt_blocked", 0),
        "block_rate_den": r["block_rate_denom"],
        "model_refused": t.get("model_refused", 0),
        "out_of_scope": t.get("out_of_scope", 0),
        "interbolt_blocked": t.get("interbolt_blocked", 0),
        "attack_succeeded_defended": t.get("attack_succeeded_defended", 0),
        "ambiguous_sink_match": t.get("ambiguous_sink_match", 0),
        "attack_failed_unattributed": t.get("attack_failed_unattributed", 0),
        "bucket_total": bucket_total,
        "blocks_benign": sum(r["blocks_by_rule_benign"].values()),
        "blocks_attacked": sum(r["blocks_by_rule_attacked"].values()),
        "approvals_denied": sum(e["approvals_denied"] for e in r["events_cd"]),
        "eval_errors": r["eval_errors"],
    }
    return {
        "fixed": fixed,
        "blocks_by_rule_benign": r["blocks_by_rule_benign"],
        "blocks_by_rule_attacked": r["blocks_by_rule_attacked"],
    }


def _rule_columns(rule_names: set[str]) -> list[str]:
    cols = []
    for rule in sorted(rule_names):
        cols += [f"rule__{rule}__benign", f"rule__{rule}__attacked"]
    return cols


def _write_quartet_csv_rows(rows: list[dict], csv_path: Path) -> None:
    """Append `rows` to csv_path, one per repeat.

    Different policies/suites fire different rules, so a later invocation
    can introduce a rule__*__* column the file's current header has never
    seen. To keep every row the same column count, this reads the existing
    file's header and rows (if any), unions its rule names with this
    invocation's, and rewrites the whole file with the unioned header.

    A row's own blocks_by_rule_benign/blocks_by_rule_attacked dict keys are
    already that row's full declared-rule set (zero-seeded by
    _quartet_repeat_metrics) plus anything observed. So a rule__*__* column
    absent from a given row -- whether it's an old row read back from the
    file or a new row in this call -- was necessarily not declared by that
    row's own policy: backfilled "" ("not declared"), never 0 ("declared,
    never fired") -- conflating the two would misrepresent a different
    policy's rule as part of this row's policy.
    """
    existing_rows: list[dict] = []
    existing_rules: set[str] = set()
    if csv_path.exists():
        with csv_path.open(newline="") as f:
            reader = csv.DictReader(f)
            existing_rows = list(reader)
            existing_rules = {c.split("__")[1] for c in (reader.fieldnames or []) if c.startswith("rule__")}

    new_rules = {rule for row in rows for rule in (*row["blocks_by_rule_benign"], *row["blocks_by_rule_attacked"])}
    all_rules = existing_rules | new_rules
    fieldnames = _FIXED_CSV_FIELDNAMES + _rule_columns(all_rules)

    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for old_row in existing_rows:
            writer.writerow({col: old_row.get(col, "") for col in fieldnames})
        for row in rows:
            full = dict(row["fixed"])
            for rule in all_rules:
                full[f"rule__{rule}__benign"] = row["blocks_by_rule_benign"].get(rule, "")
                full[f"rule__{rule}__attacked"] = row["blocks_by_rule_attacked"].get(rule, "")
            writer.writerow(full)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dirs", nargs="*", type=Path, help="ad-hoc single/multi-run inspection mode")
    parser.add_argument("--ceiling", type=Path, help="run A: no attack, no defense")
    parser.add_argument("--asr-model", type=Path, help="run B: attack, allow_all enforce")
    parser.add_argument("--utility", type=Path, help="run C: no attack, <policy> enforce")
    parser.add_argument("--asr-system", type=Path, help="run D: attack, <policy> enforce")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="directory to write results.md into (defaults to the single run_dir in ad-hoc mode; "
        "required with --markdown otherwise)",
    )
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument(
        "--csv-out",
        type=Path,
        help="quartet mode only: append one row per repeat to this CSV (creating/extending it)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    quartet = [args.ceiling, args.asr_model, args.utility, args.asr_system]
    given = [f is not None for f in quartet]

    if any(given) and not all(given):
        parser.error("--ceiling, --asr-model, --utility, --asr-system must all be given together")
    if all(given) and args.run_dirs:
        parser.error("run_dirs and the quartet flags are mutually exclusive")
    if not all(given) and not args.run_dirs:
        parser.error("provide run_dirs, or all four of --ceiling/--asr-model/--utility/--asr-system")
    if args.csv_out is not None and not all(given):
        parser.error("--csv-out requires the quartet flags (--ceiling/--asr-model/--utility/--asr-system)")

    if all(given):
        result = _five_numbers(args.ceiling, args.asr_model, args.utility, args.asr_system, args.allow_dirty)
        if args.csv_out is not None:
            rows = [_quartet_csv_row(r, i) for i, r in enumerate(result["per_repeat"])]
            _write_quartet_csv_rows(rows, args.csv_out)
            print(f"wrote {len(rows)} row(s) to {args.csv_out}")
        if args.markdown:
            text = _render_quartet_markdown(result)
            print(text)
            if args.out_dir is None:
                parser.error("--out-dir is required with --markdown in quartet mode")
            path = _write_markdown_file(args.out_dir, text)
            print(f"wrote {path}")
        else:
            _print_quartet_text(result)
    else:
        results = [compute_run(run_dir, args.allow_dirty) for run_dir in args.run_dirs]
        if args.markdown:
            text = _render_markdown(results)
            print(text)
            out_dir = args.out_dir
            if out_dir is None:
                if len(args.run_dirs) != 1:
                    parser.error("--out-dir is required with --markdown when multiple run_dirs are given")
                out_dir = args.run_dirs[0]
            path = _write_markdown_file(out_dir, text)
            print(f"wrote {path}")
        else:
            _print_text(results)


if __name__ == "__main__":
    main()
