"""probe() against a real local HTTP server (guard bypassed via the injectable validator)."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from common.checker import probe
from common.urlguard import UnsafeURL


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (stdlib naming)
        if self.path == "/ok":
            self.send_response(200)
        elif self.path == "/error":
            self.send_response(503)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
        elif self.path == "/slow":
            time.sleep(1.0)
            self.send_response(200)
        else:
            self.send_response(404)
        self.end_headers()
        self.server.user_agents.append(self.headers.get("User-Agent"))

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.user_agents = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


def no_guard(url):
    return url


def url(server, path):
    return f"http://127.0.0.1:{server.server_address[1]}{path}"


def test_success_records_status_and_latency(server):
    result = probe(url(server, "/ok"), validator=no_guard)
    assert result.status_code == 200
    assert result.error is None
    assert 0 <= result.latency_ms < 1000


def test_http_error_status_is_captured_not_raised(server):
    result = probe(url(server, "/error"), validator=no_guard)
    assert result.status_code == 503
    assert result.error is None


def test_redirects_are_not_followed(server):
    result = probe(url(server, "/redirect"), validator=no_guard)
    assert result.status_code == 302


def test_timeout_is_an_error(server):
    result = probe(url(server, "/slow"), timeout=0.2, validator=no_guard)
    assert result.status_code is None
    assert result.error


def test_connection_refused_is_an_error():
    result = probe("http://127.0.0.1:1/", timeout=0.5, validator=no_guard)
    assert result.status_code is None
    assert result.error


def test_identifies_itself(server):
    probe(url(server, "/ok"), validator=no_guard)
    assert server.user_agents[-1].startswith("VigilWatch/")


def test_guard_runs_by_default_and_blocks_private_targets(server):
    result = probe(url(server, "/ok"))
    assert result.status_code is None
    assert "private" in result.error


def test_guard_failure_never_raises():
    def exploding(_url):
        raise UnsafeURL("nope")

    assert probe("https://example.com", validator=exploding).error == "nope"
