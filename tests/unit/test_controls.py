"""Connectivity checks: is the checker itself able to reach the internet?"""

import pytest

from common.controls import ControlReport, check_controls
from common.settings import Settings, SettingsError
from common.status import CheckResult

pytestmark = pytest.mark.req("VW-022")

OK = CheckResult(status_code=200, latency_ms=30.0)
REDIRECT = CheckResult(status_code=301, latency_ms=30.0)
SERVER_ERROR = CheckResult(status_code=503, latency_ms=30.0)
TIMEOUT = CheckResult(status_code=None, latency_ms=None, error="timed out")


def scripted(outcomes):
    return lambda url, **_: outcomes[url]


def test_no_controls_configured_means_the_feature_is_off_not_failing():
    report = check_controls((), scripted({}))
    assert report == ControlReport(checked=0, ok=0, healthy=True)


@pytest.mark.parametrize(
    "outcomes, healthy",
    [
        ({"a": OK}, True),
        ({"a": OK, "b": OK}, True),
        ({"a": TIMEOUT, "b": OK}, True),
        ({"a": SERVER_ERROR, "b": OK}, True),
        ({"a": TIMEOUT, "b": TIMEOUT}, False),
        ({"a": SERVER_ERROR, "b": TIMEOUT}, False),
        ({"a": REDIRECT}, True),
    ],
)
def test_the_checker_is_connected_if_any_control_answers_properly(outcomes, healthy):
    report = check_controls(tuple(outcomes), scripted(outcomes))
    assert report.healthy is healthy
    assert report.checked == len(outcomes)


@pytest.mark.negative
def test_a_probe_function_that_raises_counts_as_a_failed_control():
    def exploding(url, **_):
        raise RuntimeError("boom")

    report = check_controls(("a", "b"), exploding)
    assert report.healthy is False and report.ok == 0


def test_every_control_is_probed_once_with_the_timeout():
    seen = []

    def recording(url, **kwargs):
        seen.append((url, kwargs.get("timeout")))
        return OK

    check_controls(("a", "b", "c"), recording, timeout=2.5)
    assert sorted(seen) == [("a", 2.5), ("b", 2.5), ("c", 2.5)]


def test_control_urls_come_from_the_environment_as_a_clean_tuple(monkeypatch):
    monkeypatch.setenv(
        "CONTROL_URLS", " https://a.example.com/healthz.txt , ,https://b.example.org/ "
    )
    assert Settings.from_env().control_urls == (
        "https://a.example.com/healthz.txt",
        "https://b.example.org/",
    )


def test_control_urls_default_to_none(monkeypatch):
    monkeypatch.delenv("CONTROL_URLS", raising=False)
    assert Settings.from_env().control_urls == ()
    monkeypatch.setenv("CONTROL_URLS", "")
    assert Settings.from_env().control_urls == ()


@pytest.mark.negative
@pytest.mark.parametrize(
    "value",
    [
        "ftp://a.example.com/",
        "not a url",
        "https://ok.example.com/,javascript:alert(1)",
        ",".join(["https://a.example.com/"] * 6),
    ],
)
def test_bad_control_urls_are_refused_naming_the_variable(monkeypatch, value):
    monkeypatch.setenv("CONTROL_URLS", value)
    with pytest.raises(SettingsError, match="CONTROL_URLS"):
        Settings.from_env()
