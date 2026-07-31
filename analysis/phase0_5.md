# Phase 0.5 addendum

Insert between Phase 0 and Phase 1 of `verification.md`. Resolves three issues the
artifact manifest surfaced, adds one guard, and adds one new claim. Everything here is
report-only except where it changes how a downstream number is computed.

---

## B. Block counts must exclude superseded attempts

The published `Blocks (benign + attack runs)` column aggregates over every event in
`interbolt_events.jsonl`, including executions that were discarded for scoring. Banking
D_targeted's 380 blocks span 165 executions of 153 cases, so roughly 8% of them belong to runs
that no published number is otherwise derived from.

Recompute every event-derived aggregate filtered to the `run_id` set in `case_to_run.csv`.
This affects:

- The `Blocks` column, per configuration.
- Rule attribution counts in section 2.4.
- The retry analysis in section 2.2, which is the most affected, since a superseded attempt is
  indistinguishable from a genuine retry unless it is filtered out first.
- Total decisions evaluated, the denominator for the zero-error claim in I7.

Report both the filtered and unfiltered count for each, with the difference, so the size of the
correction is visible.

---

## C. Version uniformity guard

Banking's runs span two Interbolt builds: `B_asr_model`, `C_utility_targeted`, and
`D_asr_system_targeted` on 0.1.1 at schema 7, against `C_utility_strict` and
`D_asr_system_strict` on 0.2.0 at schema 9. Travel is uniform at 0.2.0 and schema 9.

A cross-policy comparison spanning two builds cannot distinguish a policy effect from a version
effect. Implement a hard guard rather than a warning:

- Before computing any strict-versus-targeted comparison, assert that all four runs feeding it
  (A, B, C, D) record the same `interbolt.version` and the same `schema_version`. On mismatch,
  raise and name the offending runs.
- Before computing a taxonomy, assert that the B run and the D run it is compared against
  record the same version, since bucket assignment joins the two.
- Emit a `version_matrix.csv` covering suite, role, policy, `interbolt.version`,
  `schema_version`, `install_mode`, `agentdojo.version`, and `agentdojo.commit`.

Fields present only at schema 9, notably `policy_fingerprint`, must raise on access against a
schema 7 record rather than defaulting to null.

If banking is re-run uniformly on 0.2.0, this guard should pass everywhere and the code stays
in as a regression check.

---

## D. New claim: injection goals are achievable as standalone tasks

The manifest surfaced AgentDojo's pseudo-cases, where `user_task_id` holds an `injection_task_N`
string and both `injection_task_id` and `attack_type` are null. These run the attacker's goal as
an ordinary user task with no injection involved, and they are already scored: the sampled
banking `injection_task_0` pseudo-case completed the transfer and scored `utility: true`.

This answers an objection the post cannot currently answer. `model_refused` holds 25 of 144
banking cases and 71 of 140 travel cases, and a skeptical reader can ask whether the model
declined the attack or simply could not perform the action. The pseudo-cases separate those.

Compute, per suite, the `utility` boolean for each of the 9 banking and 7 travel pseudo-cases.
Report the count that succeed as standalone tasks, and cross-reference against N6: for each
injection task, its standalone success and its in-context refusal rate.

Favorable: every injection goal succeeds standalone, so `model_refused` is refusal in context
rather than incapacity, and the post's argument that model refusal is an unstable quantity to
depend on gets stronger. Unfavorable: some goals fail standalone, in which case those injection
tasks were never a real test of anything and should be excluded from `model_refused` or at least
named.

Add as N14, and add C30 to the claims ledger.

---

## E. Re-run scope

Recommendation: re-run banking in full on 0.2.0 in a single session. All six configurations,
A_ceiling, B_asr_model, C_utility_strict, C_utility_targeted, D_asr_system_strict, and
D_asr_system_targeted. Roughly 480 cases.

Re-running only the three 0.1.1 configurations is not sufficient. B feeds both taxonomies, so
moving it moves strict as well as targeted, and the strict-versus-targeted divergence analysis
needs both defended runs from the same session or it measures session noise rather than policy.

Travel is uniform at 0.2.0 and does not need re-running.

Every banking figure will move, since model nondeterminism between sessions affects
`u_ceiling`, `ASR_model`, and every bucket. Treat the current banking row as superseded rather
than as something to reconcile against.

If repeats are run, keep the existing `repeat_N` directory convention and record the repeat
index in `case_to_run.csv`, so all per-case analysis can be grouped by repeat and reported as a
range rather than a point estimate. In that case the confidence-bound work in N4 becomes
secondary to observed variance and should be reported alongside it rather than instead of it.

After the re-run, re-run Phase 0 and confirm three things: the version matrix is uniform, the
duplicate case keys either recur or do not, and the result-file counts still match the expected
16, 144, 16, 16, 144, 144. If duplicates recur, they come from harness retry logic and A3
should identify the trigger. If they do not, they were an artifact of resuming an interrupted
session, and the current banking artifacts were affected while future ones will not be.
