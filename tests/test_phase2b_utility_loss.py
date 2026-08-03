"""analysis/phase2b/utility_loss_attribution.py (N2) tests."""

from __future__ import annotations

from analysis.common.casetables import BenignTaskRow
from analysis.phase2b.utility_loss_attribution import classify, compute_rows


def _row(user_task_id: str, utility_a: bool, utility_c: bool, n_blocks: int) -> BenignTaskRow:
    return BenignTaskRow(
        suite="banking",
        policy="strict",
        repeat=0,
        user_task_id=user_task_id,
        utility_a=utility_a,
        utility_c=utility_c,
        n_blocks=n_blocks,
        n_calls=3,
        policy_fingerprint="fp",
    )


def test_classify_policy_caused_loss():
    assert classify(_row("t", utility_a=True, utility_c=False, n_blocks=1)) == "policy_caused_loss"


def test_classify_run_variance():
    assert classify(_row("t", utility_a=True, utility_c=False, n_blocks=0)) == "run_variance"


def test_classify_reverse_variance():
    assert classify(_row("t", utility_a=False, utility_c=True, n_blocks=0)) == "reverse_variance"
    # reverse_variance regardless of blocks on the C run -- over-block artifact is
    # still possible even when the task ultimately passed despite a block.
    assert classify(_row("t", utility_a=False, utility_c=True, n_blocks=2)) == "reverse_variance"


def test_classify_blocked_but_recovered():
    assert classify(_row("t", utility_a=True, utility_c=True, n_blocks=1)) == "blocked_but_recovered"


def test_classify_unaffected():
    assert classify(_row("t", utility_a=True, utility_c=True, n_blocks=0)) == "unaffected"


def test_classify_model_limitation():
    assert classify(_row("t", utility_a=False, utility_c=False, n_blocks=0)) == "model_limitation"
    assert classify(_row("t", utility_a=False, utility_c=False, n_blocks=3)) == "model_limitation"


def test_compute_rows_every_row_classified_and_sorted():
    rows = [
        _row("user_task_1", utility_a=True, utility_c=True, n_blocks=0),
        _row("user_task_0", utility_a=True, utility_c=False, n_blocks=1),
    ]
    result = compute_rows(rows)
    assert [r.user_task_id for r in result] == ["user_task_0", "user_task_1"]  # sorted
    assert result[0].category == "policy_caused_loss"
    assert result[1].category == "unaffected"
    assert all(r.category for r in result)  # never blank/unclassified
