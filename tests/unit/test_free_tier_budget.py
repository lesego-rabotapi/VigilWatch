"""Both environments share one AWS account, so the free tier is checked across them together.

`terraform validate` sees one environment at a time and cannot do this sum.
"""

import pytest

import free_tier_budget

pytestmark = pytest.mark.req("VW-013")

DEV = """
environment                  = "dev"
dynamodb_capacity            = 2 # two tables
dynamodb_deletion_protection = false
metrics_enabled              = false
enabled_alarms               = ["checker-errors", "checker-not-running"]
"""
PROD = """
environment       = "prod"
dynamodb_capacity = 5
metrics_enabled   = true
enabled_alarms    = ["checker-errors", "checker-not-running", "checker-dlq", "checker-blind", "api-5xx"]
"""


def write_envs(tmp_path, **envs):
    for name, text in envs.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / "terraform.tfvars").write_text(text, encoding="utf-8")
    return tmp_path


def test_parses_numbers_booleans_strings_lists_and_comments():
    values = free_tier_budget.parse_tfvars(DEV)
    assert values == {
        "environment": "dev",
        "dynamodb_capacity": 2,
        "dynamodb_deletion_protection": False,
        "metrics_enabled": False,
        "enabled_alarms": ["checker-errors", "checker-not-running"],
    }


def test_the_committed_sizes_fit(tmp_path):
    envs = write_envs(tmp_path, dev=DEV, prod=PROD)
    assert free_tier_budget.violations(envs) == []


@pytest.mark.boundary
@pytest.mark.parametrize("capacity, fits", [(10, True), (11, False)])
def test_capacity_is_summed_across_environments(tmp_path, capacity, fits):
    """Two tables per environment: dev 2 x 2 = 4, prod 2 x 10 = 20, 24 <= 25; prod 11 gives 26.
    Each module alone would accept 11 (2 x 11 = 22), which is why the sum is checked here."""
    prod = PROD.replace("dynamodb_capacity = 5", f"dynamodb_capacity = {capacity}")
    problems = free_tier_budget.violations(write_envs(tmp_path, dev=DEV, prod=prod))
    assert (problems == []) is fits


@pytest.mark.negative
def test_alarms_beyond_ten_in_total_are_reported(tmp_path):
    dev = DEV.replace(
        '["checker-errors", "checker-not-running"]',
        '["checker-errors", "checker-not-running", "checker-dlq", "api-5xx", "checker-blind", "x", "y"]',
    )
    problems = free_tier_budget.violations(write_envs(tmp_path, dev=dev, prod=PROD))
    assert any("alarms" in p for p in problems)


@pytest.mark.negative
def test_two_environments_publishing_metrics_are_reported(tmp_path):
    dev = DEV.replace("metrics_enabled              = false", "metrics_enabled = true")
    problems = free_tier_budget.violations(write_envs(tmp_path, dev=dev, prod=PROD))
    assert any("custom metrics" in p for p in problems)


@pytest.mark.negative
def test_the_command_fails_when_over_budget(tmp_path, capsys):
    prod = PROD.replace("dynamodb_capacity = 5", "dynamodb_capacity = 12")
    envs = write_envs(tmp_path, dev=DEV, prod=prod)
    assert free_tier_budget.main(["--envs", str(envs)]) == 1
    assert "capacity" in capsys.readouterr().out


def test_the_command_passes_on_the_repository():
    assert free_tier_budget.main([]) == 0
