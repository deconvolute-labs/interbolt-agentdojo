## 2.8. Suite metadata

Tool counts per AgentDojo v1.2.2 suite. `agentdojo`'s `Function` has no read-only/state-changing attribute (checked the installed 0.1.35 package directly), so banking's and travel's split is a hand-verified constant, checked against each tool's actual body in `agentdojo/default_suites/v1/tools/{banking_client,travel_booking_client}.py` -- independent of any policy YAML's sink list, though it happens to match which sinks `strict.yaml`/`targeted.yaml` gate. `slack`/`workspace` are reported by total tool count only, for the min/max comparison below, not hand-classified.

| Suite | Total tools | State-changing | Read-only | Hand-verified split |
|---|---|---|---|---|
| banking | 11 | 5 | 6 | True |
| slack | 11 | n/a | n/a | False |
| travel | 28 | 6 | 22 | True |
| workspace | 24 | n/a | n/a | False |

**Largest surface: travel (28 tools).** Strict, unique maximum.
**Smallest surface: banking, slack (11 tools).** Tied among 2 suites (banking, slack), **not a strict minimum** -- this is exactly why the draft's text was softened to "among."

