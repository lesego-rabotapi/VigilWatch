"""Fixtures for end-to-end tests: pick an environment, get a proxy, guard writes."""

import os

import pytest

from tests.e2e.config import dashboard_url, get_environment, unavailable
from tests.proxies import ApiProxy, ProxyError, create_proxy_for_environment

TARGET = "https://example.com/"


@pytest.fixture(scope="session")
def env_config(request):
    return get_environment(request.config.getoption("--env"))


@pytest.fixture(scope="session")
def proxy(env_config):
    try:
        return create_proxy_for_environment(env_config.name)
    except ProxyError as exc:
        unavailable(str(exc))


@pytest.fixture(scope="session")
def dashboard(env_config):
    url = dashboard_url(env_config)
    if url is None:
        unavailable(f"no dashboard address: set {env_config.dashboard_var} (or DASHBOARD_URL)")
    return ApiProxy(url, read_only=True, timeout=env_config.timeout)


@pytest.fixture
def writable(env_config):
    """Request this in any test that modifies data: it skips where writes are not allowed."""
    if env_config.read_only:
        pytest.skip(f"{env_config.name} is read-only; write tests do not run there")


@pytest.fixture(scope="session")
def monitored_url(env_config, proxy):
    """A monitored URL: writable environments register one, read-only ones are given one."""
    if env_config.read_only:
        url = os.environ.get("E2E_READONLY_URL")
        if not url:
            unavailable("set E2E_READONLY_URL to a URL that is already monitored")
        return url
    response = proxy.register(TARGET)
    assert response.status in (200, 201), response.text
    return TARGET
