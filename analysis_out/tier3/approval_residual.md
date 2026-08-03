## 2.7. Approval residual (proxy)

**This is a proxy, not the draft's `[N]` of `[M]` approval-residual figure** -- neither policy uses `require_approval`. Reported instead: benign state-changing calls blocked over benign state-changing calls attempted, per (suite, policy, repeat).

| Suite | Policy | Repeat | Attempted | Blocked | Proxy rate |
| --- | --- | --- | --- | --- | --- |
| banking | strict | repeat_0 | 20 | 19 | 0.950 (19/20) |
| banking | strict | repeat_1 | 22 | 21 | 0.955 (21/22) |
| banking | targeted | repeat_0 | 13 | 11 | 0.846 (11/13) |
| banking | targeted | repeat_1 | 17 | 14 | 0.824 (14/17) |
| travel | strict | repeat_0 | 6 | 6 | 1.000 (6/6) |
| travel | strict | repeat_1 | 9 | 9 | 1.000 (9/9) |
| travel | targeted | repeat_0 | 8 | 8 | 1.000 (8/8) |
| travel | targeted | repeat_1 | 8 | 8 | 1.000 (8/8) |
