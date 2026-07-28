| Config | Utility ceiling | Utility w/ policy | Retention | ASR_model | ASR_system | Interbolt block-rate |
|---|---|---|---|---|---|---|
| strict.yaml | 0.55 | 0.35 | 0.64 | 0.28 | 0.08 | 1.00 |

| Config | model_refused | out_of_scope | interbolt_blocked | attack_succeeded_defended | ambiguous_sink_match | attack_failed_unattributed |
|---|---|---|---|---|---|---|
| strict.yaml | 71 | 10 | 24 | 0 | 30 | 5 |

| Configuration | Blocks (benign + attack runs) | Approvals denied | Eval errors | Top matched rules |
|---------------|-------------------------------|-------------------|-------------|--------------------|
| strict.yaml | 120 | 0 | 0 | block_when_run_tainted (120) |