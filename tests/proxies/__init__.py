"""Proxies for the environments tests may target.

There is deliberately no production proxy class: production is reached only through the generic,
read-only ApiProxy, with its address supplied at run time.
"""

import os

from tests.e2e.config import api_url, get_environment
from tests.proxies import cognito
from tests.proxies.base_proxy import ApiProxy, ProxyError
from tests.proxies.dev_proxy import DevProxy
from tests.proxies.local_proxy import DEFAULT_LOCAL_URL, LocalProxy


def create_proxy_for_environment(name: str | None = None) -> ApiProxy:
    env = get_environment(name)
    url = api_url(env)
    if env.name == "local":
        return LocalProxy(url or DEFAULT_LOCAL_URL, timeout=env.timeout)
    if url is None:
        raise ProxyError(f"no API address for {env.name}: set {env.api_var} (or API_URL)")
    token = smoke_token(env.timeout)
    if env.name == "dev":
        return DevProxy(url, timeout=env.timeout, token=token)
    return ApiProxy(url, read_only=env.read_only, timeout=env.timeout, token=token)


def smoke_token(timeout: float) -> str:
    """Sign in as the smoke-test user (ADR 0007). The local stack signs itself in instead."""
    username, password = os.environ.get("E2E_USERNAME"), os.environ.get("E2E_PASSWORD")
    client_id = os.environ.get("COGNITO_CLIENT_ID")
    if not (username and password and client_id):
        raise ProxyError(
            "a deployed API needs a signed-in caller: set E2E_USERNAME, E2E_PASSWORD and "
            "COGNITO_CLIENT_ID (the smoke_client_id output; docs/RUNBOOK.md, section 1)"
        )
    region = os.environ.get("AWS_REGION", "af-south-1")
    return cognito.cognito_token(client_id, username, password, region, timeout)


__all__ = ["ApiProxy", "ProxyError", "create_proxy_for_environment"]
