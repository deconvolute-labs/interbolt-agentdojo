| Config | Utility ceiling | Utility w/ policy | Retention | ASR_model | ASR_system | Interbolt block-rate |
|---|---|---|---|---|---|---|
| targeted.yaml | 0.55 | 0.40 | 0.73 | 0.28 | 0.08 | 1.00 |

| Config | model_refused | out_of_scope | interbolt_blocked | attack_succeeded_defended | ambiguous_sink_match | attack_failed_unattributed |
|---|---|---|---|---|---|---|
| targeted.yaml | 71 | 10 | 23 | 0 | 30 | 6 |

| Configuration | Blocks (benign + attack runs) | Approvals denied | Eval errors | Top matched rules |
|---------------|-------------------------------|-------------------|-------------|--------------------|
| targeted.yaml | 122 | 0 | 0 | block_when_run_tainted (89), block_exfil_to_external_when_tainted (33) |
