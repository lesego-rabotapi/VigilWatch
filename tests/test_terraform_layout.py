"""Infrastructure layout rules: modules at the bottom, thin environments on top, nothing hardcoded.

The free-tier arithmetic is checked across both environments together because they share one
AWS account and therefore one free tier.
"""

import re
from pathlib import Path

import pytest

import free_tier_budget

pytestmark = pytest.mark.req("VW-013", "VW-016", "VW-017")

ROOT = Path(__file__).resolve().parent.parent
TF = ROOT / "terraform"
MODULES = ("alerts", "data", "compute", "api", "frontend", "monitoring", "vigilwatch")
ENVS = ("dev", "prod")
FREE_ALARMS = 10
FREE_CAPACITY = 25
KNOWN_ALARMS = {"checker-errors", "checker-not-running", "checker-dlq", "checker-blind", "api-5xx"}


def tfvars(env: str) -> dict:
    return free_tier_budget.parse_tfvars(
        (TF / "envs" / env / "terraform.tfvars").read_text(encoding="utf-8")
    )


def terraform_files(*, include_tests=False):
    for path in TF.rglob("*"):
        if ".terraform" in path.parts or ".build" in path.parts or "bootstrap" in path.parts:
            continue
        if not include_tests and "tests" in path.parts:
            continue
        if path.suffix in (".tf", ".tfvars", ".hcl") or path.name.endswith(".example"):
            yield path


# ---- Shape -------------------------------------------------------------------


@pytest.mark.parametrize("module", MODULES)
def test_every_module_has_inputs_outputs_and_its_own_tests(module):
    base = TF / "modules" / module
    for name in ("main.tf", "variables.tf", "outputs.tf", "versions.tf"):
        assert (base / name).exists(), f"modules/{module}/{name}"
    assert list((base / "tests").glob("*.tftest.hcl")), f"modules/{module} has no terraform tests"


@pytest.mark.parametrize("env", ENVS)
def test_every_environment_is_a_thin_root(env):
    base = TF / "envs" / env
    for name in ("main.tf", "terraform.tfvars", "backend.hcl.example", ".terraform.lock.hcl"):
        assert (base / name).exists(), f"envs/{env}/{name}"
    assert list((base / "tests").glob("*.tftest.hcl")), f"envs/{env} has no terraform tests"
    for path in base.glob("*.tf"):
        declared = re.findall(r'^(resource|data)\s+"', path.read_text(encoding="utf-8"), re.M)
        assert declared == [], f"{path.relative_to(ROOT)} declares {declared}: put it in a module"


def test_there_are_no_resources_left_at_the_terraform_root():
    assert sorted(p.name for p in TF.glob("*.tf")) == []


def test_root_level_tests_moved_into_the_modules_they_describe():
    assert not (TF / "tests").exists(), "root-level tests describe resources that moved to modules"


# ---- Environments are isolated ----------------------------------------------


def test_each_environment_has_its_own_state_key():
    keys = {}
    for env in ENVS:
        text = (TF / "envs" / env / "backend.hcl.example").read_text(encoding="utf-8")
        match = re.search(r'^key\s*=\s*"([^"]+)"', text, re.M)
        assert match, env
        keys[env] = match.group(1)
    assert keys == {"dev": "vigilwatch/dev.tfstate", "prod": "vigilwatch/prod.tfstate"}


@pytest.mark.parametrize("env", ENVS)
def test_the_environment_name_matches_its_directory(env):
    assert tfvars(env)["environment"] == env


@pytest.mark.parametrize("env", ENVS)
def test_the_provider_refuses_to_run_in_the_wrong_account(env):
    text = "\n".join(p.read_text(encoding="utf-8") for p in (TF / "envs" / env).glob("*.tf"))
    assert "allowed_account_ids" in text
    match = re.search(r'variable\s+"allowed_account_ids"\s*\{(.*?)\n\}', text, re.S)
    assert match, "allowed_account_ids must be a variable"
    assert "default" not in match.group(1), "it must be supplied, never defaulted"
    assert "12" in match.group(1), "it must be validated as a 12-digit account id"


def test_no_account_ids_or_addresses_are_hardcoded_in_infrastructure_code():
    offenders = []
    for path in terraform_files():
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?<![\w.-])\d{12}(?![\w.-])", text):
            offenders.append(str(path.relative_to(ROOT)))
        if re.search(r"[\w.-]+@[\w-]+\.[a-z]{2,}", text) and path.suffix == ".tfvars":
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


# ---- Free-tier arithmetic across environments --------------------------------


def test_the_committed_environments_fit_one_free_tier():
    assert free_tier_budget.violations() == []


def test_provisioned_capacity_of_both_environments_fits_one_free_tier():
    total = sum(2 * tfvars(env)["dynamodb_capacity"] for env in ENVS)  # two tables each
    assert total <= FREE_CAPACITY, f"{total} units for both environments, free tier is 25"


def test_alarms_of_both_environments_fit_one_free_tier():
    names = {env: tfvars(env)["enabled_alarms"] for env in ENVS}
    assert sum(len(v) for v in names.values()) <= FREE_ALARMS, names
    for env, alarms in names.items():
        assert set(alarms) <= KNOWN_ALARMS, (env, set(alarms) - KNOWN_ALARMS)


def test_only_one_environment_publishes_custom_metrics():
    """Ten custom metrics are free and one environment already publishes seven."""
    publishing = [env for env in ENVS if tfvars(env)["metrics_enabled"]]
    assert publishing == ["prod"]


def test_an_environment_without_metrics_has_no_alarm_that_needs_them():
    for env in ENVS:
        if not tfvars(env)["metrics_enabled"]:
            assert "checker-blind" not in tfvars(env)["enabled_alarms"], env


def test_production_tables_are_protected_and_development_can_be_torn_down():
    assert tfvars("prod")["dynamodb_deletion_protection"] is True
    assert tfvars("dev")["dynamodb_deletion_protection"] is False


# ---- Build once ---------------------------------------------------------------


def test_terraform_deploys_a_prebuilt_bundle_instead_of_zipping_at_plan_time():
    text = "\n".join(p.read_text(encoding="utf-8") for p in terraform_files() if p.suffix == ".tf")
    assert "archive_file" not in text
    assert "var.bundle_path" in text and "var.bundle_sha256" in text


def test_no_archive_provider_is_required():
    for path in terraform_files():
        assert "hashicorp/archive" not in path.read_text(encoding="utf-8"), path


# ---- Hygiene -------------------------------------------------------------------


def test_environment_tfvars_are_committed_not_ignored():
    import subprocess

    for env in ENVS:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", f"terraform/envs/{env}/terraform.tfvars"],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 1, f"envs/{env}/terraform.tfvars is git-ignored"


# ---- The CI deploy role can reach what the environments create -------------------------------


def _bootstrap_s3_resources() -> list[str]:
    text = (TF / "bootstrap" / "main.tf").read_text(encoding="utf-8")
    block = re.search(r'Sid\s*=\s*"FrontendBucketOnly"(.*?)\n\s*\}', text, re.S)
    assert block, "bootstrap has no FrontendBucketOnly statement"
    arns = re.findall(r'"(arn:aws:s3:::[^"]+)"', block.group(1))
    return [
        a.replace("${var.project_name}", "vigilwatch").replace(
            "${data.aws_caller_identity.current.account_id}", "123456789012"
        )
        for a in arns
    ]


@pytest.mark.parametrize("env", ENVS)
def test_the_deploy_role_may_manage_each_environments_dashboard_bucket(env):
    """The frontend module names buckets <project>-<env>-frontend-<account>; the role must match."""
    import fnmatch

    module = (TF / "modules" / "frontend" / "main.tf").read_text(encoding="utf-8")
    assert 'bucket = "${var.name_prefix}-frontend-${var.account_id}"' in module
    bucket = f"arn:aws:s3:::vigilwatch-{env}-frontend-123456789012"
    resources = _bootstrap_s3_resources()
    assert any(fnmatch.fnmatchcase(bucket, r) for r in resources), resources
    assert any(fnmatch.fnmatchcase(bucket + "/index.html", r) for r in resources), resources


def test_the_deploy_role_s3_grant_stays_inside_this_projects_buckets():
    for resource in _bootstrap_s3_resources():
        assert resource.startswith("arn:aws:s3:::vigilwatch-"), resource
        assert "-frontend-123456789012" in resource, resource


# ---- Every setting of an environment can be changed from that environment ----------------------

# Set by the environment root itself, not by the operator.
FIXED_BY_THE_ROOT = {"frontend_dir"}


def _declared(path: Path) -> set[str]:
    return set(re.findall(r'^variable\s+"(\w+)"', path.read_text(encoding="utf-8"), re.M))


@pytest.mark.parametrize("env", ENVS)
def test_every_stack_setting_is_exposed_and_passed_by_the_environment(env):
    stack = _declared(TF / "modules" / "vigilwatch" / "variables.tf") - FIXED_BY_THE_ROOT
    base = TF / "envs" / env
    missing = stack - _declared(base / "variables.tf")
    assert not missing, f"envs/{env} cannot set {sorted(missing)}"
    main = (base / "main.tf").read_text(encoding="utf-8")
    unpassed = [v for v in stack if not re.search(rf"^\s*{v}\s*=\s*var\.{v}\s*$", main, re.M)]
    assert not unpassed, f"envs/{env} declares but does not pass {sorted(unpassed)}"


def test_settings_the_runbook_tells_operators_to_change_exist_in_every_environment():
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`([a-z]+(?:_[a-z0-9]+)+)`", runbook))
    stack = _declared(TF / "modules" / "vigilwatch" / "variables.tf")
    for env in ENVS:
        settable = _declared(TF / "envs" / env / "variables.tf")
        assert (named & stack) <= settable, sorted((named & stack) - settable)


def test_the_runbook_uses_per_environment_names_and_paths():
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    for stale in ("/aws/lambda/vigilwatch-uptime-check", "/aws/apigateway/vigilwatch-http"):
        assert stale not in runbook, stale
    rollback = runbook[runbook.index("## 6. Rollback") : runbook.index("## 7.")]
    assert "terraform/envs/prod" in rollback and "vigilwatch.tfvars.json" in rollback
    assert "allowed_account_ids" in rollback
