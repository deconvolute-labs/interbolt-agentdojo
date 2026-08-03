## N10. Trajectory cost

Calls per case, D vs. B (attacked) and C vs. A (benign). Positive `delta` means the defended run made more calls than the undefended baseline for the same case.

### Attacked (D vs. B)

| Suite | Policy | Repeat | Cases | Total calls (undefended) | Total calls (defended) | Total delta |
|---|---|---|---|---|---|---|
| banking | strict | 0 | 144 | 543 | 716 | 173 |
| banking | strict | 1 | 144 | 532 | 748 | 216 |
| banking | targeted | 0 | 144 | 543 | 724 | 181 |
| banking | targeted | 1 | 144 | 532 | 757 | 225 |
| travel | strict | 0 | 140 | 1154 | 1242 | 88 |
| travel | strict | 1 | 140 | 1151 | 1313 | 162 |
| travel | targeted | 0 | 140 | 1154 | 1137 | -17 |
| travel | targeted | 1 | 140 | 1151 | 1211 | 60 |

### Benign (C vs. A)

| Suite | Policy | Repeat | Cases | Total calls (undefended) | Total calls (defended) | Total delta |
|---|---|---|---|---|---|---|
| banking | strict | 0 | 16 | 42 | 58 | 16 |
| banking | strict | 1 | 16 | 44 | 56 | 12 |
| banking | targeted | 0 | 16 | 42 | 44 | 2 |
| banking | targeted | 1 | 16 | 44 | 49 | 5 |
| travel | strict | 0 | 20 | 149 | 155 | 6 |
| travel | strict | 1 | 20 | 154 | 147 | -7 |
| travel | targeted | 0 | 20 | 149 | 151 | 2 |
| travel | targeted | 1 | 20 | 154 | 161 | 7 |

### Named sanity check: banking strict's D-run `blocks_attacked` swing

Recomputed independently: repeat 0 = 297, repeat 1 = 334. **Matches the spec's published 297/334 -- this module's counting agrees with the already-verified figure.**

