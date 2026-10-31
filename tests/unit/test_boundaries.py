"""Boundary-value, equivalence-partition and hostile-input tests for the pure input handling.

For each bounded input: below the minimum, the minimum, the maximum and above the maximum.
"""

import pytest

from common.http import BadRequest, json_body
from common.settings import Settings, SettingsError
from common.urlguard import MAX_URL_LENGTH, UnsafeURL, normalize

pytestmark = pytest.mark.req("VW-002", "VW-003", "VW-005", "VW-009")

BASE = "https://example.com/"


def url_of_length(n):
    return BASE + "a" * (n - len(BASE))


@pytest.mark.boundary
@pytest.mark.parametrize(
    "length, accepted",
    [(1, False), (2047, True), (MAX_URL_LENGTH, True), (MAX_URL_LENGTH + 1, False)],
)
def test_url_length_boundary(length, accepted):
    url = url_of_length(length) if length > len(BASE) else "x" * length
    if accepted:
        assert normalize(url).startswith("https://example.com/")
    else:
        with pytest.raises(UnsafeURL):
            normalize(url)


@pytest.mark.boundary
@pytest.mark.parametrize(
    "port, accepted",
    [(0, False), (1, True), (80, True), (65535, True), (65536, False), (-1, False)],
)
def test_port_boundary(port, accepted):
    url = f"https://example.com:{port}/"
    if accepted:
        assert normalize(url)
    else:
        with pytest.raises(UnsafeURL):
            normalize(url)


@pytest.mark.negative
@pytest.mark.parametrize("raw", ["", " ", "\t\n", None, 42, ["https://example.com/"], {"a": 1}])
def test_blank_or_non_string_urls_are_rejected(raw):
    with pytest.raises(UnsafeURL):
        normalize(raw)


@pytest.mark.negative
@pytest.mark.security
@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com/a\r\nX-Injected: 1",
        "https://example.com/a\nb",
        "https://exam\tple.com/",
    ],
)
def test_control_characters_never_survive_normalisation(raw):
    cleaned = normalize(raw)
    assert not any(ch in cleaned for ch in "\r\n\t")


@pytest.mark.security
def test_a_megabyte_url_is_refused_without_being_processed():
    with pytest.raises(UnsafeURL):
        normalize("https://example.com/" + "a" * 1_000_000)


@pytest.mark.boundary
@pytest.mark.parametrize(
    "threshold, valid", [(0, False), (1, True), (2, True), (10, True), (11, False), (-3, False)]
)
def test_failure_threshold_boundary(monkeypatch, threshold, valid):
    monkeypatch.setenv("FAILURE_THRESHOLD", str(threshold))
    if valid:
        assert Settings.from_env().failure_threshold == threshold
    else:
        with pytest.raises(SettingsError, match="FAILURE_THRESHOLD"):
            Settings.from_env()


@pytest.mark.boundary
@pytest.mark.parametrize("ms, valid", [(0, False), (1, True), (1000, True), (-5, False)])
def test_degraded_threshold_boundary(monkeypatch, ms, valid):
    monkeypatch.setenv("DEGRADED_MS", str(ms))
    if valid:
        assert Settings.from_env().degraded_ms == ms
    else:
        with pytest.raises(SettingsError, match="DEGRADED_MS"):
            Settings.from_env()


@pytest.mark.boundary
@pytest.mark.parametrize("seconds, valid", [(0, False), (0.5, True), (30, True), (31, False)])
def test_probe_timeout_boundary(monkeypatch, seconds, valid):
    monkeypatch.setenv("PROBE_TIMEOUT_S", str(seconds))
    if valid:
        assert Settings.from_env().timeout_s == seconds
    else:
        with pytest.raises(SettingsError, match="PROBE_TIMEOUT_S"):
            Settings.from_env()


@pytest.mark.negative
@pytest.mark.parametrize("name", ["FAILURE_THRESHOLD", "DEGRADED_MS", "PROBE_TIMEOUT_S"])
@pytest.mark.parametrize("value", ["abc", "", "1.5.2", "nan", "inf"])
def test_non_numeric_settings_name_the_offending_variable(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(SettingsError, match=name):
        Settings.from_env()


def test_defaults_are_valid_when_nothing_is_set(monkeypatch):
    for name in ("FAILURE_THRESHOLD", "DEGRADED_MS", "PROBE_TIMEOUT_S", "MAX_WORKERS"):
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env() == Settings()


@pytest.mark.negative
@pytest.mark.parametrize(
    "event",
    [
        {},
        {"body": None},
        {"body": ""},
        {"body": "   "},
        {"body": "{"},
        {"body": "null"},
        {"body": "42"},
        {"body": '"text"'},
        {"body": "[1, 2]"},
        {"body": "\xff\xfe", "isBase64Encoded": True},
        {"body": "!!!not-base64!!!", "isBase64Encoded": True},
    ],
)
def test_malformed_bodies_are_bad_requests(event):
    with pytest.raises(BadRequest):
        json_body(event)


@pytest.mark.negative
@pytest.mark.security
@pytest.mark.parametrize("depth", [1_000, 100_000])
def test_pathologically_nested_json_is_a_bad_request_not_a_crash(depth):
    event = {"body": "[" * depth + "]" * depth}
    with pytest.raises(BadRequest):
        json_body(event)


@pytest.mark.boundary
@pytest.mark.parametrize(
    "value, valid", [(0, False), (1, True), (2, True), (10, True), (11, False), (-1, False)]
)
def test_recovery_threshold_boundary(monkeypatch, value, valid):
    monkeypatch.setenv("RECOVERY_THRESHOLD", str(value))
    if valid:
        assert Settings.from_env().recovery_threshold == value
    else:
        with pytest.raises(SettingsError, match="RECOVERY_THRESHOLD"):
            Settings.from_env()


@pytest.mark.boundary
@pytest.mark.parametrize(
    "value, valid", [(-1, False), (0, True), (1, True), (1440, True), (1441, False)]
)
def test_reminder_minutes_boundary(monkeypatch, value, valid):
    monkeypatch.setenv("REMINDER_MINUTES", str(value))
    if valid:
        assert Settings.from_env().reminder_minutes == value
    else:
        with pytest.raises(SettingsError, match="REMINDER_MINUTES"):
            Settings.from_env()


def test_alert_polish_is_off_by_default(monkeypatch):
    monkeypatch.delenv("RECOVERY_THRESHOLD", raising=False)
    monkeypatch.delenv("REMINDER_MINUTES", raising=False)
    settings = Settings.from_env()
    assert (settings.recovery_threshold, settings.reminder_minutes) == (1, 0)


@pytest.mark.negative
@pytest.mark.parametrize("value", ["yes", "1", "", "TRUE ", "enabled"])
def test_metrics_enabled_accepts_only_true_or_false(monkeypatch, value):
    monkeypatch.setenv("METRICS_ENABLED", value)
    with pytest.raises(SettingsError, match="METRICS_ENABLED"):
        Settings.from_env()


@pytest.mark.parametrize("value, expected", [("true", True), ("false", False), ("False", False)])
def test_metrics_enabled_values(monkeypatch, value, expected):
    monkeypatch.setenv("METRICS_ENABLED", value)
    assert Settings.from_env().metrics_enabled is expected


def test_metrics_are_on_by_default(monkeypatch):
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    assert Settings.from_env().metrics_enabled is True
