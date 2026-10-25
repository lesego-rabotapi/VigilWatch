"""Runtime settings read from the environment (set by Terraform)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    degraded_ms: float = 1000
    failure_threshold: int = 2
    timeout_s: float = 5
    max_workers: int = 10

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            degraded_ms=float(os.environ.get("DEGRADED_MS", cls.degraded_ms)),
            failure_threshold=int(os.environ.get("FAILURE_THRESHOLD", cls.failure_threshold)),
            timeout_s=float(os.environ.get("PROBE_TIMEOUT_S", cls.timeout_s)),
            max_workers=int(os.environ.get("MAX_WORKERS", cls.max_workers)),
        )
