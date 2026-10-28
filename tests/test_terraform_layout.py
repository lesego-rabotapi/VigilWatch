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


def state_keys() -> dict[str, str]:
    keys = {}
    for env in ENVS:
        text = (TF / "envs" / env / "backend.hcl.example").read_text(encoding="utf-8")
        match = re.search(r'^key\s*=\s*"([^"]+)"', text, re.M)
        assert match, env
        keys[env] = match.group(1)
    return keys


def test_each_environment_has_its_own_state_key():
    """Not vigilwatch/prod.tfstate: the earlier flat-root pipeline used that key, and the new
    layout reading its state would plan to destroy whatever that pipeline created."""
    assert state_keys() == {
        "dev": "vigilwatch/envs/dev.tfstate",
        "prod": "vigilwatch/envs/prod.tfstate",
    }


def test_the_pipeline_and_the_runbook_use_the_environments_state_keys():
    workflow = (ROOT / ".github" / "workflows" / "deploy-environment.yml").read_text(
        encoding="utf-8"
    )
    used = set(re.findall(r"key=([\w/.${} -]+\.tfstate)", workflow))
    assert used == {"vigilwatch/envs/${{ inputs.environment }}.tfstate"}, used
    for env, key in state_keys().items():
        assert key == f"vigilwatch/envs/{env}.tfstate", "the workflow derives keys this way"
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    named = set(re.findall(r"vigilwatch/[\w/.-]+\.tfstate", runbook))
    assert named and named <= set(state_keys().values()), named


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


@pytest.mark.parametrize("env", ENVS)
def test_every_enabled_alarm_is_one_the_monitoring_module_knows(env):
    alarms = set(tfvars(env)["enabled_alarms"])
    assert alarms <= KNOWN_ALARMS, alarms - KNOWN_ALARMS


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


def _lock_hashes(path: Path) -> dict[str, set[str]]:
    text = path.read_text(encoding="utf-8")
    return {
        provider: set(re.findall(r'"(h1:[^"]+)"', block))
        for provider, block in re.findall(r'provider "([^"]+)" \{(.*?)\n\}', text, re.S)
    }


def test_every_committed_lock_file_can_verify_the_provider_on_every_platform_we_use():
    """CI reuses providers from a cache of unpacked plugins, which Terraform verifies with the
    platform's h1 hash only. A lock file written on one OS has just that OS's h1 hash, and CI on
    Linux then fails with 'doesn't match any of the checksums' (it did, for bootstrap)."""
    locks = sorted(TF.glob("*/.terraform.lock.hcl")) + sorted(TF.glob("envs/*/.terraform.lock.hcl"))
    assert {p.parent.name for p in locks} >= {"bootstrap", "dev", "prod"}
    hashes = {p.relative_to(TF).as_posix(): _lock_hashes(p) for p in locks}
    reference = hashes["envs/prod/.terraform.lock.hcl"]
    assert all(len(h) >= 4 for h in reference.values()), "linux, windows and two darwin builds"
    for name, found in hashes.items():
        for provider, needed in reference.items():
            missing = needed - found.get(provider, set())
            assert not missing, f"{name} cannot verify {provider} on every platform: {missing}"


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


def _bootstrap_statement(sid: str) -> str:
    text = (TF / "bootstrap" / "main.tf").read_text(encoding="utf-8")
    block = re.search(rf'Sid\s*=\s*"{sid}"(.*?)\n\s*\}}', text, re.S)
    assert block, f"bootstrap has no {sid} statement"
    return block.group(1)


def _bootstrap_resources(sid: str) -> list[str]:
    """The literal ARNs of one statement, with the account and prefix filled in."""
    arns = re.findall(r'"(arn:aws:[^"]+)"', _bootstrap_statement(sid))
    account = "${data.aws_caller_identity.current.account_id}"
    return [
        a.replace(account, "123456789012").replace("${local.project_name}", "vigilwatch")
        for a in arns
    ]


def _bootstrap_s3_resources() -> list[str]:
    return _bootstrap_resources("FrontendBucketOnly")


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


@pytest.mark.security
def test_the_deploy_role_trusts_main_and_the_approved_production_environment_only():
    """Jobs on main assume the role as ref:refs/heads/main. A job that declares a GitHub
    environment assumes it as environment:<name>, from any branch, so an environment the role
    trusts must itself be gated: production waits for a reviewer. An unreviewed `development`
    environment would hand the write role to any branch."""
    text = (TF / "bootstrap" / "main.tf").read_text(encoding="utf-8")
    block = re.search(r'resource "aws_iam_role" "deploy"(.*?)\n\}', text, re.S).group(1)
    subjects = set(re.findall(r'"repo:\$\{var\.github_repository\}:([^"]+)"', block))
    assert subjects == {"ref:refs/heads/main", "environment:production"}


def _plan_role() -> tuple[str, str]:
    text = (TF / "bootstrap" / "main.tf").read_text(encoding="utf-8")
    role = re.search(r'resource "aws_iam_role" "plan"(.*?)\n\}', text, re.S)
    policy = re.search(r'resource "aws_iam_role_policy" "plan"(.*?)\n\}', text, re.S)
    assert role and policy, "bootstrap has no read-only plan role"
    return role.group(1), policy.group(1)


@pytest.mark.security
def test_pull_requests_and_drift_checks_get_a_separate_read_only_role():
    """A pull request's code is not reviewed yet: it may read, never change, the account."""
    role, policy = _plan_role()
    assert '"vigilwatch-github-plan"' in role
    subjects = set(re.findall(r'"repo:\$\{var\.github_repository\}:([^"]+)"', role))
    assert subjects == {"pull_request", "ref:refs/heads/main"}
    actions = re.findall(r'"([a-z0-9-]+:[A-Za-z*]+)"', policy)
    assert actions, "the plan role grants nothing"
    read_only = re.compile(r"^[a-z0-9-]+:(Get|List|Describe|Head)[A-Za-z]*\*?$|^apigateway:GET$")
    writes = [a for a in actions if not read_only.match(a)]
    assert writes == [], f"the plan role may only read: {writes}"
    assert "Deny" not in policy, "read-only by construction, not by exception"


def test_the_plan_role_is_an_output_for_the_repository_variable():
    outputs = (TF / "bootstrap" / "outputs.tf").read_text(encoding="utf-8")
    assert 'output "plan_role_arn"' in outputs and "AWS_PLAN_ROLE_ARN" in outputs


@pytest.mark.security
def test_the_deploy_role_cannot_edit_its_own_permissions():
    """Its own name is vigilwatch-github-deploy: a vigilwatch-* grant would let a pipeline run
    attach '*' to itself and become account admin."""
    import fnmatch

    deploy_role = "arn:aws:iam::123456789012:role/vigilwatch-github-deploy"
    granted = _bootstrap_resources("OwnRolesOnly")
    assert not any(fnmatch.fnmatchcase(deploy_role, r) for r in granted), granted
    deny = _bootstrap_statement("NeverItself")
    assert re.search(r'Effect\s*=\s*"Deny"', deny), "belt and braces: an explicit deny on itself"
    assert '"iam:*"' in deny and "aws_iam_role.deploy.arn" in deny


@pytest.mark.parametrize("env", ENVS)
def test_the_deploy_role_may_manage_each_environments_function_roles(env):
    import fnmatch

    granted = _bootstrap_resources("OwnRolesOnly")
    for fn in ("uptime-check", "register-endpoint", "get-checks"):
        role = f"arn:aws:iam::123456789012:role/vigilwatch-{env}-{fn}"
        assert any(fnmatch.fnmatchcase(role, r) for r in granted), (role, granted)


def test_the_deploy_role_s3_grant_stays_inside_this_projects_buckets():
    for resource in _bootstrap_s3_resources():
        assert resource.startswith("arn:aws:s3:::vigilwatch-"), resource
        assert "-frontend-123456789012" in resource, resource


# ---- Every setting of an environment can be changed from that environment ----------------------

# Set by the environment root itself, not by the operator. project_name stays at the module default:
# the bootstrap deploy role and the provider's Project tag are tied to "vigilwatch", so another
# prefix would plan cleanly and then fail with AccessDenied on apply.
FIXED_BY_THE_ROOT = {"frontend_dir", "project_name"}


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


@pytest.mark.parametrize("env", ENVS)
def test_an_environment_cannot_rename_the_project(env):
    """Only the bootstrap stack may choose the prefix, because its deploy role is scoped to it."""
    base = TF / "envs" / env
    assert "project_name" not in _declared(base / "variables.tf")
    assert "project_name" not in (base / "main.tf").read_text(encoding="utf-8")


def test_bootstrap_cannot_choose_a_prefix_the_environments_do_not_use():
    """The environments always use the module default; a different bootstrap prefix would scope
    the deploy role to names nothing creates, and the first apply would fail with AccessDenied."""
    assert "project_name" not in _declared(TF / "bootstrap" / "variables.tf")
    stack = (TF / "modules" / "vigilwatch" / "variables.tf").read_text(encoding="utf-8")
    default = re.search(r'variable "project_name"\s*\{[^}]*default\s*=\s*"([^"]+)"', stack, re.S)
    bootstrap = (TF / "bootstrap" / "main.tf").read_text(encoding="utf-8")
    assert re.search(rf'project_name\s*=\s*"{default.group(1)}"', bootstrap), "same prefix"


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


def _section(runbook: str, heading: str) -> str:
    start = runbook.index(heading)
    end = runbook.find("\n## ", start + len(heading))
    return runbook[start : end if end != -1 else None]


def test_the_urgent_rollback_keeps_the_alert_email_subscription():
    """Without notification_email the plan deletes prod's SNS email subscription mid-incident."""
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    rollback = _section(runbook, "## 6. Rollback")
    plans = [line for line in rollback.splitlines() if line.strip().startswith("terraform plan")]
    assert plans, "the rollback has no terraform plan"
    for line in plans:
        assert "notification_email" in line, line


# The root module of the old stack, as on main before this branch (terraform/variable.tf and
# provider.tf there). Retiring it runs in that checkout, where only these variables exist.
OLD_STACK_VARIABLES = {
    "aws_region",
    "vpc_cidr",
    "project_name",
    "check_interval_minutes",
    "notification_email",
}


def test_retiring_the_old_stack_only_passes_variables_the_old_stack_declares():
    """Terraform refuses an undeclared -var, so the retirement would stop at its first command."""
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    section = _section(runbook, "## 2. Migrating an existing deployment")
    commands = [
        line.strip() for line in section.splitlines() if line.strip().startswith("terraform")
    ]
    assert any("destroy" in c for c in commands), "the section must still retire the old stack"
    passed = {name for c in commands for name in re.findall(r"-var[ =]'?(\w+)=", c)}
    assert passed <= OLD_STACK_VARIABLES, sorted(passed - OLD_STACK_VARIABLES)


@pytest.mark.parametrize("heading", ["## 3. First deploy"])
def test_paths_in_runbook_commands_exist_from_the_directory_they_run_in(heading):
    """Follow each `cd` in the section's commands and check every tests/ path from there."""
    runbook = (ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
    cwd, checked = ROOT, []
    for line in _section(runbook, heading).splitlines():
        command = line.split("#")[0].strip()
        if command.startswith("cd "):
            cwd = (cwd / command.split()[1]).resolve()
        for token in re.findall(r"(?:\.\./)*tests/[\w/]+", command):
            checked.append(token)
            assert (cwd / token).exists(), f"{token} does not exist from {cwd.relative_to(ROOT)}"
    assert checked, "the section runs no tests"
