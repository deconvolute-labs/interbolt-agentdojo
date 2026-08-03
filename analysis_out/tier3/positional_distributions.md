## N8 + N9 remainder: positional distributions

### N8. Taint onset

Call index at which a run first becomes tainted, over every scored run in roles B, C, and D (A never touches Interbolt, excluded). Histogram: `figures/taint_onset_histogram.{svg,png}` (blue pair `#3987e5` banking / `#184f95` travel, validated colorblind-safe via the dataviz skill's palette validator).

| Suite | Runs | Ever tainted | Never tainted | Onset index (min/median/max) |
|---|---|---|---|---|
| banking | 928 | 588 | 340 | 1 / 1.0 / 3 |
| travel | 920 | 638 | 282 | 1 / 1.0 / 7 |

### N9 remainder. Block position as a fraction of trajectory length

For every C/D case with at least one block, the call index of the first block divided by that run's total call count. The main N9 question (blocks vs. lost tasks) is already answered by N2's `blocked_but_recovered` -- this is only the position statistic.

| Suite | Role | Cases with a block | Fraction (min/median/max) |
|---|---|---|---|
| banking | C_utility | 37 | 0.14 / 0.50 / 0.75 |
| banking | D_asr_system | 499 | 0.08 / 0.33 / 0.80 |
| travel | C_utility | 26 | 0.50 / 0.80 / 0.88 |
| travel | D_asr_system | 290 | 0.10 / 0.70 / 0.95 |

