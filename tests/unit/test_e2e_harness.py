"""The E2E harness: environments, read-only protection and the proxies tests talk through."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.e2e.config import ENVIRONMENTS, api_url, dashboard_url, get_environment, unavailable
from tests.proxies import create_proxy_for_environment
from tests.proxies import cognito
from tests.proxies.base_proxy import ApiProxy, ProxyError, ReadOnlyEnvironmentError
from tests.proxies.dev_proxy import DevProxy
from tests.proxies.local_proxy import LocalProxy

pytestmark = pytest.mark.req("VW-017")


# ---- environments ------------------------------------------------------------------------------


def test_environments_and_their_write_permission():
    assert set(ENVIRONMENTS) == {"local", "dev", "prod"}
    assert [ENVIRONMENTS[name].read_only for name in ("local", "dev", "prod")] == [
        False,
        False,
        True,
    ]


def test_the_default_environment_is_dev_and_can_come_from_the_env_variable(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)
    assert get_environment().name == "dev"
    monkeypatch.setenv("ENV", "PROD")
    assert get_environment().name == "prod"


@pytest.mark.negative
def test_an_unknown_environment_is_refused_with_the_valid_choices():
    with pytest.raises(ValueError, match="local, dev, prod"):
        get_environment("staging")


def test_urls_come_from_the_environment_never_from_code(monkeypatch):
    for name in ("API_URL", "API_URL_DEV", "DASHBOARD_URL", "DASHBOARD_URL_DEV"):
        monkeypatch.delenv(name, raising=False)
    dev = get_environment("dev")
    assert api_url(dev) is None and dashboard_url(dev) is None
    monkeypatch.setenv("API_URL", "http://generic.test/")
    assert api_url(dev) == "http://generic.test", (
        "generic variable is the fallback, trailing / trimmed"
    )
    monkeypatch.setenv("API_URL_DEV", "http://specific.test")
    assert api_url(dev) == "http://specific.test", "environment-specific variable wins"


def test_a_missing_address_skips_on_a_developer_machine(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception, match="E2E_READONLY_URL"):
        unavailable("set E2E_READONLY_URL")


@pytest.mark.negative
def test_a_missing_address_fails_in_ci_because_a_skipped_smoke_test_proves_nothing(monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception, match="E2E_READONLY_URL"):
        unavailable("set E2E_READONLY_URL")


# ---- proxies -----------------------------------------------------------------------------------


@pytest.mark.negative
@pytest.mark.security
def test_a_read_only_proxy_refuses_to_write_before_touching_the_network():
    proxy = ApiProxy("http://unreachable.invalid", read_only=True)
    with pytest.raises(ReadOnlyEnvironmentError):
        proxy.register("https://example.com/")


def test_there_is_no_production_proxy_class():
    with pytest.raises(ModuleNotFoundError):
        __import__("tests.proxies.prod_proxy")


@pytest.fixture
def smoke_user(monkeypatch):
    """The smoke-test user's settings, with Cognito answering a fixed token."""
    monkeypatch.setenv("E2E_USERNAME", "smoke@example.test")
    monkeypatch.setenv("E2E_PASSWORD", "not-a-real-password")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "smokeclient")
    calls = []

    def fake_token(client_id, username, password, region, timeout):
        calls.append((client_id, username, region))
        return "smoke-token"

    monkeypatch.setattr(cognito, "cognito_token", fake_token)
    return calls


def test_the_factory_returns_the_right_proxy_per_environment(monkeypatch, smoke_user):
    monkeypatch.setenv("API_URL_DEV", "http://dev.test")
    monkeypatch.setenv("API_URL_PROD", "http://prod.test")
    assert isinstance(create_proxy_for_environment("dev"), DevProxy)
    assert isinstance(create_proxy_for_environment("local"), LocalProxy)
    prod = create_proxy_for_environment("prod")
    assert type(prod) is ApiProxy and prod.read_only is True


@pytest.mark.req("VW-026")
def test_a_deployed_environment_is_reached_signed_in_as_the_smoke_user(monkeypatch, smoke_user):
    monkeypatch.setenv("API_URL_DEV", "http://dev.test")
    monkeypatch.delenv("AWS_REGION", raising=False)
    assert create_proxy_for_environment("dev").token == "smoke-token"
    assert smoke_user == [("smokeclient", "smoke@example.test", "af-south-1")]
    assert create_proxy_for_environment("local").token is None, "the local stack signs itself in"


@pytest.mark.req("VW-026")
@pytest.mark.negative
def test_a_deployed_environment_without_smoke_credentials_says_what_to_set(monkeypatch):
    monkeypatch.setenv("API_URL_DEV", "http://dev.test")
    for name in ("E2E_USERNAME", "E2E_PASSWORD", "COGNITO_CLIENT_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProxyError, match="E2E_USERNAME, E2E_PASSWORD and COGNITO_CLIENT_ID"):
        create_proxy_for_environment("dev")


@pytest.mark.negative
def test_the_factory_says_which_variable_to_set_when_no_url_is_configured(monkeypatch):
    for name in ("API_URL", "API_URL_DEV"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProxyError, match="API_URL_DEV"):
        create_proxy_for_environment("dev")


class _Echo(BaseHTTPRequestHandler):
    seen: list = []

    def _reply(self, status=200, body=None):
        payload = json.dumps(body if body is not None else {"ok": True}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        _Echo.seen.append(("POST", self.path, json.loads(self.rfile.read(length) or b"null")))
        self._reply(201, {"created": True})

    def do_GET(self):  # noqa: N802
        _Echo.seen.append(("GET", self.path, None))
        self._reply(404 if "missing" in self.path else 200)

    def do_OPTIONS(self):  # noqa: N802
        _Echo.seen.append(("OPTIONS", self.path, self.headers.get("Origin")))
        self._reply(204 if False else 200)

    def log_message(self, *args):
        pass


@pytest.fixture
def echo_server():
    _Echo.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_register_posts_json_and_returns_status_and_body(echo_server):
    response = ApiProxy(echo_server).register("https://example.com/", expected_status=204)
    assert (response.status, response.json) == (201, {"created": True})
    assert _Echo.seen == [
        ("POST", "/register", {"url": "https://example.com/", "expected_status": 204})
    ]


def test_checks_url_encodes_the_target_and_returns_client_errors_without_raising(echo_server):
    proxy = ApiProxy(echo_server, read_only=True)
    assert proxy.checks("https://example.com/a b?x=1&y=2").status == 200
    assert proxy.checks("https://missing.example.com/").status == 404
    assert _Echo.seen[0][1] == "/checks?url=https%3A%2F%2Fexample.com%2Fa%20b%3Fx%3D1%26y%3D2"


def test_a_read_only_proxy_may_still_read_and_preflight(echo_server):
    proxy = ApiProxy(echo_server, read_only=True)
    assert proxy.checks("https://example.com/").status == 200
    assert proxy.preflight("/register", "https://dash.test").status == 200
    assert _Echo.seen[-1] == ("OPTIONS", "/register", "https://dash.test")


@pytest.mark.negative
def test_a_connection_failure_is_a_proxy_error_not_a_raw_urllib_exception():
    with pytest.raises(ProxyError, match="could not reach"):
        ApiProxy("http://127.0.0.1:1", timeout=0.2).checks("https://example.com/")


# ---- signing in for the smoke tests (VW-026) -------------------------------------------------


class _Cognito(BaseHTTPRequestHandler):
    """Cognito's public InitiateAuth endpoint, as far as the smoke tests use it."""

    answer: dict = {}
    status = 200
    seen: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        _Cognito.seen.append((dict(self.headers), json.loads(self.rfile.read(length))))
        payload = json.dumps(_Cognito.answer).encode()
        self.send_response(_Cognito.status)
        self.send_header("Content-Type", "application/x-amz-json-1.1")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def cognito_server():
    _Cognito.seen, _Cognito.status = [], 200
    _Cognito.answer = {"AuthenticationResult": {"AccessToken": "the-token"}}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Cognito)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


def sign_in(endpoint):
    return cognito.cognito_token(
        "smokeclient", "smoke@example.test", "pw-123", "af-south-1", 5, endpoint=endpoint
    )


@pytest.mark.req("VW-026")
def test_the_smoke_token_comes_from_cognitos_public_endpoint(cognito_server):
    assert sign_in(cognito_server) == "the-token"
    headers, body = _Cognito.seen[0]
    assert headers["X-Amz-Target"] == "AWSCognitoIdentityProviderService.InitiateAuth"
    assert headers["Content-Type"] == "application/x-amz-json-1.1"
    assert body == {
        "AuthFlow": "USER_PASSWORD_AUTH",
        "ClientId": "smokeclient",
        "AuthParameters": {"USERNAME": "smoke@example.test", "PASSWORD": "pw-123"},
    }


def test_the_endpoint_is_the_regions_cognito():
    assert cognito.endpoint_for("af-south-1") == "https://cognito-idp.af-south-1.amazonaws.com/"


@pytest.mark.req("VW-026")
@pytest.mark.negative
def test_a_user_who_must_still_set_a_password_is_explained(cognito_server):
    _Cognito.answer = {"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": "s"}
    with pytest.raises(ProxyError, match="permanent password"):
        sign_in(cognito_server)


@pytest.mark.req("VW-026")
@pytest.mark.negative
def test_a_refused_sign_in_never_repeats_the_password(cognito_server):
    _Cognito.status = 400
    _Cognito.answer = {
        "__type": "NotAuthorizedException",
        "message": "Incorrect username or password.",
    }
    with pytest.raises(ProxyError, match="could not sign in") as error:
        sign_in(cognito_server)
    assert "pw-123" not in str(error.value)
    assert "NotAuthorizedException" in str(error.value)


class _Headers(BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):  # noqa: N802
        _Headers.seen.append(self.headers.get("Authorization"))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.mark.req("VW-026")
def test_a_signed_in_proxy_sends_its_token_and_its_anonymous_copy_does_not():
    _Headers.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Headers)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        proxy = ApiProxy(f"http://127.0.0.1:{httpd.server_address[1]}", token="tok")
        proxy.checks("https://example.com/")
        proxy.anonymous().checks("https://example.com/")
        assert _Headers.seen == ["Bearer tok", None]
        assert proxy.anonymous().read_only == proxy.read_only
    finally:
        httpd.shutdown()
