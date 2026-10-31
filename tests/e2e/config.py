"""Environments the end-to-end tests can target.

No URL is stored in this repository. Each environment's address comes from an environment variable
(`API_URL_<ENV>`, falling back to `API_URL`), which CI fills from the Terraform outputs.
Production is read-only: the harness refuses to write there.

    pytest -m e2e tests/e2e --env=dev
    pytest -m e2e tests/e2e --env=local      # against scripts/local_api.py
"""

import os
from dataclasses import dataclass
from typing import NoReturn

import pytest


@dataclass(frozen=True)
class EnvironmentConfig:
    name: str
    read_only: bool
    timeout: float = 20.0

    @property
    def api_var(self) -> str:
        return f"API_URL_{self.name.upper()}"

    @property
    def dashboard_var(self) -> str:
        return f"DASHBOARD_URL_{self.name.upper()}"


ENVIRONMENTS = {
    "local": EnvironmentConfig("local", read_only=False),
    "dev": EnvironmentConfig("dev", read_only=False),
    "prod": EnvironmentConfig("prod", read_only=True),
}


def get_environment(name: str | None = None) -> EnvironmentConfig:
    name = (name or os.environ.get("ENV", "dev")).lower()
    if name not in ENVIRONMENTS:
        raise ValueError(f"unknown environment {name!r}; choose one of: {', '.join(ENVIRONMENTS)}")
    return ENVIRONMENTS[name]


def _url(specific: str, generic: str) -> str | None:
    value = os.environ.get(specific) or os.environ.get(generic)
    return value.rstrip("/") if value else None


def unavailable(reason: str) -> NoReturn:
    """A missing address skips on a developer machine and fails in CI: a smoke run that skipped
    its checks would be a green deploy that proved nothing."""
    if os.environ.get("CI"):
        pytest.fail(reason, pytrace=False)
    pytest.skip(reason)


def api_url(env: EnvironmentConfig) -> str | None:
    return _url(env.api_var, "API_URL")


def dashboard_url(env: EnvironmentConfig) -> str | None:
    return _url(env.dashboard_var, "DASHBOARD_URL")
