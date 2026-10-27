"""Both environments share one AWS account, so the free tier is checked across them together.

`terraform validate` sees one environment at a time and cannot do this sum.
"""

import json

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
ALL_ALARMS = ["checker-errors", "checker-not-running", "checker-dlq", "checker-blind", "api-5xx"]
PROD = f"""
environment       = "prod"
dynamodb_capacity = 5
metrics_enabled   = true
enabled_alarms    = {json.dumps(ALL_ALARMS)}
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


def test_parses_lists_written_over_several_lines():
    text = 'enabled_alarms = [\n  "checker-errors", # first\n  "api-5xx",\n]\nx = 1\n'
    assert free_tier_budget.parse_tfvars(text) == {
        "enabled_alarms": ["checker-errors", "api-5xx"],
        "x": 1,
    }


def test_every_hcl_comment_style_is_ignored():
    text = "// line\na = 1 // trailing\n/* block\n b = 2 */\nc = 3 # hash\n"
    assert free_tier_budget.parse_tfvars(text) == {"a": 1, "c": 3}


def test_a_hash_or_slashes_inside_a_string_are_part_of_the_string():
    text = 'origin = "http://localhost:3000/#x"\nlist = ["a#b", "c//d"]\n'
    assert free_tier_budget.parse_tfvars(text) == {
        "origin": "http://localhost:3000/#x",
        "list": ["a#b", "c//d"],
    }


@pytest.mark.negative
def test_syntax_it_cannot_read_is_an_error_not_a_wrong_answer():
    with pytest.raises(ValueError, match="tags"):
        free_tier_budget.parse_tfvars('tags = { a = "b" }\n')


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
    six = (
        '["checker-errors", "checker-not-running", "checker-dlq", "api-5xx", "checker-blind", "x"]'
    )
    dev = DEV.replace('["checker-errors", "checker-not-running"]', six)
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


@pytest.mark.negative
def test_finding_no_environment_fails_instead_of_passing_on_nothing(tmp_path, capsys):
    """A moved or misspelt envs directory must not turn the check into a green no-op."""
    assert free_tier_budget.main(["--envs", str(tmp_path)]) == 1
    assert "no environments" in capsys.readouterr().out


@pytest.mark.negative
def test_a_missing_setting_is_named_not_a_bare_key_error(tmp_path):
    prod = PROD.replace("dynamodb_capacity = 5\n", "")
    problems = free_tier_budget.violations(write_envs(tmp_path, dev=DEV, prod=prod))
    assert problems == ["prod: dynamodb_capacity is not set"]


def test_the_command_passes_on_the_repository():
    assert free_tier_budget.main([]) == 0
