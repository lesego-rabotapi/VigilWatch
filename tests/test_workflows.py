"""Pipeline policy: quality gates on every change, safe and keyless deploys."""

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.req("VW-017")

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def load(name):
    path = WORKFLOWS / name
    assert path.exists(), f"{name} is missing"
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    data["on"] = data.get("on", data.get(True))  # YAML 1.1 parses `on:` as True
    return text, data


def steps_text(job):
    return "\n".join(str(s.get("run", "")) + " " + str(s.get("uses", "")) for s in job["steps"])


@pytest.fixture(scope="module")
def ci():
    return load("ci.yml")


@pytest.fixture(scope="module")
def deploy():
    return load("deploy.yml")


def test_legacy_pipeline_is_gone():
    assert not (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8").count("AWS_ACCESS_KEY_ID")


# ---- CI ------------------------------------------------------------------


def test_ci_runs_on_pull_requests_pushes_and_as_reusable_workflow(ci):
    _, wf = ci
    assert {"pull_request", "push", "workflow_call"} <= set(wf["on"])


def test_ci_is_read_only(ci):
    _, wf = ci
    assert wf["permissions"] == {"contents": "read"}


def test_ci_python_gate(ci):
    _, wf = ci
    text = "\n".join(steps_text(j) for j in wf["jobs"].values())
    assert "ruff check" in text
    assert "ruff format --check" in text
    assert re.search(r"pytest .*--cov", text)


def test_ci_terraform_gate(ci):
    _, wf = ci
    text = "\n".join(steps_text(j) for j in wf["jobs"].values())
    for cmd in (
        "terraform fmt -check",
        "init -backend=false",
        "terraform validate",
        "terraform test",
    ):
        assert cmd in text, cmd


def test_ci_frontend_and_security_gates(ci):
    _, wf = ci
    text = "\n".join(steps_text(j) for j in wf["jobs"].values())
    assert "npm ci" in text and "npm test" in text
    assert "gitleaks" in text
    assert "trivy" in text


# ---- Deploy --------------------------------------------------------------


def test_deploy_only_from_main(deploy):
    _, wf = deploy
    assert wf["on"]["push"]["branches"] == ["main"]


def test_deploy_reuses_ci_as_a_gate(deploy):
    _, wf = deploy
    assert wf["jobs"]["ci"]["uses"] == "./.github/workflows/ci.yml"
    assert "ci" in wf["jobs"]["plan"]["needs"]


def test_deploy_has_no_static_credentials(deploy):
    text, _ = deploy
    assert "aws-access-key-id" not in text
    assert "AWS_SECRET_ACCESS_KEY" not in text
    assert "role-to-assume" in text


def test_deploy_is_serialized(deploy):
    _, wf = deploy
    assert wf["concurrency"]["cancel-in-progress"] is False


def test_top_level_permissions_are_minimal(deploy):
    _, wf = deploy
    assert wf["permissions"] == {"contents": "read"}


def test_apply_requires_approval_and_uses_the_reviewed_plan(deploy):
    text, wf = deploy
    apply = wf["jobs"]["apply"]
    assert apply["environment"]["name"] == "production"
    assert "plan" in apply["needs"]
    assert "-auto-approve" not in text
    assert re.search(r"terraform apply .*tfplan", steps_text(apply))
    assert "terraform plan" in steps_text(wf["jobs"]["plan"])
    assert "-out=tfplan" in steps_text(wf["jobs"]["plan"])


def test_oidc_jobs_request_id_token(deploy):
    _, wf = deploy
    for name in ("plan", "apply"):
        assert wf["jobs"][name]["permissions"]["id-token"] == "write", name


def test_post_deploy_smoke_and_cache_invalidation(deploy):
    _, wf = deploy
    text = steps_text(wf["jobs"]["apply"])
    assert "cloudfront create-invalidation" in text
    assert "pytest -m e2e" in text


def test_only_release_job_can_write_contents(deploy):
    _, wf = deploy
    writers = [
        n for n, j in wf["jobs"].items() if j.get("permissions", {}).get("contents") == "write"
    ]
    assert writers == ["release"]
    assert "apply" in wf["jobs"]["release"]["needs"]


def test_terraform_version_supports_native_state_locking(deploy, ci):
    for text, _ in (deploy, ci):
        for version in re.findall(r"terraform_version:\s*\"?([\d.]+)", text):
            major, minor = (int(x) for x in version.split(".")[:2])
            assert (major, minor) >= (1, 10), version


def test_actions_are_pinned_to_versions(deploy, ci):
    for text, _ in (deploy, ci):
        for ref in re.findall(r"uses:\s*([^\s]+)", text):
            if ref.startswith("./"):
                continue
            assert "@" in ref and not ref.endswith(("@main", "@master")), ref


# ---- Toolchain pin ---------------------------------------------------------


def test_terraform_version_has_a_single_source_of_truth():
    pin_file = WORKFLOWS.parent.parent / ".terraform-version"
    assert pin_file.exists(), ".terraform-version is missing"
    pinned = pin_file.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned), pinned
    for name in ("ci.yml", "deploy.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        versions = re.findall(r'TF_VERSION:\s*"([\d.]+)"', text)
        assert versions == [pinned], f"{name} pins {versions}, expected {pinned}"


# ---- Unconfigured repositories ---------------------------------------------


def test_aws_jobs_are_skipped_not_failed_until_the_repository_is_configured(deploy):
    """A fresh merge must show 'skipped', not a red run, before bootstrap is done."""
    _, wf = deploy
    for name in ("plan", "apply", "release"):
        condition = str(wf["jobs"][name].get("if", ""))
        assert "vars.AWS_DEPLOY_ROLE_ARN" in condition, f"{name} has no configuration guard"
        assert "!=" in condition and "''" in condition, f"{name}: {condition}"


# ---- Modules, environments and the prebuilt bundle ---------------------------


def test_ci_checks_every_module_and_every_environment(ci):
    text, _ = ci
    assert "terraform/modules/*" in text and "terraform/envs/*" in text
    assert "terraform fmt -check -recursive terraform" in text


def test_no_workflow_can_destroy_infrastructure(deploy, ci):
    for text, _ in (deploy, ci):
        assert not re.search(r"terraform\s+destroy|-destroy\b", text)


def test_deploy_builds_the_bundle_once_and_apply_reuses_it(deploy):
    _, wf = deploy
    plan, apply = steps_text(wf["jobs"]["plan"]), steps_text(wf["jobs"]["apply"])
    assert "scripts/build_bundle.py" in plan
    assert "bundle_sha256" in plan
    assert "build_bundle" not in apply, "apply must deploy the bundle the plan was made with"


def test_deploy_names_the_environment_and_pins_the_account(deploy):
    text, wf = deploy
    assert "terraform/envs/prod" in text
    assert "allowed_account_ids" in steps_text(wf["jobs"]["plan"])
    assert "vars.AWS_ACCOUNT_ID" in text


def test_the_python_job_installs_terraform_for_the_policy_enforcement_tests(ci):
    """tests/mock/test_iam_policies.py renders the real policies with terraform: no skipping."""
    _, wf = ci
    steps = wf["jobs"]["python"]["steps"]
    uses = [s.get("uses", "") for s in steps]
    setup = next(i for i, u in enumerate(uses) if u.startswith("hashicorp/setup-terraform"))
    pytest_step = next(i for i, s in enumerate(steps) if "pytest" in str(s.get("run", "")))
    assert setup < pytest_step, "terraform must be installed before pytest runs"
    assert steps[setup]["with"]["terraform_wrapper"] is False, "the wrapper adds output to stdout"


def test_a_half_configured_repository_skips_instead_of_failing(deploy):
    """The plan needs both the role and the account id; missing either must mean 'skipped'."""
    _, wf = deploy
    for name in ("plan", "apply", "release"):
        condition = str(wf["jobs"][name].get("if", ""))
        assert "vars.AWS_ACCOUNT_ID != ''" in condition, f"{name}: {condition}"


def test_the_production_smoke_test_is_read_only(deploy):
    """apply deploys prod: its smoke test must never register endpoints there."""
    _, wf = deploy
    smoke = next(s for s in wf["jobs"]["apply"]["steps"] if "pytest -m e2e" in str(s.get("run")))
    assert "--env=prod" in smoke["run"]
    assert "--env=dev" not in smoke["run"]
    assert set(smoke["env"]) == {"API_URL_PROD", "DASHBOARD_URL_PROD", "E2E_READONLY_URL"}


def test_the_production_smoke_test_is_given_a_url_it_can_read(deploy):
    """Prod is read-only, so it cannot register a URL to read back: one must be supplied, or the
    read test would skip on every deploy."""
    _, wf = deploy
    smoke = next(s for s in wf["jobs"]["apply"]["steps"] if "pytest -m e2e" in str(s.get("run")))
    assert smoke["env"]["E2E_READONLY_URL"] == "${{ vars.E2E_READONLY_URL }}"


def test_aws_jobs_also_wait_for_the_state_bucket(deploy):
    """Without it terraform init has no backend to use and the run fails instead of skipping."""
    _, wf = deploy
    for name in ("plan", "apply", "release"):
        condition = str(wf["jobs"][name].get("if", ""))
        assert "vars.TF_STATE_BUCKET != ''" in condition, f"{name}: {condition}"


def test_the_terraform_job_checks_the_free_tier_across_environments(ci):
    """terraform validate sees one environment at a time; the shared account needs the sum."""
    _, wf = ci
    assert "python scripts/free_tier_budget.py" in steps_text(wf["jobs"]["terraform"])
