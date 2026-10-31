"""HTTP client every end-to-end test talks through.

Tests never call Lambda or DynamoDB directly: the only way in is the public API, exactly as a
visitor would use it. A proxy for a read-only environment refuses writes before any network call.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import quote


class ProxyError(Exception):
    """The API could not be reached or the harness is misconfigured."""


class ReadOnlyEnvironmentError(ProxyError):
    """A write was attempted against an environment that must not be modified."""


@dataclass(frozen=True)
class Response:
    status: int
    text: str
    headers: dict = field(default_factory=dict)

    @property
    def json(self):
        return json.loads(self.text)

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        return next((v for k, v in self.headers.items() if k.lower() == wanted), None)


class ApiProxy:
    def __init__(self, base_url: str, read_only: bool = False, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.read_only = read_only
        self.timeout = timeout

    def _send(self, method: str, path: str, body=None, headers=None) -> Response:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(  # noqa: S310 (base URL comes from the environment)
            self.base_url + path, data=data, method=method, headers=headers or {}
        )
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:  # noqa: S310
                return Response(reply.status, reply.read().decode(), dict(reply.headers))
        except urllib.error.HTTPError as exc:  # 4xx/5xx are results the tests assert on
            return Response(exc.code, exc.read().decode(), dict(exc.headers))
        except (urllib.error.URLError, OSError) as exc:
            raise ProxyError(f"could not reach {self.base_url}: {exc}") from exc

    def _require_writable(self) -> None:
        if self.read_only:
            raise ReadOnlyEnvironmentError("this environment is read-only; writes are not allowed")

    def register(self, url: str, expected_status: int | None = None) -> Response:
        self._require_writable()
        body = {"url": url}
        if expected_status is not None:
            body["expected_status"] = expected_status
        return self._send("POST", "/register", body)

    def checks(self, url: str) -> Response:
        return self._send("GET", f"/checks?url={quote(url, safe='')}")

    def preflight(self, path: str, origin: str) -> Response:
        return self._send(
            "OPTIONS",
            path,
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    def get(self, path: str) -> Response:
        return self._send("GET", path)
