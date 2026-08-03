## N13. Cross-suite consistency

Banking (11 tools) vs. travel (28 tools), same metrics side by side. `taint_onset_median` is pooled across both repeats for a (suite, policy) -- it does not vary by repeat in this table even though the row grain is per-repeat.

| Suite | Policy | Repeat | Tools | Gated sinks | Gated calls | Blocks | Blocks/gated call | Attacked cases | ...with block | Share | Block rate | Taint onset (median) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| banking | strict | 0 | 11 | 5 | 343 | 331 | 0.965 | 144 | 127 | 0.88 | 1.00 (66/66) | 1.0 |
| banking | strict | 1 | 11 | 5 | 382 | 371 | 0.971 | 144 | 132 | 0.92 | 1.00 (68/68) | 1.0 |
| banking | targeted | 0 | 11 | 5 | 348 | 320 | 0.920 | 144 | 118 | 0.82 | 1.00 (67/67) | 1.0 |
| banking | targeted | 1 | 11 | 5 | 357 | 328 | 0.919 | 144 | 122 | 0.85 | 1.00 (66/66) | 1.0 |
| travel | strict | 0 | 28 | 6 | 152 | 150 | 0.987 | 140 | 74 | 0.53 | 1.00 (22/22) | 1.0 |
| travel | strict | 1 | 28 | 6 | 144 | 142 | 0.986 | 140 | 71 | 0.51 | 1.00 (27/27) | 1.0 |
| travel | targeted | 0 | 28 | 6 | 137 | 128 | 0.934 | 140 | 73 | 0.52 | 1.00 (24/24) | 3.0 |
| travel | targeted | 1 | 28 | 6 | 121 | 116 | 0.959 | 140 | 72 | 0.51 | 1.00 (23/23) | 3.0 |

