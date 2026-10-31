"""Step definitions for every feature in tests/features.

Steps drive the real Lambda handlers against moto. Only the network edge is faked: probes return
scripted results and DNS is a fixed table, so scenarios are deterministic and need no AWS account.
"""

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from pytest_bdd import given, parsers, then, when

import get_checks
import register_endpoint
import uptime_check
from common.repo import Repo
from common.status import CheckResult
from common.urlguard import UnresolvableHost, endpoint_id, normalize

START = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
DEFAULT_RESULT = CheckResult(status_code=200, latency_ms=50.0)
PUBLIC_ADDRESS = "93.184.215.14"
CONTROL_URLS = ("https://control-1.example.com/healthz.txt", "https://control-2.example.org/")
BLIND_RESULT = CheckResult(status_code=None, latency_ms=None, error="timed out")


@dataclass
class Clock:
    now: datetime = START

    def advance(self):
        self.now += timedelta(minutes=5)


@dataclass
class Context:
    clock: Clock
    monkeypatch: pytest.MonkeyPatch
    scripts: dict = field(default_factory=lambda: defaultdict(deque))
    response: dict | None = None
    summary: dict | None = None
    read_alerts: object = None
    alerts: list = field(default_factory=list)


def _fake_resolver(host):
    if host == "example.com" or host.endswith(".example.com"):
        return [PUBLIC_ADDRESS]
    raise UnresolvableHost(host)


@pytest.fixture
def ctx(tables, sns_topic, monkeypatch):
    clock = Clock()
    context = Context(clock=clock, monkeypatch=monkeypatch)

    def scripted_probe(url, **_):
        queue = context.scripts[url]
        return queue.popleft() if queue else DEFAULT_RESULT

    for module in (register_endpoint, uptime_check):
        monkeypatch.setattr(module, "probe", scripted_probe)
    for module in (register_endpoint, uptime_check, get_checks):
        monkeypatch.setattr(module, "utcnow", lambda: clock.now)
    monkeypatch.setattr(register_endpoint, "resolver", _fake_resolver)
    monkeypatch.delenv("MAX_ENDPOINTS", raising=False)
    return context


def _respond(ctx, lambda_response):
    ctx.response = {
        "status": lambda_response["statusCode"],
        "body": json.loads(lambda_response["body"]),
    }


def _register(ctx, url):
    event = {"version": "2.0", "body": json.dumps({"url": url}), "isBase64Encoded": False}
    _respond(ctx, register_endpoint.lambda_handler(event, None))
    ctx.clock.advance()


def _status_event(url):
    return {"version": "2.0", "queryStringParameters": None if url is None else {"url": url}}


def _queue(ctx, url, count, code, ms):
    result = CheckResult(status_code=code, latency_ms=float(ms))
    ctx.scripts[normalize(url)].extend([result] * count)


def _collect_alerts(ctx):
    if ctx.read_alerts:
        ctx.alerts.extend(ctx.read_alerts())
    return ctx.alerts


# ---- Given -------------------------------------------------------------------------------------


@given("a clean monitoring service")
def _clean_service(ctx):
    assert Repo().count_endpoints() == 0


@given("alert emails are captured")
def _capture_alerts(ctx, alerts):
    ctx.read_alerts = alerts


@given("no alert topic is configured")
def _no_topic(ctx):
    ctx.monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)


@given(parsers.parse("the monitoring limit is {n:d} endpoint"))
def _limit(ctx, n):
    ctx.monkeypatch.setenv("MAX_ENDPOINTS", str(n))


@given("control URLs are configured")
def _controls_configured(ctx):
    ctx.monkeypatch.setenv("CONTROL_URLS", ",".join(CONTROL_URLS))


@given(parsers.parse("the checker can reach the internet for {n:d} check"))
@given(parsers.parse("the checker can reach the internet for {n:d} checks"))
def _controls_reachable(ctx, n):
    for url in CONTROL_URLS:
        ctx.scripts[url].extend([DEFAULT_RESULT] * n)


@given(parsers.parse("the checker cannot reach the internet for {n:d} check"))
@given(parsers.parse("the checker cannot reach the internet for {n:d} checks"))
def _controls_blind(ctx, n):
    for url in CONTROL_URLS:
        ctx.scripts[url].extend([BLIND_RESULT] * n)


@given(parsers.parse('"{url}" answers with status {code:d} in {ms:d} ms'))
def _answers(ctx, url, code, ms):
    _queue(ctx, url, 1, code, ms)


@given(parsers.parse('the next check of "{url}" answers with status {code:d} in {ms:d} ms'))
def _next_check(ctx, url, code, ms):
    _queue(ctx, url, 1, code, ms)


@given(parsers.parse('the next {n:d} checks of "{url}" answer with status {code:d} in {ms:d} ms'))
def _next_checks(ctx, n, url, code, ms):
    _queue(ctx, url, n, code, ms)


@given(parsers.parse('"{url}" is already monitored'))
def _already_monitored(ctx, url):
    _register(ctx, url)
    assert ctx.response["status"] in (200, 201), ctx.response


@given(parsers.parse('"{url}" is disabled'))
def _disabled(ctx, url):
    Repo().update_endpoint(endpoint_id(normalize(url)), enabled=False)


# ---- When --------------------------------------------------------------------------------------


@when(parsers.parse('I register "{url}"'))
def _i_register(ctx, url):
    _register(ctx, url)


@when("the scheduled check runs")
def _check_runs(ctx):
    ctx.summary = uptime_check.lambda_handler({}, None)
    ctx.clock.advance()


@when(parsers.parse("the scheduled check runs {n:d} times"))
def _check_runs_n(ctx, n):
    for _ in range(n):
        _check_runs(ctx)


@when(parsers.parse('I ask for the status of "{url}"'))
def _ask_status(ctx, url):
    _respond(ctx, get_checks.lambda_handler(_status_event(url), None))


@when("I ask for the status without a url")
def _ask_status_without_url(ctx):
    _respond(ctx, get_checks.lambda_handler(_status_event(None), None))


# ---- Then --------------------------------------------------------------------------------------


@then(parsers.parse("the response status is {code:d}"))
def _response_status(ctx, code):
    assert ctx.response["status"] == code, ctx.response


@then("the error message is not empty")
def _error_message(ctx):
    assert ctx.response["body"].get("message"), ctx.response


@then(parsers.parse("the number of monitored endpoints is {n:d}"))
def _endpoint_count(ctx, n):
    assert Repo().count_endpoints() == n


@then(parsers.parse('the dashboard shows status "{status}"'))
def _dashboard_status(ctx, status):
    assert ctx.response["body"]["status"] == status, ctx.response


@then(parsers.parse("the dashboard lists {n:d} recent check"))
@then(parsers.parse("the dashboard lists {n:d} recent checks"))
def _recent_checks(ctx, n):
    assert len(ctx.response["body"]["recent_latencies"]) == n, ctx.response


@then(parsers.parse('the latest recent check is "{status}"'))
def _latest_check(ctx, status):
    assert ctx.response["body"]["recent_latencies"][-1]["status"] == status


@then(parsers.parse("uptime is {pct:f} percent"))
def _uptime(ctx, pct):
    assert ctx.response["body"]["uptime_30d"] == pytest.approx(pct, abs=0.01)


@then(parsers.parse("the checker reports {n:d} endpoints checked"))
def _checked(ctx, n):
    assert ctx.summary["checked"] == n, ctx.summary


def _dashboard(ctx, url):
    response = get_checks.lambda_handler(_status_event(url), None)
    assert response["statusCode"] == 200, response
    return json.loads(response["body"])


@then(parsers.parse('the dashboard for "{url}" shows status "{status}"'))
def _dashboard_for_status(ctx, url, status):
    assert _dashboard(ctx, url)["status"] == status


@then(parsers.parse('the dashboard for "{url}" shows a last alert time'))
def _dashboard_last_alert(ctx, url):
    assert _dashboard(ctx, url)["last_alert_sent"]


@then(parsers.parse("the number of alerts sent is {n:d}"))
def _alert_count(ctx, n):
    assert len(_collect_alerts(ctx)) == n, ctx.alerts


@then(parsers.parse('alert {i:d} has a subject starting "{prefix}"'))
def _alert_subject(ctx, i, prefix):
    assert _collect_alerts(ctx)[i - 1]["Subject"].startswith(prefix), ctx.alerts


def _incidents(url):
    return Repo().incidents(endpoint_id(normalize(url)))


@then(parsers.parse('"{url}" has {n:d} incidents'))
def _incident_count(ctx, url, n):
    assert len(_incidents(url)) == n


@then(parsers.parse('the failure count of "{url}" is {n:d}'))
def _failure_count(ctx, url, n):
    assert Repo().get_endpoint(endpoint_id(normalize(url)))["consecutive_failures"] == n


@then(parsers.parse('"{url}" has {n:d} open incident'))
def _open_incidents(ctx, url, n):
    assert len([i for i in _incidents(url) if not i["resolved"]]) == n


@then(parsers.parse('"{url}" has {n:d} resolved incident'))
def _resolved_incidents(ctx, url, n):
    assert len([i for i in _incidents(url) if i["resolved"]]) == n
