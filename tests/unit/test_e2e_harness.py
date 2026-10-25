"""The E2E harness: environments, read-only protection and the proxies tests talk through."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.e2e.config import ENVIRONMENTS, api_url, dashboard_url, get_environment
from tests.proxies import create_proxy_for_environment
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


def test_the_default_environment_is_dev_and_can_come_from_ENV(monkeypatch):
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


def test_the_factory_returns_the_right_proxy_per_environment(monkeypatch):
    monkeypatch.setenv("API_URL_DEV", "http://dev.test")
    monkeypatch.setenv("API_URL_PROD", "http://prod.test")
    assert isinstance(create_proxy_for_environment("dev"), DevProxy)
    assert isinstance(create_proxy_for_environment("local"), LocalProxy)
    prod = create_proxy_for_environment("prod")
    assert type(prod) is ApiProxy and prod.read_only is True


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
        ApiProxy("http://127.0.0.1:1", timeout=0.5).checks("https://example.com/")
