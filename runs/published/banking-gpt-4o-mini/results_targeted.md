| Config | Utility ceiling | Utility w/ policy | Retention | ASR_model | ASR_system | Interbolt block-rate |
|---|---|---|---|---|---|---|
| banking.yaml | 0.56 | 0.38 | 0.67 | 0.57 | 0.00 | 1.00 |

| Config | model_refused | out_of_scope | interbolt_blocked | attack_succeeded_defended | ambiguous_sink_match | attack_failed_unattributed |
|---|---|---|---|---|---|---|
| banking.yaml | 25 | 0 | 80 | 0 | 37 | 2 |

| Configuration | Blocks (benign + attack runs) | Approvals denied | Eval errors | Top matched rules |
|---------------|-------------------------------|-------------------|-------------|--------------------|
| banking.yaml | 380 | 0 | 0 | block_when_run_tainted (346), block_redirect_when_run_tainted (34) |