| Config | Utility ceiling | Utility w/ policy | Retention | ASR_model | ASR_system | Interbolt block-rate |
|---|---|---|---|---|---|---|
| strict.yaml | 0.56 | 0.38 | 0.67 | 0.57 | 0.00 | 1.00 |

| Config | model_refused | out_of_scope | interbolt_blocked | attack_succeeded_defended | ambiguous_sink_match | attack_failed_unattributed |
|---|---|---|---|---|---|---|
| strict.yaml | 25 | 0 | 78 | 0 | 37 | 4 |

| Configuration | Blocks (benign + attack runs) | Approvals denied | Eval errors | Top matched rules |
|---------------|-------------------------------|-------------------|-------------|--------------------|
| strict.yaml | 397 | 0 | 0 | block_when_run_tainted (397) |