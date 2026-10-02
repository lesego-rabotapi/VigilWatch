import pytest

from common.status import DEGRADED, DOWN, UP, CheckResult, classify, counts_as_up


@pytest.mark.parametrize(
    "result, expected",
    [
        (CheckResult(status_code=200, latency_ms=120.0), UP),
        (CheckResult(status_code=200, latency_ms=999.9), UP),
        (CheckResult(status_code=200, latency_ms=1000.0), DEGRADED),
        (CheckResult(status_code=200, latency_ms=4500.0), DEGRADED),
        (CheckResult(status_code=500, latency_ms=50.0), DOWN),
        (CheckResult(status_code=404, latency_ms=50.0), DOWN),
        # Redirects are not followed, so a 301 is a mismatch against 200.
        (CheckResult(status_code=301, latency_ms=50.0), DOWN),
        (CheckResult(status_code=None, latency_ms=None, error="timeout"), DOWN),
        (CheckResult(status_code=200, latency_ms=10.0, error="boom"), DOWN),
    ],
)
def test_classify_default_thresholds(result, expected):
    assert classify(result, expected_status=200, degraded_ms=1000) == expected


def test_expected_status_is_respected():
    assert classify(CheckResult(status_code=204, latency_ms=10.0), expected_status=204) == UP
    assert classify(CheckResult(status_code=200, latency_ms=10.0), expected_status=204) == DOWN


def test_degraded_threshold_is_configurable():
    r = CheckResult(status_code=200, latency_ms=300.0)
    assert classify(r, degraded_ms=250) == DEGRADED
    assert classify(r, degraded_ms=301) == UP


@pytest.mark.parametrize("status, up", [(UP, True), (DEGRADED, True), (DOWN, False)])
def test_counts_as_up(status, up):
    assert counts_as_up(status) is up
