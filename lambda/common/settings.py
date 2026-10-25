"""Runtime settings read from the environment (set by Terraform).

Values are validated when read. A misconfigured function should fail loudly and name the
variable, rather than run with a nonsense value (an alert threshold of 0, a 10-minute probe
timeout). The failure-threshold range mirrors terraform/variables.tf.
"""

import math
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class SettingsError(ValueError):
    """An environment variable is missing a valid value."""


def _read(name: str, default, kind, low, high):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = kind(raw)
    except ValueError:
        value = None
    if value is None or (kind is float and not math.isfinite(value)):
        raise SettingsError(f"{name} must be a number, got {raw!r}")
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}, got {raw!r}")
    return value


MAX_CONTROL_URLS = 5


def _read_urls(name: str) -> tuple[str, ...]:
    urls = tuple(part.strip() for part in os.environ.get(name, "").split(",") if part.strip())
    if len(urls) > MAX_CONTROL_URLS:
        raise SettingsError(f"{name} accepts at most {MAX_CONTROL_URLS} URLs, got {len(urls)}")
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise SettingsError(f"{name} must hold http or https URLs, got {url!r}")
    return urls


@dataclass(frozen=True)
class Settings:
    degraded_ms: float = 1000
    failure_threshold: int = 2
    timeout_s: float = 5
    max_workers: int = 10
    control_urls: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            degraded_ms=_read("DEGRADED_MS", cls.degraded_ms, float, 1, 60_000),
            failure_threshold=_read("FAILURE_THRESHOLD", cls.failure_threshold, int, 1, 10),
            timeout_s=_read("PROBE_TIMEOUT_S", cls.timeout_s, float, 0.1, 30),
            max_workers=_read("MAX_WORKERS", cls.max_workers, int, 1, 50),
            control_urls=_read_urls("CONTROL_URLS"),
        )
