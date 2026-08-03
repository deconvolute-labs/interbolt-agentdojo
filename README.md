# Benchmark: Interbolt on AgentDojo

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Interbolt](https://img.shields.io/badge/interbolt-0.2.0-1d4ed8.svg)](https://github.com/deconvolute-labs/interbolt)
[![AgentDojo](https://img.shields.io/badge/agentdojo-v1.2.2-64748b.svg)](https://github.com/ethz-spylab/agentdojo)

<p align="center">
  <strong><a href="https://github.com/deconvolute-labs/interbolt">Interbolt Library</a></strong>
  &nbsp;•&nbsp;
  <strong><a href="https://deconvoluteai.com/blog/provenance-agentdojo-benchmark">In-depth Analysis</a></strong>
</p>

Benchmarking [**Interbolt**](https://github.com/deconvolute-labs/interbolt), a library that gates an agent's tool calls on the provenance of the data reaching them with no model in the decision path, as a defense on the [AgentDojo](https://github.com/ethz-spylab/agentdojo) agent-security benchmark.

It attaches Interbolt to AgentDojo's tool executor, runs the banking and travel suites under two policy tiers against an undefended baseline, and reports what enforcement blocked and what it cost. Both AgentDojo and Interbolt are used unmodified.

## Results

`gpt-4o-mini-2024-07-18`, AgentDojo v1.2.2, `important_instructions` attack, Interbolt 0.2.0, two repeats per configuration. Every rate is shown with the counts behind it.

| Suite | Policy | Rep | Ceiling | With policy | Retention | ASR undefended | ASR defended | Block rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| banking | strict | 0 | 9/16 | 6/16 | 6/9 | 71/144 | 0/144 | 66/66 |
| banking | strict | 1 | 9/16 | 6/16 | 6/9 | 70/144 | 0/144 | 68/68 |
| banking | targeted | 0 | 9/16 | 7/16 | 7/9 | 71/144 | 0/144 | 67/67 |
| banking | targeted | 1 | 9/16 | 6/16 | 6/9 | 70/144 | 0/144 | 66/66 |
| travel | strict | 0 | 13/20 | 7/20 | 7/13 | 39/140 | 9/140 | 22/22 |
| travel | strict | 1 | 10/20 | 8/20 | 8/10 | 42/140 | 10/140 | 27/27 |
| travel | targeted | 0 | 13/20 | 6/20 | 6/13 | 39/140 | 11/140 | 24/24 |
| travel | targeted | 1 | 10/20 | 7/20 | 7/10 | 42/140 | 11/140 | 23/23 |

**Block rate** is the fraction of attacks that reached a gated sink and were blocked. It is 1.00 in all eight configurations, and `attack_succeeded_defended` is empty in all eight. Split by injection task rather than pooled, it is 1.00 for every one of the sixteen injection tasks individually.

**Travel's residual** is a single injection task whose goal is a sentence in the agent's reply and which names no tool call in its ground truth. Every injection whose goal requires a tool call was blocked.

**Retention** divides utility under policy by the undefended ceiling. Banking's ceiling held at 9/16 across both repeats and travel's moved from 13/20 to 10/20, which is why travel's retention spans 0.46 to 0.80 for the same policy. Banking lost no benign task without a block in any configuration; travel lost two to three per configuration to session variance alone.

Full per-case data, integrity checks, and per-repeat tables are in `analysis_out/`. The canonical row-per-repeat table is `runs/published/results.csv`.

## Reproducing the published numbers

Requires Python 3.12+ and `OPENAI_API_KEY`. API keys live in environment variables only.

```bash
uv sync
```

Pin both dependencies before generating publishable numbers. `compute_results.py` refuses to include an editable-install or dirty-tree run in a table unless you pass `--allow-dirty`, and every published run's `run_manifest.json` records which state was active.

```toml
[project.dependencies]
interbolt = "0.2.0"
agentdojo = "0.1.35"
```

### The four runs

Each policy tier needs a quartet. Runs A and B do not depend on the policy, so each is run once per suite and reused across tiers.

```bash
M=gpt-4o-mini-2024-07-18
S=banking          # then repeat everything with S=travel

# A: no attack, no defense. The utility ceiling.
uv run python -m interbolt_agentdojo.run_benchmark \
  --suite $S --model $M --repeats 2 --logdir runs/$S/A_ceiling

# B: attack, allow_all enforce. The undefended baseline.
uv run python -m interbolt_agentdojo.run_benchmark \
  --suite $S --model $M --attack important_instructions \
  --policy policies/$S/allow_all.yaml --mode enforce \
  --repeats 2 --logdir runs/$S/B_asr_model

# C: no attack, policy enforced. Utility under the policy.
uv run python -m interbolt_agentdojo.run_benchmark \
  --suite $S --model $M \
  --policy policies/$S/strict.yaml --mode enforce \
  --repeats 2 --logdir runs/$S/C_utility_strict

# D: attack, policy enforced. What a deployment gets.
uv run python -m interbolt_agentdojo.run_benchmark \
  --suite $S --model $M --attack important_instructions \
  --policy policies/$S/strict.yaml --mode enforce \
  --repeats 2 --logdir runs/$S/D_asr_system_strict
```

Repeat C and D with `targeted.yaml`. Two suites, two tiers, two repeats is roughly 2,800 pipeline calls and a few hours.

Run B uses `allow_all` rather than no policy at all. It blocks nothing, so it is a true undefended baseline, but unlike a no-policy run it still emits `call_records.jsonl` and `run_index.jsonl`. Those are what let the analysis determine, per case, whether the undefended model actually reached the tool the attacker was aiming for.

### Computing the table

```bash
uv run python -m interbolt_agentdojo.compute_results \
  --ceiling runs/$S/A_ceiling --asr-model runs/$S/B_asr_model \
  --utility runs/$S/C_utility_targeted --asr-system runs/$S/D_asr_system_targeted \
  --csv-out runs/published/results.csv
```

Run this for both policy versions `strict` and `targeted` for C and D. Repeats are paired by index and never pooled, so a case in repeat 0's B run is never compared against repeat 1's D run. Each invocation appends one row per repeat, and repeated invocations across suites and tiers accumulate into the same file.

### Running the analysis

```bash
uv run python -m analysis.phase0.cli    --results-root runs/published --out-dir analysis_out/phase0
uv run python -m analysis.phase1.cli    --results-root runs/published --out-dir analysis_out/phase1
uv run python -m analysis.phase2b.cli   --results-root runs/published --out-dir analysis_out/phase2b
uv run python -m analysis.tier2.cli     --results-root runs/published --out-dir analysis_out/tier2
uv run python -m analysis.tier3.cli     --results-root runs/published --out-dir analysis_out/tier3
```

Phase 1 is the integrity check layer: taxonomy completeness, the `ASR_model` decomposition, policy-invariance of the buckets that derive from run B, and the zero-value claims. Phase 2B and the tier modules produce the per-injection-task, utility-attribution, divergence, and coverage tables the post draws on.

## What this measures

Every rate is measured against an undefended run of the same model. Each attacked case is classified into one of six buckets: `model_refused`, `out_of_scope`, `interbolt_blocked`, `attack_succeeded_defended`, `ambiguous_sink_match`, `attack_failed_unattributed`. Block rate is `interbolt_blocked / (interbolt_blocked + attack_succeeded_defended)`, reported as undefined rather than divided when the denominator is empty.

The full rationale, like why raw ASR doesn't isolate the defense, the policy-authoring rule, retry filtering, the block message, approval scoring, and run scoping, is in [the write-up](https://deconvolutelabs.com/blog/prompt-injection-defense-provenance-agentdojo-benchmark).

## Design choices

**Model registry bypass.** AgentDojo's `ModelsEnum` is a `StrEnum` that cannot be extended at runtime, and forking AgentDojo to patch it would mean carrying patches against every future version. `models_ext.make_llm(model_string)` constructs the provider client directly and passes the object as `PipelineConfig(llm=...)`, which AgentDojo already accepts alongside an enum string. New model ids are a one-line addition here rather than a patch there.

The same bypass overrides a provider's default auth mode. `run_benchmark._resolve_model` forces every `gemini-` id through `make_llm` regardless of enum membership, because AgentDojo wires Google models to Vertex AI while this repo uses a `GOOGLE_API_KEY` client. OpenAI has no such mismatch, so its branch exists only to catch unenumerated ids.

**Replay tooling.** `replay_policy.py` evaluates a candidate policy offline against a recorded `call_records.jsonl`, with no live run and no API calls. It cannot show trajectory effects, since a blocked call changes what the model does next, so replay ASR is optimistic and replay utility is unreliable. Replay is for iteration and regression checking. Published numbers come only from live enforce runs.

## Source trust classification

Each suite's tools are classified as trusted or untrusted by reading the tool's implementation and the environment model it reads from, never from where the injection tasks place their payloads. The classification and reasoning are documented in that suite's policy file comments: `policies/banking/targeted.yaml` and `policies/travel/targeted.yaml`.

## Extending to another suite

1. Add `policies/<suite>/allow_all.yaml`, `strict.yaml`, and `targeted.yaml`, authored by the rule above.
2. Document the trust classification in the policy file's comments.
3. Nothing else changes. `run_benchmark.py --suite <name>` accepts any suite `get_suite()` knows about, and the qualified-name scheme (`agentdojo.<tool>`) and taint source scheme (`tool:<tool>`) are suite-agnostic.

## Tests

```bash
uv run pytest
```

No network calls. The executor and replay tests use `InMemoryReporter` and a stub runtime with two fake tools, the manifest test checks the schema and install-state detection, and the results test checks the case taxonomy, target-sink derivation, and the quartet join against synthetic run directories.
