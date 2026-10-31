"""Proxies for the environments tests may target.

There is deliberately no production proxy class: production is reached only through the generic,
read-only ApiProxy, with its address supplied at run time.
"""

from tests.e2e.config import api_url, get_environment
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
    if env.name == "dev":
        return DevProxy(url, timeout=env.timeout)
    return ApiProxy(url, read_only=env.read_only, timeout=env.timeout)


__all__ = ["ApiProxy", "ProxyError", "create_proxy_for_environment"]
