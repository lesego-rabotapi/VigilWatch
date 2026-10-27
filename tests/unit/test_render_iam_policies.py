"""Rendering the IAM policies must be cheap to repeat and must never break test collection."""

import json

import pytest

import render_iam_policies

pytestmark = pytest.mark.req("VW-016")

POLICY = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["a:B"]}]}


def console_output(policies: dict) -> str:
    """What `terraform console` prints for jsonencode(local.function_policies)."""
    return json.dumps(json.dumps({k: json.dumps(v) for k, v in policies.items()})) + "\n"


@pytest.fixture
def terraform(monkeypatch):
    """A scripted terraform: a list of results per subcommand, recorded calls."""
    calls, script = [], {}

    def fake(*args, stdin=None):
        calls.append(args[0])
        outcomes = script.get(args[0], [""])
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(render_iam_policies, "_terraform", fake)
    render_iam_policies.clear_cache()
    yield calls, script
    render_iam_policies.clear_cache()


def test_policies_are_rendered_once_and_reused(terraform):
    calls, script = terraform
    script["console"] = [console_output({"get_checks": POLICY})]
    first = render_iam_policies.render()
    second = render_iam_policies.render()
    assert first == second == {"get_checks": POLICY}
    assert calls.count("console") == 1


def test_callers_cannot_change_the_cached_copy(terraform):
    _, script = terraform
    script["console"] = [console_output({"get_checks": POLICY})]
    render_iam_policies.render()["get_checks"]["Statement"].clear()
    assert render_iam_policies.render()["get_checks"] == POLICY


def test_a_failing_console_reinitialises_once_then_retries(terraform):
    """A stale or half-initialised .terraform directory must not be trusted."""
    calls, script = terraform
    script["console"] = [RuntimeError("provider missing"), console_output({"x": POLICY})]
    assert render_iam_policies.render() == {"x": POLICY}
    assert calls == ["console", "init", "console"]


@pytest.mark.negative
def test_a_console_that_keeps_failing_raises_after_one_retry(terraform):
    calls, script = terraform
    script["console"] = [RuntimeError("offline")]
    with pytest.raises(RuntimeError, match="offline"):
        render_iam_policies.render()
    assert calls == ["console", "init", "console"]


@pytest.mark.negative
def test_collection_gets_an_error_value_instead_of_an_exception(terraform):
    """Parametrising tests calls this at import time: raising there would abort the whole run."""
    _, script = terraform
    script["console"] = [RuntimeError("offline")]
    policies, error = render_iam_policies.render_or_error()
    assert policies is None
    assert "offline" in error


def test_collection_gets_the_policies_when_terraform_works(terraform):
    _, script = terraform
    script["console"] = [console_output({"x": POLICY})]
    assert render_iam_policies.render_or_error() == ({"x": POLICY}, None)
