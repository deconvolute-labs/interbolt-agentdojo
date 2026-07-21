# Benchmark Interbolt on Agentdojo

## What this is

A benchmark harness that evaluates [Interbolt](https://github.com/) (provenance-gated tool calls, no model in the decision path) as a defense on the [AgentDojo](https://github.com/ethz-spylab/agentdojo) agent-security benchmark. It runs AgentDojo's banking suite under four Interbolt policy variants against a no-defense baseline, and produces attack success rate (ASR) and utility numbers with full reproducibility metadata, plus record/replay tooling for fast offline policy iteration.

## Setup

```bash
uv sync
```

Requires Python 3.12+ (see `pyproject.toml`).

**API keys** live in environment variables only, never in files. `.env` is gitignored; put keys there or export them in your shell. AgentDojo's Anthropic provider constructs `anthropic.Anthropic()` with no explicit key argument, so it relies on the Anthropic SDK's own default: `ANTHROPIC_API_KEY`.

**Interbolt source toggle** (`pyproject.toml`):

- **Dev** (default, checked in): editable path dependency against the sibling checkout.

  ```toml
  [tool.uv.sources]
  interbolt = { path = "../interbolt", editable = true }
  agentdojo = { path = "../agentdojo", editable = true }
  ```

- **Pinned** (required for published numbers): delete the `interbolt` line above and pin an exact release in `[project.dependencies]` instead, e.g. `"interbolt==0.1.1"`. Pin `agentdojo` to a git SHA rather than its PyPI/tag version, since the sibling checkout used during development trails the latest tag:

  ```toml
  agentdojo = { git = "https://github.com/ethz-spylab/agentdojo", rev = "089ed468cf3ed0322acc66b0211f26d9d90dbf60" }
  ```

`run_manifest.json` (see Methodology) records which state was active for every run; `compute_results.py` refuses to include an editable-install or dirty-tree run in a publishable table unless you pass `--allow-dirty`.

**Known-good models.** `--model` is a plain string everywhere; any id AgentDojo's `ModelsEnum` already knows works as-is, and anything else goes through `models_ext.make_llm` (see Design choices below). `claude-3-haiku-20240307`, the id AgentDojo's enum lists as its cheap-iteration Haiku, has been fully retired by Anthropic (confirmed live: the API 404s on it) -- use **`claude-haiku-4-5-20251001`** instead for cheap iteration (note: still a comparatively weak tool-caller; results from it are plumbing-verification only). For published runs, one current frontier model per provider, exact dated snapshot id pinned here once chosen (e.g. `claude-sonnet-5` for Anthropic).

## Design choices

**Model registry patching.** AgentDojo's `ModelsEnum` is a `StrEnum` and tops out around Claude 3.7 -- it can't be extended at runtime, and forking AgentDojo to patch it would mean carrying patches against every future AgentDojo version instead of pinning a SHA. Instead, `models_ext.make_llm(model_string)` constructs the provider client (`AnthropicLLM`) directly and passes the resulting object as `PipelineConfig(llm=...)`, which AgentDojo already accepts alongside a `ModelsEnum` string (see `AgentPipeline.from_config`'s `isinstance(config.llm, str)` branch). AgentDojo stays unmodified and pinnable; new model ids are a one-line addition to our own adapter, not a patch to theirs.

**Block message constant.** A blocked or denied tool call always returns the exact string `"Blocked by security policy."` as its error -- never the matched rule name or CEL condition text. That detail is model-visible context; leaking it hands an attacker free information about exactly which policy edge to route around next. Every decision's full detail (rule, condition, contributing labels) still reaches the reporter's `interbolt_events.jsonl` -- it's just never echoed back into the transcript the model reads.

**Approval auto-deny scoring.** `interbolt.configure()`'s `approval_resolver` defaults to `auto_deny` and is never overridden here -- there's no human in the loop during a benchmark run. A `require_approval` decision therefore always denies: it scores as *blocked* for the security question (did the attack succeed?) and as *failure* for the utility question (did the benign task complete?). `generic.yaml`'s use of `require_approval` instead of `block` is meaningful for audit/diagnostic purposes (the emitted event records the softer intended posture) but produces identical enforcement outcomes to a hard `block` in this harness.

**Run scoping.** AgentDojo's benchmark loop calls `pipeline.query()` exactly once per (user_task, injection_task) case. `RunScopedPipeline` wraps the whole pipeline and opens one `runtime.agent_context_sync(AGENT_ID)` per `query()` call, so `Decision.run_tainted` never leaks between cases. It also writes `run_index.jsonl` (`{seq, run_id, started_at}`) -- the join key between Interbolt's own `interbolt_events.jsonl`/`call_records.jsonl` and AgentDojo's per-task trace files, which AgentDojo's own logs don't carry.

## Running

All commands assume `ANTHROPIC_API_KEY` is set. Costs/times are order-of-magnitude for `claude-haiku-4-5-20251001` on the full banking suite (16 user tasks x 9 injection tasks = 144 with-injection cases, or 16 without); a `--user-tasks`/`--injection-tasks` subset scales down proportionally.

**Baseline (no defense):**

```bash
uv run python -m interbolt_agentdojo.run_benchmark \
  --suite banking --model claude-haiku-4-5-20251001 \
  --attack important_instructions \
  --logdir runs/baseline
```

~144 cases, a few minutes, low single-digit dollars with Haiku.

**Record a replay corpus** (one spend, two artifacts -- see epistemics note below):

```bash
uv run python -m interbolt_agentdojo.record_corpus \
  --suite banking --model claude-haiku-4-5-20251001 \
  --attack important_instructions \
  --logdir runs/corpus_banking
```

Same cost/time as the baseline run above. Produces `runs/corpus_banking/repeat_0/interbolt_events.jsonl` and `call_records.jsonl` (the replay corpus) plus AgentDojo traces that ARE the baseline numbers.

**Replay iteration loop** (offline, no API calls, sub-second):

```bash
uv run python -m interbolt_agentdojo.replay_policy \
  --corpus runs/corpus_banking/repeat_0/call_records.jsonl \
  --policy policies/targeted/banking.yaml \
  --compare policies/strict.yaml
```

**Enforce runs** (one per policy tier):

```bash
uv run python -m interbolt_agentdojo.run_benchmark \
  --suite banking --model claude-haiku-4-5-20251001 \
  --attack important_instructions \
  --policy policies/strict.yaml --mode enforce \
  --logdir runs/strict
```

Repeat for `generic.yaml`, `targeted/banking.yaml`. Same order-of-magnitude cost/time as baseline, per tier. Add `--repeats N` for mean/spread reporting; each repeat gets its own subdirectory so AgentDojo's per-logdir task caching doesn't skip re-running.

**Compute results:**

```bash
uv run python -m interbolt_agentdojo.compute_results \
  runs/baseline runs/generic runs/strict runs/targeted_banking --markdown
```

## Methodology

**Policy-authoring blindness (verbatim rule).** Policies are authored against what the *user tasks* legitimately require and against general security judgment. They MUST NOT be tuned by inspecting which injection tasks succeed and patching those specific holes; that is overfitting the test set and invalidates the security claim. Iterating on utility (which benign calls get wrongly gated) via replay is fine; iterating on ASR via replay is diagnosis only, not a tuning signal for rule-by-rule patches.

**Replay epistemics.** `replay_policy.py` shows which recorded calls a candidate policy would gate, evaluated offline against `call_records.jsonl` via `interbolt.policy.evaluate` directly (no live run, no API calls). It cannot show trajectory effects: a blocked call changes what the model does next, which replay can't simulate. Replay ASR is therefore optimistic and replay utility is unreliable. Replay is for iteration and regression-checking only -- **published numbers come only from live `enforce` runs.**

**Repeats and spread.** `--repeats N` runs N full independent passes, each in its own `repeat_<i>/` subdirectory (own manifest, traces, events). `compute_results.py` reports mean and min-max spread across repeats for every metric.

**Publishable-run criteria.** A run is only included in a publishable table if its manifest shows a pinned (non-editable) install and a clean source tree for both `interbolt` and `agentdojo`; `compute_results.py` enforces this and refuses (loudly, not silently) otherwise unless `--allow-dirty` is passed for development use.

### Source trust classification: banking

Trust classification is not free-form -- it comes from reading each tool's implementation and the environment model it reads from, never from where the suite's 9 injection tasks happen to place their payloads. Tuning this table against observed attack success would be exactly the overfitting the rule above forbids.

| Tool | Kind | Trust | Why |
|------|------|-------|-----|
| `read_file` | read-only | untrusted | Returns `Filesystem.files[path]` verbatim: arbitrary attacker-writable text content, by construction. |
| `get_most_recent_transactions` | read-only | untrusted | Returns `Transaction` objects whose `subject`/`recipient` fields are free-form strings settable by any prior `send_money`/`schedule_transaction` call. |
| `get_scheduled_transactions` | read-only | untrusted | Same reasoning as above. |
| `get_iban` | read-only | trusted | Scalar `BankAccount.iban` field, no attacker-writable path in the tool's implementation. |
| `get_balance` | read-only | trusted | Scalar `BankAccount.balance` field, same reasoning. |
| `get_user_info` | read-only | trusted | `UserAccount` name/address fields are mutable only via the state-changing `update_user_info` sink (itself gated), not a standing read channel for injected content. |
| `send_money`, `schedule_transaction`, `update_scheduled_transaction`, `update_password`, `update_user_info` | state-changing | untrusted (all tiers except `allow_all`) | Every allowed tool call's formatted result is tainted under `tool:<name>` (see Run scoping); these sinks' own success messages echo caller-supplied strings back into the transcript, so they're classified defensively. |

This table is specific to banking. A new suite adds its own table here (see "Extending to other suites" below) -- the classification method is what's portable, not the table's contents.

## Results

All numbers: banking suite, AgentDojo v1.2.2, attack = important_instructions,
N = &lt;repeats&gt; repeats, mean (min-max). Approvals auto-denied (scored as blocked
for security, as failure for utility). Manifests for every published run are in
`runs/published/`.

*Not yet run: this harness has not had a full published pass. Fill in via*
*`compute_results.py --markdown` *after running the commands above with pinned*
*installs.*

### Model: &lt;model id&gt;

| Configuration        | Benign utility | Utility under attack | Targeted ASR |
|-----------------------|----------------|-----------------------|--------------|
| No defense (baseline)|                |                      |              |
| generic.yaml         |                |                      |              |
| strict.yaml          |                |                      |              |
| targeted/banking.yaml|                |                      |              |

### Interbolt event summary (enforce runs)

| Configuration | Blocks | Approvals denied | Eval errors | Top matched rules |
|---------------|--------|-------------------|-------------|--------------------|

### Scope notes

*Injection tasks not routed through any gated sink, and other observed*
*limitations, go here once real runs exist.*

### Run index

| Run dir | Manifest | interbolt version/commit | agentdojo commit | Date |
|---------|----------|---------------------------|-------------------|------|

## Extending to other suites

Banking is the only suite wired up in v1; the structure extends to others without refactoring:

1. Add `policies/targeted/<suite>.yaml`, authored the same way: read every tool's implementation and the environment model it reads from, classify each tool's `tool:<name>` source as trusted/untrusted from that data model (never from injection placement), and write argument-aware rules for state-changing sinks where a genuine, non-overfit pattern exists.
2. Add that suite's own "Source trust classification" table to this README (see the banking one above as the template).
3. Nothing else changes in code -- `run_benchmark.py --suite <name>` already accepts any suite `get_suite()` knows about, and `executor.py`'s qualified-name scheme (`agentdojo.<tool_name>`) and taint source scheme (`tool:<tool_name>`) are suite-agnostic.

## Tests

```bash
uv run pytest
```

No network calls: `tests/test_executor.py` and `tests/test_replay.py` use `InMemoryReporter` and a stub `FunctionsRuntime` with two fake tools; `tests/test_manifest.py` checks the manifest schema and this repo's own (editable, dev-mode) install detection.
