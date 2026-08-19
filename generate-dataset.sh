#!/usr/bin/env bash
# Final demo dataset generation.
# Run from the interbolt-agentdojo repo root, after the adapter changes,
# the policy work, and the single-task checkpoint are all done.

set -euo pipefail

MODEL="gpt-4o-mini-2024-07-18"
V1="./policies/workspace/workspace-demo.v1.yaml"
V2="./policies/workspace/workspace-demo.v2.yaml"
OUT="./runs/workspace2"

run() {
  local agent="$1" policy="$2" mode="$3" tasks="$4" inj="${5:-}"
  local dir="$OUT/${6}/${agent}/${tasks}${inj:+__$inj}"
  echo "=== $agent | $mode | $tasks ${inj:++ $inj}"
  if [[ -n "$inj" ]]; then
    python -m interbolt_agentdojo.run_benchmark \
      --suite workspace --model "$MODEL" \
      --attack important_instructions \
      --policy "$policy" --mode "$mode" --agent-id "$agent" \
      --user-tasks "$tasks" --injection-tasks "$inj" \
      --logdir "$dir"
  else
    python -m interbolt_agentdojo.run_benchmark \
      --suite workspace --model "$MODEL" \
      --policy "$policy" --mode "$mode" --agent-id "$agent" \
      --user-tasks "$tasks" \
      --logdir "$dir"
  fi
}

# ---------------------------------------------------------------------------
# ops-assistant — internal-ops, enforce, v2. The featured agent.
# Cross-domain work: reads the drive, sends email. Carries beat 2.
# ---------------------------------------------------------------------------
run ops-assistant "$V2" enforce user_task_13 injection_task_11 v2   # headline: drive -> external email, blocked
run ops-assistant "$V2" enforce user_task_25 injection_task_11 v2   # second exfil path
run ops-assistant "$V2" enforce user_task_28 "" v2                  # benign: drive read -> internal email, ALLOWED
run ops-assistant "$V2" enforce user_task_33 "" v2                  # benign: file summary -> client email, likely require_approval
run ops-assistant "$V2" enforce user_task_30 "" v2                  # benign: drive read only

# ---------------------------------------------------------------------------
# inbox-triage — internal-ops, enforce, v1. The drift agent.
# Email-focused. Runs the looser policy, so the same attack lands differently.
# ---------------------------------------------------------------------------
run inbox-triage "$V1" enforce user_task_16 injection_task_5 v1     # 2FA code exfil + delete sent email
run inbox-triage "$V1" enforce user_task_14 injection_task_5 v1
run inbox-triage "$V1" enforce user_task_24 "" v1                   # benign: read unread
run inbox-triage "$V1" enforce user_task_22 "" v1                   # benign: find a link in email

# ---------------------------------------------------------------------------
# calendar-bot — scheduling group, enforce, v2.
# Calendar only. Not in internal-ops, so email and drive writes are gated off.
# ---------------------------------------------------------------------------
run calendar-bot "$V2" enforce user_task_6 "" v2                    # read calendar then create event -> require_approval_untrusted
run calendar-bot "$V2" enforce user_task_9 "" v2                    # create event from existing participants
run calendar-bot "$V2" enforce user_task_1 "" v2                    # benign read

# ---------------------------------------------------------------------------
# drive-indexer — no groups, DRY RUN, v2.
# Feeds the review queue. Decisions recorded, nothing enforced.
# No groups means block_non_internal_ops always matches on gated sinks,
# which is the shadowing evidence for Explain.
# ---------------------------------------------------------------------------
run drive-indexer "$V2" dry_run user_task_26 "" v2                  # largest file
run drive-indexer "$V2" dry_run user_task_27 "" v2                  # files shared with an address
run drive-indexer "$V2" dry_run user_task_35 "" v2                  # find and DELETE largest file -> gated write
run drive-indexer "$V2" dry_run user_task_31 "" v2                  # create a new file -> gated write

echo
echo "Done. 16 runs."