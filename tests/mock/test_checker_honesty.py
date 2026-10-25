"""The checker must tell 'the website is down' apart from 'I cannot see the internet'."""

import json
from datetime import UTC, datetime, timedelta

import pytest

import uptime_check
from common.repo import Repo, iso
from common.status import CheckResult

pytestmark = pytest.mark.req("VW-022")

T0 = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
A, B = "https://a.example.com/", "https://b.example.com/"
CONTROL_1, CONTROL_2 = "https://control-1.example.com/healthz.txt", "https://control-2.example.org/"

OK = CheckResult(status_code=200, latency_ms=50.0)
FAIL = CheckResult(status_code=503, latency_ms=40.0)
TIMEOUT = CheckResult(status_code=None, latency_ms=None, error="timed out")


@pytest.fixture
def world(tables, monkeypatch):
    """Two monitored endpoints, scripted network results, a recorded probe log and a clock."""
    state = {"now": T0, "script": {}, "probed": []}
    repo = Repo()
    repo.put_endpoint("a", A, T0)
    repo.put_endpoint("b", B, T0)
    monkeypatch.setenv("CONTROL_URLS", f"{CONTROL_1},{CONTROL_2}")

    def scripted(url, **_):
        state["probed"].append(url)
        outcomes = state["script"].get(url, [OK])
        return outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]

    monkeypatch.setattr(uptime_check, "probe", scripted)
    monkeypatch.setattr(uptime_check, "utcnow", lambda: state["now"])

    def run(times=1):
        out = None
        for _ in range(times):
            state["probed"].clear()
            out = uptime_check.lambda_handler({}, None)
            state["now"] += timedelta(minutes=5)
        return out

    def script(url, *outcomes):
        state["script"][url] = list(outcomes)

    state.update(repo=repo, run=run, script=state["script"], set=script)
    return state


def blind(world):
    world["set"](CONTROL_1, TIMEOUT)
    world["set"](CONTROL_2, TIMEOUT)


def emf(capsys):
    lines = [x for x in capsys.readouterr().out.splitlines() if x.startswith("{") and "_aws" in x]
    return json.loads(lines[-1])


@pytest.mark.negative
def test_a_blind_cycle_is_inconclusive_and_nothing_is_blamed_on_the_targets(world):
    world["set"](A, FAIL)
    world["set"](B, FAIL)
    blind(world)

    summary = world["run"](times=3)

    assert summary == {
        "checked": 2,
        "up": 0,
        "degraded": 0,
        "down": 0,
        "inconclusive": 2,
        "errors": 0,
    }
    repo = world["repo"]
    for endpoint_id in ("a", "b"):
        item = repo.get_endpoint(endpoint_id)
        assert item["status"] == "INCONCLUSIVE"
        assert item["consecutive_failures"] == 0
        assert repo.incidents(endpoint_id) == []
        assert all(c["status"] == "INCONCLUSIVE" for c in repo.recent_checks(endpoint_id))
    assert repo.uptime_30d("a", T0) is None, "inconclusive checks must not count towards uptime"


def test_a_real_outage_is_still_an_outage_when_the_connectivity_checks_pass(world):
    world["set"](A, FAIL)
    world["set"](B, FAIL)
    summary = world["run"](times=2)
    assert summary["down"] == 2 and summary["inconclusive"] == 0
    assert len(world["repo"].incidents("a")) == 1


def test_any_target_that_answers_proves_connectivity_so_controls_are_not_probed(world):
    world["set"](A, OK)
    world["set"](B, FAIL)
    blind(world)  # would fail if asked, but nobody should ask

    summary = world["run"]()

    assert (summary["up"], summary["down"], summary["inconclusive"]) == (1, 1, 0)
    assert CONTROL_1 not in world["probed"] and CONTROL_2 not in world["probed"]


def test_controls_are_not_probed_when_every_target_is_healthy(world):
    world["run"]()
    assert sorted(world["probed"]) == [A, B]


def test_without_control_urls_the_feature_is_off_and_down_means_down(world, monkeypatch):
    monkeypatch.delenv("CONTROL_URLS")
    world["set"](A, FAIL)
    world["set"](B, FAIL)
    summary = world["run"]()
    assert (summary["down"], summary["inconclusive"]) == (2, 0)


def test_a_blind_cycle_neither_counts_nor_erases_earlier_failures(world):
    world["set"](A, FAIL)
    world["set"](B, FAIL)
    repo = world["repo"]

    world["run"]()  # controls healthy: first genuine failure
    assert repo.get_endpoint("a")["consecutive_failures"] == 1

    blind(world)
    world["run"]()  # blind: nothing changes
    assert repo.get_endpoint("a")["consecutive_failures"] == 1
    assert repo.get_endpoint("a")["status"] == "INCONCLUSIVE"

    world["set"](CONTROL_1, OK)
    world["set"](CONTROL_2, OK)
    world["run"]()  # second genuine failure crosses the threshold
    assert repo.get_endpoint("a")["consecutive_failures"] == 2
    assert len(repo.incidents("a")) == 1


def test_an_open_incident_survives_a_blind_cycle_and_closes_on_recovery(world):
    world["set"](A, FAIL, FAIL, FAIL, OK)
    world["set"](B, OK)
    repo = world["repo"]
    # B stays up, so A's failures are judged with B's success proving connectivity
    world["run"](times=2)
    assert len(repo.incidents("a")) == 1 and not repo.incidents("a")[0]["resolved"]

    world["set"](B, FAIL)  # now nothing answers: only the controls can tell us why
    blind(world)
    world["run"]()
    assert not repo.incidents("a")[0]["resolved"], "a blind cycle must not close the incident"
    assert repo.get_endpoint("a")["status"] == "INCONCLUSIVE"

    world["set"](B, OK)
    world["run"]()  # A answers again: genuine recovery
    assert repo.incidents("a")[0]["resolved"] is True


def test_every_completed_run_writes_a_heartbeat(world):
    world["run"]()
    beat = world["repo"].heartbeat()
    assert beat["last_run"] == iso(T0)
    assert (beat["checked"], beat["up"], beat["down"], beat["inconclusive"]) == (2, 2, 0, 0)
    assert beat["controls"] == "not_needed"


@pytest.mark.parametrize(
    "setup, expected",
    [
        ("healthy_controls", "healthy"),
        ("blind", "failed"),
    ],
)
def test_the_heartbeat_says_what_the_connectivity_checks_found(world, setup, expected):
    world["set"](A, FAIL)
    world["set"](B, FAIL)
    if setup == "blind":
        blind(world)
    world["run"]()
    assert world["repo"].heartbeat()["controls"] == expected


def test_the_heartbeat_says_disabled_when_no_controls_are_configured(world, monkeypatch):
    monkeypatch.delenv("CONTROL_URLS")
    world["run"]()
    assert world["repo"].heartbeat()["controls"] == "disabled"


def test_the_heartbeat_is_written_even_when_an_endpoint_fails_internally(world, monkeypatch):
    real = Repo.record_check

    def flaky(self, endpoint_id, *args, **kwargs):
        if endpoint_id == "a":
            raise RuntimeError("dynamodb exploded")
        return real(self, endpoint_id, *args, **kwargs)

    monkeypatch.setattr(Repo, "record_check", flaky)
    with pytest.raises(RuntimeError, match="1 of 2"):
        world["run"]()
    assert world["repo"].heartbeat()["errors"] == 1


def test_metrics_report_blindness_without_a_per_endpoint_dimension(world, capsys):
    world["set"](A, FAIL)
    world["set"](B, FAIL)
    blind(world)
    world["run"]()
    record = emf(capsys)
    names = {m["Name"] for m in record["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert {"ControlProbeFailed", "EndpointsInconclusive", "RunsCompleted"} <= names
    assert record["ControlProbeFailed"] == 1
    assert record["EndpointsInconclusive"] == 2
    assert record["RunsCompleted"] == 1
    assert record["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [["Service"]]


def test_the_blind_metric_is_zero_when_connectivity_was_checked_and_fine(world, capsys):
    world["set"](A, FAIL)
    world["set"](B, FAIL)
    world["run"]()
    assert emf(capsys)["ControlProbeFailed"] == 0


def test_the_blind_metric_is_absent_when_connectivity_never_needed_checking(world, capsys):
    world["run"]()
    names = {m["Name"] for m in emf(capsys)["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert "ControlProbeFailed" not in names
    assert "RunsCompleted" in names


def test_metrics_can_be_switched_off_without_losing_the_heartbeat(world, capsys, monkeypatch):
    """A second environment would exceed the 10 free custom metrics, so it can stay silent."""
    monkeypatch.setenv("METRICS_ENABLED", "false")
    world["run"]()
    assert "_aws" not in capsys.readouterr().out
    assert world["repo"].heartbeat()["checked"] == 2
