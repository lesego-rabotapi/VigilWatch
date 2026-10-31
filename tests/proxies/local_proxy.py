"""The local stack started by `python scripts/local_api.py` (AWS mocked, no account needed)."""

from tests.proxies.base_proxy import ApiProxy

DEFAULT_LOCAL_URL = "http://127.0.0.1:8787"


class LocalProxy(ApiProxy):
    def __init__(self, base_url: str = DEFAULT_LOCAL_URL, timeout: float = 20.0):
        super().__init__(base_url, read_only=False, timeout=timeout)
