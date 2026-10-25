"""The deployed DEV environment: reads and writes are allowed."""

from tests.proxies.base_proxy import ApiProxy


class DevProxy(ApiProxy):
    def __init__(self, base_url: str, timeout: float = 20.0):
        super().__init__(base_url, read_only=False, timeout=timeout)
