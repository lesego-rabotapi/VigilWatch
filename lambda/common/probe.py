"""Probe one URL with a single GET."""

import time
import urllib.error
import urllib.request
from collections.abc import Callable

from common.status import CheckResult
from common.urlguard import UnsafeURL, validate

USER_AGENT = "VigilWatch/1.0 (+https://github.com/lesego-rabotapi/VigilWatch)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Report 3xx as-is. Following redirects would let a public URL bounce the probe inward."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def probe(
    url: str,
    timeout: float = 5,
    validator: Callable[[str], str] = validate,
) -> CheckResult:
    """Single GET. Never raises: every failure becomes CheckResult.error."""
    try:
        url = validator(url)
    except UnsafeURL as exc:
        return CheckResult(status_code=None, latency_ms=None, error=str(exc))

    # Scheme is restricted to http/https by the validator above.
    request = urllib.request.Request(  # noqa: S310
        url, method="GET", headers={"User-Agent": USER_AGENT}
    )
    started = time.perf_counter()
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status_code = response.status
    except urllib.error.HTTPError as exc:
        status_code = exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return CheckResult(
            status_code=None, latency_ms=None, error=str(reason) or type(exc).__name__
        )
    return CheckResult(status_code=status_code, latency_ms=(time.perf_counter() - started) * 1000)
