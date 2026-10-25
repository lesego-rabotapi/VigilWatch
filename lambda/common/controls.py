"""Connectivity checks: can the checker itself reach the internet?

A target that does not answer is only evidence about the target if the checker could have
reached anything at all. Control URLs (this deployment's own health file and an independent
site) answer that question. If at least one control answers properly, the checker's outbound
path works and a failing target really is failing. If none answers, the checker is blind and
cannot judge any target.

A control is "answering" when it returns a 2xx or 3xx status without an error.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass


@dataclass(frozen=True)
class ControlReport:
    checked: int
    ok: int
    healthy: bool


def _answered(result) -> bool:
    return (
        result.error is None and result.status_code is not None and 200 <= result.status_code < 400
    )


def check_controls(
    urls: tuple[str, ...], probe_fn: Callable, timeout: float = 5.0
) -> ControlReport:
    """Probe every control once, in parallel. With none configured, assume connectivity is fine."""
    if not urls:
        return ControlReport(checked=0, ok=0, healthy=True)

    def one(url: str) -> bool:
        try:
            return _answered(probe_fn(url, timeout=timeout))
        except Exception:  # a control that blows up is a control that did not answer
            return False

    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        ok = sum(pool.map(one, urls))
    return ControlReport(checked=len(urls), ok=ok, healthy=ok > 0)
