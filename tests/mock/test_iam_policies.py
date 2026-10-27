"""The IAM policies Terraform will create must be enough for the code, and no more than it needs.

The policy documents are rendered from the real Terraform module (no AWS account needed), attached
to IAM users in moto, and each handler is run with that user's credentials while moto enforces them.
A missing action fails here instead of on the first real invocation.

What this proves and what it does not (evidence tag MOCK):
  * actions are enforced; resources are not. moto evaluates every DynamoDB, SNS and SQS request
    against resource "*", so the rendered resource ARNs are replaced by "*" for this test. Resource
    scoping is asserted by `terraform test` instead (no wildcards, ARNs built from the inputs).
  * AWS authorises a transaction through its item-level actions, while moto looks for a
    dynamodb:TransactWriteItems permission, so that action is granted wherever the item-level
    actions it is made of are.
"""

import copy
import importlib.util
import json
import os
from datetime import UTC, datetime

import boto3
import pytest

import get_checks
import register_endpoint
import render_iam_policies
import uptime_check
from common import aws as aws_clients
from common.repo import Repo
from common.status import CheckResult
from common.urlguard import endpoint_id

pytestmark = pytest.mark.req("VW-016")
requires_terraform = pytest.mark.skipif(
    not render_iam_policies.available() and not os.environ.get("CI"),
    reason="terraform is not installed (CI fails instead of skipping)",
)

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)
URL = "https://example.com/"
# Actions Lambda itself performs for us, so no handler invokes them.
NOT_EXERCISED_BY_CODE = ("logs:", "sqs:SendMessage")
TRANSACTION_PARTS = {"dynamodb:PutItem", "dynamodb:UpdateItem"}


# ---- Turning the rendered documents into something moto can enforce ---------------------------


def for_moto(policy: dict) -> dict:
    """Action-level copy of a policy: resources widened to '*', transactions via their parts."""
    out = copy.deepcopy(policy)
    for statement in out["Statement"]:
        statement["Resource"] = "*"
        actions = set(statement["Action"])
        if actions >= TRANSACTION_PARTS:
            statement["Action"] = sorted(actions | {"dynamodb:TransactWriteItems"})
    return out


def without(policy: dict, action: str) -> dict:
    out = copy.deepcopy(policy)
    for statement in out["Statement"]:
        statement["Action"] = [a for a in statement["Action"] if a != action]
    out["Statement"] = [s for s in out["Statement"] if s["Action"]]
    return out


def actions_of(policy: dict) -> list[str]:
    return sorted({a for s in policy["Statement"] for a in s["Action"]})


def exercised(policy: dict) -> list[str]:
    return [a for a in actions_of(policy) if not a.startswith(NOT_EXERCISED_BY_CODE)]


def test_widening_keeps_every_action_and_only_changes_resources():
    policy = {
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem"],
                "Resource": ["arn:x"],
            },
            {"Effect": "Allow", "Action": ["sns:Publish"], "Resource": ["arn:y"]},
        ]
    }
    widened = for_moto(policy)
    assert [s["Resource"] for s in widened["Statement"]] == ["*", "*"]
    assert "dynamodb:TransactWriteItems" in widened["Statement"][0]["Action"]
    assert widened["Statement"][1]["Action"] == ["sns:Publish"]
    assert policy["Statement"][0]["Resource"] == ["arn:x"], "the original must not be modified"


def test_removing_an_action_drops_empty_statements():
    policy = {"Statement": [{"Effect": "Allow", "Action": ["a:One"], "Resource": "*"}]}
    assert without(policy, "a:One")["Statement"] == []


# ---- The rendered documents ------------------------------------------------------------------


@pytest.mark.negative
def test_a_render_failure_becomes_one_case_with_a_short_name(monkeypatch):
    """The case id is printed on every report line: it must not be terraform's whole stderr."""
    monkeypatch.setattr(render_iam_policies, "available", lambda: True)
    stderr = "Error: something\n" + "detail " * 200
    monkeypatch.setattr(render_iam_policies, "render_or_error", lambda: (None, stderr))
    cases = _necessary_actions()
    assert [case.id for case in cases] == [RENDER_FAILED]


@pytest.mark.negative
def test_the_policies_fixture_reports_a_render_failure_with_terraforms_message(monkeypatch):
    """Every test using the policies fails with the reason, instead of an unrelated error."""
    monkeypatch.setattr(
        render_iam_policies, "render_or_error", lambda: (None, "Error: no provider")
    )
    with pytest.raises(pytest.fail.Exception, match="(?s)could not render.*no provider"):
        _policies_or_fail()


def test_collecting_this_module_runs_no_terraform(monkeypatch):
    """Collection happens for every run, `-m unit` included: it must not start terraform, which
    could re-initialise the module and download providers."""
    calls = []
    monkeypatch.setattr(render_iam_policies, "_terraform", lambda *args, **_: calls.append(args) or "")
    monkeypatch.setattr(render_iam_policies, "available", lambda: True)
    render_iam_policies.clear_cache()
    try:
        spec = importlib.util.spec_from_file_location("iam_policies_collected_again", __file__)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    finally:
        render_iam_policies.clear_cache()
    assert calls == []


def test_terraform_is_available_where_it_must_run():
    """A silently skipped enforcement test would be a green build that proves nothing."""
    if os.environ.get("CI"):
        assert render_iam_policies.available(), "CI must install terraform for the policy tests"


def _policies_or_fail() -> dict:
    policies, error = render_iam_policies.render_or_error()
    if error:
        pytest.fail(f"terraform could not render the policies:\n{error}", pytrace=False)
    return policies


@pytest.fixture(scope="module")
def rendered():
    return _policies_or_fail()


@requires_terraform
def test_every_function_has_a_rendered_policy(rendered):
    assert set(rendered) == {"uptime_check", "register_endpoint", "get_checks"}
    for policy in rendered.values():
        assert policy["Version"] == "2012-10-17"
        assert all(s["Effect"] == "Allow" for s in policy["Statement"])


# ---- Running the handlers as the function's own role ------------------------------------------


@pytest.fixture
def enforcement(aws, monkeypatch):
    """Switch moto's IAM enforcement on and off around code that acts as a given policy."""
    import moto.settings as moto_settings  # lazily: the unit layer must never import moto
    from moto.core.responses import ActionAuthenticatorMixin

    unlimited = 10**9
    monkeypatch.setattr(moto_settings, "INITIAL_NO_AUTH_ACTION_COUNT", unlimited)
    monkeypatch.setattr(ActionAuthenticatorMixin, "request_count", 0)

    class Roles:
        def __init__(self):
            self.count = 0

        def credentials_for(self, policy: dict) -> dict:
            self.count += 1
            iam = boto3.client("iam")
            name = f"role-{self.count}"
            iam.create_user(UserName=name)
            iam.put_user_policy(
                UserName=name, PolicyName="p", PolicyDocument=json.dumps(for_moto(policy))
            )
            key = iam.create_access_key(UserName=name)["AccessKey"]
            return {
                "AWS_ACCESS_KEY_ID": key["AccessKeyId"],
                "AWS_SECRET_ACCESS_KEY": key["SecretAccessKey"],
            }

        def act_as(self, policy: dict):
            return _ActingAs(self.credentials_for(policy), monkeypatch, moto_settings, unlimited)

    return Roles()


def fresh_clients():
    """Forget cached clients and the default session, which caches the credentials it resolved."""
    aws_clients.reset()
    boto3.setup_default_session()


class _ActingAs:
    def __init__(self, credentials, monkeypatch, moto_settings, unlimited):
        self.credentials, self.mp, self.settings, self.unlimited = (
            credentials,
            monkeypatch,
            moto_settings,
            unlimited,
        )

    def __enter__(self):
        for name, value in self.credentials.items():
            self.mp.setenv(name, value)
        self.mp.delenv("AWS_SESSION_TOKEN", raising=False)
        self.mp.delenv("AWS_SECURITY_TOKEN", raising=False)
        fresh_clients()
        self.mp.setattr(self.settings, "INITIAL_NO_AUTH_ACTION_COUNT", 0)

    def __exit__(self, *exc):
        self.mp.setattr(self.settings, "INITIAL_NO_AUTH_ACTION_COUNT", self.unlimited)
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
            self.mp.setenv(name, "testing")
        self.mp.setenv("AWS_SESSION_TOKEN", "testing")
        fresh_clients()


@pytest.fixture
def scenario_env(tables, sns_topic, monkeypatch):
    monkeypatch.setattr(register_endpoint, "resolver", lambda host: ["93.184.215.14"])
    monkeypatch.setattr(register_endpoint, "probe", lambda url, **_: CheckResult(503, 40.0))
    monkeypatch.setattr(register_endpoint, "utcnow", lambda: NOW)
    monkeypatch.setattr(get_checks, "utcnow", lambda: NOW)
    monkeypatch.setattr(uptime_check, "utcnow", lambda: NOW)
    monkeypatch.setattr(uptime_check, "probe", lambda url, **_: CheckResult(503, 40.0))
    monkeypatch.setenv("FAILURE_THRESHOLD", "1")  # one failed check opens an incident and alerts


def register_scenario():
    """Register, register again (a lookup), then hit the cap."""
    body = json.dumps({"url": URL})
    first = register_endpoint.lambda_handler({"version": "2.0", "body": body}, None)
    again = register_endpoint.lambda_handler({"version": "2.0", "body": body}, None)
    other = register_endpoint.lambda_handler(
        {"version": "2.0", "body": json.dumps({"url": "https://other.example.com/"})}, None
    )
    return [first["statusCode"], again["statusCode"], other["statusCode"]]


def read_scenario():
    response = get_checks.lambda_handler({"queryStringParameters": {"url": URL}}, None)
    return [response["statusCode"]]


def check_scenario():
    try:
        summary = uptime_check.lambda_handler({}, None)
    except Exception as error:  # noqa: BLE001 - any failure means the permissions were not enough
        return ["raised", type(error).__name__]
    return [summary["errors"], summary["down"]]


# The last item says whether the DOWN alert was delivered: the code logs and carries on if SNS
# refuses, so only this shows that sns:Publish is needed.
EXPECTED = {
    "register_endpoint": [201, 200, 429, True],
    "get_checks": [200],
    "uptime_check": [0, 1, True],
}


def run_as(function, policy, enforcement, monkeypatch):
    prepare(function, monkeypatch)
    with enforcement.act_as(policy):
        try:
            outcome = RUNNERS[function]()
        except Exception as error:  # noqa: BLE001 - a refused permission surfaces as any error
            return ["raised", type(error).__name__]
    if function != "get_checks":
        stored = Repo().get_endpoint(endpoint_id(URL)) or {}
        outcome.append(stored.get("last_alert_sent") is not None)
    return outcome


def prepare(name, monkeypatch):
    """Create the state a scenario starts from, with enforcement off."""
    if name == "register_endpoint":
        monkeypatch.setenv("MAX_ENDPOINTS", "1")
    else:
        monkeypatch.setenv("MAX_ENDPOINTS", "10")
        Repo().put_endpoint(endpoint_id(URL), URL, NOW)


RUNNERS = {
    "register_endpoint": register_scenario,
    "get_checks": read_scenario,
    "uptime_check": check_scenario,
}


@requires_terraform
@pytest.mark.parametrize("function", ["register_endpoint", "get_checks", "uptime_check"])
def test_each_function_works_with_exactly_the_permissions_terraform_grants(
    function, rendered, enforcement, scenario_env, monkeypatch
):
    assert run_as(function, rendered[function], enforcement, monkeypatch) == EXPECTED[function]


RENDER_FAILED = "terraform-render-failed"


def _necessary_actions():
    """Evaluated at collection: a render failure becomes one failing case, not an aborted run.
    That case fails in the `rendered` fixture, which reports terraform's message."""
    if not render_iam_policies.available():
        return []
    policies, error = render_iam_policies.render_or_error()
    if error:
        return [pytest.param(RENDER_FAILED, None, id=RENDER_FAILED)]
    return [
        pytest.param(name, action, id=f"{name}-{action}")
        for name, policy in sorted(policies.items())
        for action in exercised(policy)
    ]


@requires_terraform
@pytest.mark.negative
@pytest.mark.security
@pytest.mark.parametrize("function, action", _necessary_actions())
def test_removing_any_single_permission_breaks_the_function(
    function, action, rendered, enforcement, scenario_env, monkeypatch
):
    """Every granted action is used: if one could be removed unnoticed, it is over-privilege."""
    outcome = run_as(function, without(rendered[function], action), enforcement, monkeypatch)
    assert outcome != EXPECTED[function], (
        f"{function} still works without {action}: not needed, or not exercised"
    )
