"""analysis/phase1/checks.py tests.

check_i1/i2/i4/i8/i10 depend only on (Quartet, AttackedCaseRow) values, not on
filesystem contents, so they're exercised with hand-built dataclass instances --
no need to reconstruct a full run-dir fixture for logic that doesn't touch disk.
`RunRecord` requires a `manifest` dict even for these dummy instances since
`Quartet`/`checks.py` never read it directly here, but the dataclass itself is
frozen and requires every field.
"""

from __future__ import annotations

from pathlib import Path

from analysis.common.casetables import AttackedCaseRow, MissingCase, Quartet
from analysis.common.discovery import RunRecord
from analysis.phase1.checks import check_i1, check_i2, check_i4, check_i8, check_i10

BENCHMARK_VERSION = "v1.2.2"


def _dummy_run_record(role: str) -> RunRecord:
    return RunRecord(
        repeat_dir=Path("/dummy"),
        manifest={},
        suite="banking",
        attack=None,
        benchmark_version=BENCHMARK_VERSION,
        model="test-model",
        policy=None,
        role=role,
        expected_dir_name="",
        actual_parent_dir_name="",
        path_mismatch=False,
        pipeline_name=None,
    )


def _quartet(policy: str, repeat: int) -> Quartet:
    a = _dummy_run_record("A_ceiling")
    b = _dummy_run_record("B_asr_model")
    c = _dummy_run_record("C_utility")
    d = _dummy_run_record("D_asr_system")
    return Quartet(suite="banking", policy=policy, repeat=repeat, a=a, b=b, c=c, d=d)


def _row(policy: str, repeat: int, user_task_id: str, injection_task_id: str, bucket: str, security_b: bool = False) -> AttackedCaseRow:
    return AttackedCaseRow(
        suite="banking",
        policy=policy,
        repeat=repeat,
        user_task_id=user_task_id,
        injection_task_id=injection_task_id,
        security_b=security_b,
        security_d=False,
        reached_sink_b=False,
        blocked_d=False,
        bucket=bucket,
        n_blocks=0,
        n_calls=0,
        run_id_b="b",
        run_id_d="d",
        policy_fingerprint="",
    )


# ---------------------------------------------------------------------------
# I1: bucket_total vs suite-derived case count
# ---------------------------------------------------------------------------


def test_check_i1_fails_when_case_count_short():
    q = _quartet("strict", 0)
    # Real banking suite: 16 user tasks x 9 injection tasks = 144. Only 2 rows here.
    rows = [_row("strict", 0, "user_task_0", "injection_task_0", "model_refused")]
    results = check_i1([q], rows)
    assert len(results) == 1
    assert results[0].status == "FAIL"
    assert results[0].computed == "1"
    assert results[0].expected == "144"


# ---------------------------------------------------------------------------
# I2: asr_model decomposition self-consistency
# ---------------------------------------------------------------------------


def test_check_i2_passes_when_decomposition_matches():
    q = _quartet("strict", 0)
    rows = [
        _row("strict", 0, "user_task_0", "injection_task_0", "interbolt_blocked", security_b=True),
        _row("strict", 0, "user_task_1", "injection_task_0", "model_refused", security_b=False),
    ]
    results = check_i2([q], rows)
    assert results[0].status == "PASS"
    assert results[0].computed == "1"


def test_check_i2_fails_when_security_b_and_bucket_disagree():
    q = _quartet("strict", 0)
    # security_b True but bucket is model_refused (which should imply security_b False)
    # -- an internally inconsistent row, exactly what I2 exists to catch.
    rows = [_row("strict", 0, "user_task_0", "injection_task_0", "model_refused", security_b=True)]
    results = check_i2([q], rows)
    assert results[0].status == "FAIL"
    assert results[0].computed == "1"
    assert results[0].expected == "0"


# ---------------------------------------------------------------------------
# I4: policy-invariant buckets, at case-identity level
# ---------------------------------------------------------------------------


def test_check_i4_passes_when_case_sets_identical():
    strict = _quartet("strict", 0)
    targeted = _quartet("targeted", 0)
    rows = [
        _row("strict", 0, "user_task_0", "injection_task_0", "model_refused"),
        _row("targeted", 0, "user_task_0", "injection_task_0", "model_refused"),
    ]
    results = check_i4([strict, targeted], rows)
    model_refused_results = [r for r in results if "model_refused" in r.detail]
    assert model_refused_results and all(r.status == "PASS" for r in model_refused_results)


def test_check_i4_fails_when_case_sets_differ():
    strict = _quartet("strict", 0)
    targeted = _quartet("targeted", 0)
    # Same case classified model_refused under strict but not under targeted --
    # violates policy-invariance (model_refused is a B-only property, shared B
    # run, so this should never happen from real data; check_i4 must still catch
    # it if it ever does).
    rows = [
        _row("strict", 0, "user_task_0", "injection_task_0", "model_refused"),
        _row("targeted", 0, "user_task_0", "injection_task_0", "out_of_scope"),
    ]
    results = check_i4([strict, targeted], rows)
    model_refused_results = [r for r in results if "bucket=model_refused" in r.detail]
    assert model_refused_results[0].status == "FAIL"


def test_check_i4_info_when_only_one_policy_present():
    q = _quartet("strict", 0)
    rows = [_row("strict", 0, "user_task_0", "injection_task_0", "model_refused")]
    results = check_i4([q], rows)
    assert all(r.status == "INFO" for r in results)


# ---------------------------------------------------------------------------
# I8: gated-sink case union, per policy and across policies
# ---------------------------------------------------------------------------


def test_check_i8_unions_across_policies_and_repeats():
    rows = [
        _row("strict", 0, "user_task_0", "injection_task_0", "interbolt_blocked"),
        _row("strict", 1, "user_task_1", "injection_task_0", "attack_succeeded_defended"),
        _row("targeted", 0, "user_task_0", "injection_task_0", "interbolt_blocked"),  # same case as strict/repeat0
        _row("targeted", 0, "user_task_2", "injection_task_1", "attack_failed_unattributed"),
    ]
    results = check_i8(rows)
    by_policy = {r.policy: int(r.computed) for r in results if r.policy}
    assert by_policy["strict"] == 2  # user_task_0/inj_0, user_task_1/inj_0
    assert by_policy["targeted"] == 2  # user_task_0/inj_0, user_task_2/inj_1
    suite_row = next(r for r in results if r.policy == "")
    assert int(suite_row.computed) == 3  # union: {(0,0), (1,0), (2,1)}


# ---------------------------------------------------------------------------
# I10: missing-from-D surfaced as WARN with a count
# ---------------------------------------------------------------------------


def test_check_i10_warns_on_missing_cases():
    q = _quartet("strict", 0)
    missing = [
        MissingCase(suite="banking", policy="strict", repeat=0, user_task_id="user_task_1", injection_task_id="injection_task_0", from_role="D")
    ]
    results = check_i10([q], missing)
    assert results[0].status == "WARN"
    assert results[0].computed == "1"


def test_check_i10_passes_when_nothing_missing():
    q = _quartet("strict", 0)
    results = check_i10([q], [])
    assert results[0].status == "PASS"
    assert results[0].computed == "0"
