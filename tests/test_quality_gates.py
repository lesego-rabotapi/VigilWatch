"""Quality gates are pinned so they cannot be loosened by accident."""

import json
import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("VW-017", "VW-019")

ROOT = Path(__file__).resolve().parent.parent


def test_python_coverage_gate_is_at_least_90_percent():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["coverage"]["report"]["fail_under"] >= 90
    assert config["tool"]["coverage"]["run"]["branch"] is True


def _frontend_test_command():
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    return package["scripts"]["test"]


def test_frontend_tests_run_with_coverage_and_enforced_thresholds():
    command = _frontend_test_command()
    assert "--experimental-test-coverage" in command
    for flag, minimum in (("lines", 90), ("functions", 90), ("branches", 80)):
        match = re.search(rf"--test-coverage-{flag}=(\d+)", command)
        assert match, f"no {flag} threshold in: {command}"
        assert int(match.group(1)) >= minimum, f"{flag} threshold below {minimum}"


def test_frontend_coverage_counts_the_wiring_code_not_just_the_helpers():
    """The gate must include app.js: leaving it out would hide the untested form flow."""
    command = _frontend_test_command()
    assert "--test-coverage-exclude" in command, "exclude the tests themselves from the figure"
    assert "app.js" not in command.split("--test-coverage-exclude")[1].split(" --")[0]


def test_ci_runs_the_frontend_suite_through_npm_test():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "npm test" in ci
