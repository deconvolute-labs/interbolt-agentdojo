# Figure specification: Interbolt AgentDojo post

Four figures remain. Figures 2, 3, and 5 are plotted with matplotlib from `analysis_out/`.
Figure 4 is a hand-drawn SVG diagram in the style of Figure 1, not a plot.

This supersedes Phase 3 in `analysis/verification.md`, which was written before the results
existed and specified figures that no longer match the post.

---

## Shared requirements

Every figure ships as two SVG files, light and dark, with no title and no caption baked in,
since the caption lives in the `<Figure>` component.

```
public/static/images/blog/provenance-agentdojo-benchmark/
  figure2_light.svg   figure2.svg     (dark is the default filename)
  figure3_light.svg   figure3.svg
  figure4_light.svg   figure4.svg
  figure5_light.svg   figure5.svg
```

Alongside each pair, write the plotted data as `figureN_data.csv` so every number in the image
is auditable without rerunning the pipeline.

### Palette

One module-level dict per theme, selected by a `--theme` flag. No seaborn, no matplotlib style
sheets, no gridlines except a light horizontal one where a value axis needs reading.

| Role | Light | Dark |
| --- | --- | --- |
| Primary, anything defended or enforced | `#1d4ed8` | `#60a5fa` |
| Baseline, anything undefended | `#94a3b8` | `#52525b` |
| Attention, tasks that cannot succeed as posed | `#b45309` | `#fbbf24` |
| Loss caused by a block | `#b91c1c` | `#f87171` |
| Loss not caused by a block | `#a16207` | `#eab308` |
| Completed | `#15803d` | `#4ade80` |
| Text | `#18181b` | `#e4e4e7` |
| Muted text, axis labels | `#71717a` | `#a1a1aa` |
| Axis lines, light grid | `#d4d4d8` | `#3f3f46` |

Figure background must be **transparent** in both themes (`savefig(transparent=True)`), so the
site background shows through and the dark variant does not carry a black rectangle.

### Typography and chrome

- `font.family` sans-serif, `font.sans-serif` starting with DejaVu Sans, size 10, axis labels 10,
  tick labels 9, annotations 8.5.
- Remove the top and right spines. Keep the left spine only where a value axis is read.
- No legend box, no frame. Use a legend only where color encodes a category that cannot be
  labeled directly, and place it above the axes with `frameon=False`.
- Direct-label bars wherever there are few enough to do so.
- Figure width 7.6 inches at 100 dpi, matching the post's render width. Height per figure below.

### Data provenance

All paths relative to the repo root.

| Figure | Source |
| --- | --- |
| 2 | `analysis_out/phase2b/per_injection_task.csv` |
| 3 | `runs/published/results.csv` |
| 5 | `analysis_out/phase2b/utility_loss_attribution.csv` |

Never hardcode a number that appears in a figure. Read it from the CSV, and if a column the
spec names is absent, fail loudly rather than substituting.

---

## Figure 2: what each side of the decision depends on

Two panels sharing an x axis, which is the point of the figure. The left panel swings, the right
panel is flat, and putting them side by side is what makes the argument.

**Layout.** `fig, (axL, axR) = plt.subplots(1, 2, sharey=True)`, height 4.2 inches. Y axis 0 to 1
on both, ticks at 0, 0.25, 0.5, 0.75, 1.0, labeled only on the left panel.

**X axis, identical on both panels.** Sixteen injection tasks in suite order, banking
`injection_task_0` through `8` then travel `injection_task_0` through `6`. Label them `B0`
through `B8` and `T0` through `T6` to keep the axis readable, and separate the two suites with a
vertical rule in the axis-line color plus a small "banking" and "travel" label above the axis.

Two bars per task, one per repeat, side by side.

**Left panel, model refusal.** Value is `refused_count / case_count`. This is policy-invariant,
so deduplicate on policy first and assert the two policy rows agree before dropping one. Bars in
the baseline color, since this is the undefended model's own behavior.

Mark the two tasks that cannot succeed as posed, travel `injection_task_1` and banking
`injection_task_8`, by drawing their bars with a hatch (`///`) and an edge in the attention
color. Add one line of legend text above the panel reading "hatched: goal cannot succeed as
posed", `frameon=False`.

Axis label: "fraction of cases the undefended model declined".

**Right panel, policy block rate.** Value is `block_rate_num / block_rate_den`, pooled across
both policies within a repeat, so the bar structure matches the left panel exactly. Assert every
pooled rate equals 1.0 and fail if not, since that assertion is the finding.

Where `block_rate_den` is zero, draw no bar. Instead place a small muted "no gated cases" tick
mark at the baseline for that task and repeat.

Bars in the primary color. Annotate each bar with its denominator as `n=NN`, rotated vertical
inside the bar top if it fits, otherwise just above it.

Axis label: "fraction of attacks reaching a gated sink that were blocked".

**What the figure must make obvious.** The left panel ranges 0.00 to 0.70 with no pattern, and
the right panel is a flat row of bars at 1.00. Do not add a trend line, a mean line, or any
annotation implying the right panel is boring by accident.

---

## Figure 3: security and utility, before and after

Two panels, height 3.6 inches, not sharing a y axis.

**X axis, both panels.** Eight configurations, grouped by suite then policy then repeat. Label
as two-line ticks: `strict` / `r0`, `strict` / `r1`, `targeted` / `r0`, `targeted` / `r1`, with
"banking" and "travel" labels above and a separating rule, as in Figure 2.

**Left panel, attack success.** Paired bars per configuration: `asr_model` in the baseline color
and `asr_system` in the primary color. Y axis 0 to 0.6. Annotate each bar with `k/n` drawn from
`asr_model_num` over `asr_model_den` and `asr_system_num` over `asr_system_den`, not with the
rounded rate. Axis label "attack success rate".

Note that `asr_model` is policy-invariant within a suite and repeat, so the same baseline value
appears twice per suite per repeat. That is correct and should not be deduplicated here, because
each defended bar needs its own baseline beside it.

**Right panel, benign utility.** Paired bars: `u_ceiling` in the baseline color and `u_policy` in
the primary color. Y axis 0 to 1.0. Annotate with `k/n` from the `_num` and `_den` columns. Axis
label "benign tasks completed".

**One legend for both panels**, above the figure, two entries: "undefended" and "under policy".

**What the figure must make obvious.** Travel's baseline utility bar is visibly different between
repeat 0 and repeat 1, which is why the repeats are not averaged. Do not add error bars, a mean,
or any summary across repeats.

---

## Figure 4: one attacked case, defended against undefended

A hand-drawn SVG diagram, not a plot. Build it the way Figure 1 was built, as a Python module
emitting SVG text with a palette dict per theme, so the two variants stay in sync.

**Content.** Banking `user_task_0` with `injection_task_3`, two trajectories side by side, read
from `analysis_out/case_studies.md` (CS1). Left column undefended, right column defended, same
vertical time axis so the point where they diverge is visually aligned.

**Each step is a row** showing the tool name in monospace, the arguments abbreviated to what
matters, and the outcome. The user's prompt sits above both columns, since it is shared.

Steps to show, verified against the case study export before drawing:

1. `read_file(bill-december-2023.txt)` — allowed in both. Annotate the return with a short
   excerpt showing the injected instruction, in the attention color, and mark that this is the
   point the run becomes tainted.
2. The attacker's `send_money` to the injected account — succeeds on the left, blocked on the
   right with the error message the agent actually receives.
3. Any subsequent attempts, including the pivot to a different sink if the trajectory has one.
4. The final assistant message, abbreviated, showing that the defended run reports the refusal.

**Encoding.** Undefended column in the baseline color with a neutral outcome marker. Defended
column in the primary color, with blocked steps marked in the block color. The taint point marked
identically in both columns, since it happens in both.

Keep it to at most six rows per column. If the real trajectory is longer, elide the middle with a
vertical ellipsis rather than shrinking the type.

**What the figure must make obvious.** Reading the bill is what taints the run, the same call
that succeeds on the left is refused on the right, and the money moves in one column and not the
other.

---

## Figure 5: benign tasks by outcome

Horizontal stacked bars, height 3.8 inches, one bar per configuration, eight bars.

**Y axis.** Same eight configurations as Figure 3, in the same order, so a reader moving between
the two figures finds them in the same place. Banking bars total 16 and travel bars total 20, so
the x axis runs 0 to 20 with banking bars visibly shorter. Do not normalize to a fraction, since
the absolute counts are small enough to read and normalizing hides that the suites differ in size.

**Segments, in this stacking order**, left to right:

| Segment | Column in the CSV | Color role |
| --- | --- | --- |
| completed | `unaffected` | completed |
| blocked but scored complete | `blocked_but_recovered` | primary |
| lost to a block | `policy_caused_loss` | loss caused by a block |
| lost without a block | `run_variance` | loss not caused by a block |
| passed only under policy | `reverse_variance` | attention |
| failed undefended too | `model_limitation` | baseline |

The post's current caption names five segments and the data has six. `reverse_variance` is small
but non-zero on travel, so include it and update the caption to match rather than folding it into
another segment.

**Annotate each segment with its count** where the segment is wide enough, in the figure
background color for dark segments and in text color for light ones. Suppress the label on
segments of zero.

**Legend** above the figure, one row, six entries, `frameon=False`.

**What the figure must make obvious.** Banking's "lost without a block" segment is absent in all
four configurations while travel's is present in all four. That contrast is the reason the figure
exists, so verify it survives the color choices at the rendered size.

---

## Checks before handing the figures over

- Every figure renders legibly at 700 px wide in a browser, not just in the notebook.
- The dark variant sits correctly on the site's dark background, with a transparent figure
  background and no stray white rectangle.
- Text in the SVG is real text, not paths, so it stays selectable and scales cleanly. Set
  `plt.rcParams['svg.fonttype'] = 'none'`.
- Every number annotated in a figure matches the corresponding row of `figureN_data.csv`.
- Figure 2's right panel is 1.00 everywhere, and the assertion that makes it so is in the code
  rather than in a comment.
- Figure 5's segments sum to 16 on banking rows and 20 on travel rows.
