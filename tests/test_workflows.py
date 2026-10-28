"""Pipeline policy: quality gates on every change, safe and keyless deploys.

Layout (DevOps Stage 6): ci.yml on every change; deploy-dev.yml on main; promote-prod.yml and
rollback.yml by hand with approval; all three deploy through one reusable deploy-environment.yml.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.req("VW-017")

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
CONFIGURED = (
    "vars.AWS_DEPLOY_ROLE_ARN != '' && vars.AWS_ACCOUNT_ID != '' && vars.TF_STATE_BUCKET != ''"
)
REUSABLE = "./.github/workflows/deploy-environment.yml"


def load(name):
    path = WORKFLOWS / name
    assert path.exists(), f"{name} is missing"
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    data["on"] = data.get("on", data.get(True))  # YAML 1.1 parses `on:` as True
    return text, data


def steps_text(job):
    return "\n".join(str(s.get("run", "")) + " " + str(s.get("uses", "")) for s in job["steps"])


def all_workflows():
    return sorted(p.name for p in WORKFLOWS.glob("*.yml"))


@pytest.fixture(scope="module")
def ci():
    return load("ci.yml")


@pytest.fixture(scope="module")
def dev():
    return load("deploy-dev.yml")


@pytest.fixture(scope="module")
def promote():
    return load("promote-prod.yml")


@pytest.fixture(scope="module")
def rollback():
    return load("rollback.yml")


@pytest.fixture(scope="module")
def deploy():
    """The reusable workflow every environment is deployed through."""
    return load("deploy-environment.yml")


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


def test_ci_checks_every_module_and_every_environment(ci):
    text, _ = ci
    assert "terraform/modules/*" in text and "terraform/envs/*" in text
    assert "terraform fmt -check -recursive terraform" in text


def test_the_python_job_installs_terraform_for_the_policy_enforcement_tests(ci):
    """tests/mock/test_iam_policies.py renders the real policies with terraform: no skipping."""
    _, wf = ci
    steps = wf["jobs"]["python"]["steps"]
    uses = [s.get("uses", "") for s in steps]
    setup = next(i for i, u in enumerate(uses) if u.startswith("hashicorp/setup-terraform"))
    pytest_step = next(i for i, s in enumerate(steps) if "pytest" in str(s.get("run", "")))
    assert setup < pytest_step, "terraform must be installed before pytest runs"
    assert steps[setup]["with"]["terraform_wrapper"] is False, "the wrapper adds output to stdout"


def test_the_free_tier_is_checked_once_by_the_test_suite_not_again_by_a_ci_step(ci):
    """tests/unit/test_free_tier_budget.py runs the command on the repository in every job that
    runs pytest; a second CI step computes the same answer."""
    text, _ = ci
    assert "free_tier_budget.py" not in text


def test_each_job_saves_its_own_provider_cache_entry(ci):
    """Two jobs saving one key race, and one save fails with 'Unable to reserve cache'."""
    _, wf = ci
    keys = []
    for job in ("python", "terraform"):
        cache = next(s for s in wf["jobs"][job]["steps"] if "actions/cache@" in s.get("uses", ""))
        keys.append(cache["with"]["key"])
    assert len(set(keys)) == 2, keys


def test_ci_verifies_the_bundle_inside_the_lambda_runtime_image(ci):
    """Lessons 3 and 4: run the package where Lambda runs it, not only from the repository."""
    _, wf = ci
    steps = wf["jobs"]["package"]["steps"]
    text = steps_text(wf["jobs"]["package"])
    assert "scripts/build_bundle.py" in text
    run = next(s["run"] for s in steps if "docker run" in str(s.get("run", "")))
    assert "public.ecr.aws/lambda/python:3.12" in run
    assert "verify_package.py" in run and ":ro" in run, "the bundle is mounted read-only"
    assert "--network none" in run, "verification needs no network, so it gets none"


@pytest.mark.parametrize("job", ["python", "terraform"])
def test_terraform_providers_come_from_a_cache_between_runs(ci, job):
    """Module lock files are not committed, so without a cache every run downloads the AWS
    provider, hundreds of MB, before any test starts."""
    _, wf = ci
    env = {**wf.get("env", {}), **wf["jobs"][job].get("env", {})}
    assert env.get("TF_PLUGIN_CACHE_DIR"), f"{job} sets no plugin cache directory"
    steps = wf["jobs"][job]["steps"]
    cache = next(
        (i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/cache@")),
        None,
    )
    assert cache is not None, f"{job} restores no cache"
    assert "TF_PLUGIN_CACHE_DIR" in str(steps[cache]["with"]["path"])
    first_use = next(
        i for i, s in enumerate(steps) if re.search(r"pytest|terraform init", str(s.get("run", "")))
    )
    assert cache < first_use, f"{job} must restore the cache before terraform runs"


# ---- The DevOps layout ------------------------------------------------------------------------


def test_the_single_deploy_workflow_is_split_into_the_devops_layout():
    assert not (WORKFLOWS / "deploy.yml").exists(), "replaced by deploy-dev and promote-prod"
    expected = {
        "ci.yml",
        "deploy-dev.yml",
        "promote-prod.yml",
        "rollback.yml",
        "deploy-environment.yml",
    }
    assert expected <= set(all_workflows())


def test_dev_deploys_every_push_to_main_after_ci(dev):
    """By hand too: the first deploy after the repository variables are set has no new push."""
    _, wf = dev
    assert set(wf["on"]) == {"push", "workflow_dispatch"}
    assert wf["on"]["push"]["branches"] == ["main"]
    assert wf["jobs"]["ci"]["uses"] == "./.github/workflows/ci.yml"
    job = wf["jobs"]["deploy"]
    assert job["uses"] == REUSABLE
    assert "ci" in job["needs"]
    assert job["with"] == {"environment": "dev", "sha": "${{ github.sha }}", "build": True}


def test_prod_is_only_ever_deployed_by_hand(promote, rollback):
    for _, wf in (promote, rollback):
        assert set(wf["on"]) == {"workflow_dispatch"}


def test_promotion_deploys_the_commit_dev_last_released_and_its_stored_bundle(promote):
    _, wf = promote
    assert wf["on"]["workflow_dispatch"]["inputs"]["sha"]["required"] is False
    job = wf["jobs"]["deploy"]
    assert job["uses"] == REUSABLE
    assert job["with"]["environment"] == "prod"
    assert job["with"]["sha"] == "${{ needs.resolve.outputs.sha }}"
    assert job["with"]["require_dev_release"] is True
    assert job["with"].get("build", False) is False, "prod never builds: it deploys dev's bytes"
    assert 'scripts/release.sh "$BUCKET" dev' in steps_text(wf["jobs"]["resolve"])


def test_rollback_redeploys_a_given_commit_through_the_same_approval(rollback):
    _, wf = rollback
    assert wf["on"]["workflow_dispatch"]["inputs"]["sha"]["required"] is True
    job = wf["jobs"]["deploy"]
    assert job["uses"] == REUSABLE
    assert job["with"] == {
        "environment": "prod",
        "sha": "${{ inputs.sha }}",
        "require_dev_release": False,
    }


def test_each_environment_deploys_one_run_at_a_time_and_never_cancels_an_apply(
    dev, promote, rollback
):
    groups = {}
    for name, (_, wf) in {"dev": dev, "promote": promote, "rollback": rollback}.items():
        assert wf["concurrency"]["cancel-in-progress"] is False, name
        groups[name] = wf["concurrency"]["group"]
    # A dispatch from another branch fails at its first step; until then it must not take the
    # prod queue's pending slot, which would cancel a real deploy waiting there.
    isolated = "deploy-prod-${{ github.ref }}"
    assert groups["promote"] == groups["rollback"] == isolated, "one queue for prod, main only"
    assert groups["dev"] == isolated.replace("deploy-prod", "deploy-dev")


@pytest.mark.parametrize("name", ["deploy-dev.yml", "promote-prod.yml", "rollback.yml"])
def test_callers_grant_the_reusable_workflow_only_what_it_needs(name):
    _, wf = load(name)
    deploy = wf["jobs"]["deploy"]
    assert deploy["permissions"] == {"contents": "read", "id-token": "write"}
    assert CONFIGURED in str(deploy["if"]), "skipped, not failed, until the repository is set up"


# ---- The reusable deployment ------------------------------------------------------------------


def test_the_reusable_workflow_takes_an_environment_and_a_commit(deploy):
    _, wf = deploy
    inputs = wf["on"]["workflow_call"]["inputs"]
    assert {"environment", "sha", "build", "require_dev_release"} <= set(inputs)
    assert inputs["environment"]["required"] and inputs["sha"]["required"]
    assert inputs["build"]["default"] is False and inputs["require_dev_release"]["default"] is False


def test_inputs_are_validated_before_anything_else_runs(deploy):
    _, wf = deploy
    first = wf["jobs"]["plan"]["steps"][0]
    assert "dev|prod" in first["run"] and "[0-9a-f]{40}" in first["run"]
    assert "${{" not in first["run"], "inputs reach the shell through env, never inline"


def test_the_commit_is_what_gets_checked_out_planned_and_applied(deploy):
    _, wf = deploy
    checkout = next(
        s for s in wf["jobs"]["plan"]["steps"] if "actions/checkout" in s.get("uses", "")
    )
    assert checkout["with"]["ref"] == "${{ inputs.sha }}"
    text = steps_text(wf["jobs"]["plan"])
    assert "git merge-base --is-ancestor" in text, "prod deploys only commits that are on main"


def test_dev_builds_and_stores_the_bundle_prod_fetches_those_bytes(deploy):
    _, wf = deploy
    steps = wf["jobs"]["plan"]["steps"]
    build = next(s for s in steps if "scripts/build_bundle.py --out" in str(s.get("run", "")))
    fetch = next(s for s in steps if "Fetch" in s.get("name", ""))
    assert build["if"] == "${{ inputs.build }}" and fetch["if"] == "${{ !inputs.build }}"
    assert "bundles/" in build["run"] and "aws s3 cp" in build["run"]
    assert "cmp" in build["run"], "a stored bundle with other bytes means the build drifted"
    assert "bundles/" in fetch["run"]
    assert "tfvars.json" in steps_text(wf["jobs"]["plan"]), "the Terraform variables are written"


def test_promotion_refuses_anything_but_what_dev_last_released(deploy):
    _, wf = deploy
    check = next(
        s for s in wf["jobs"]["plan"]["steps"] if s.get("if") == "${{ inputs.require_dev_release }}"
    )
    assert 'scripts/release.sh "$BUCKET" dev' in check["run"] and "exit 1" in check["run"]


def test_apply_requires_approval_for_prod_and_uses_the_reviewed_plan(deploy):
    text, wf = deploy
    apply = wf["jobs"]["apply"]
    # Dev applies run as main, in no environment; prod waits in "production" for a reviewer.
    assert apply["environment"] == "${{ inputs.environment == 'prod' && 'production' || '' }}"
    assert "plan" in apply["needs"]
    assert re.search(r"terraform apply .*tfplan", steps_text(apply))
    assert "-out=tfplan" in steps_text(wf["jobs"]["plan"])
    assert "build_bundle.py --out" not in steps_text(apply), "apply deploys the planned bundle"


def test_each_environment_uses_its_own_directory_and_state_key(deploy):
    text, wf = deploy
    assert wf["jobs"]["plan"]["defaults"]["run"]["working-directory"] == (
        "terraform/envs/${{ inputs.environment }}"
    )
    assert "key=vigilwatch/envs/${{ inputs.environment }}.tfstate" in text


def test_a_successful_deploy_is_recorded_only_after_its_smoke_test(deploy):
    _, wf = deploy
    record = wf["jobs"]["record"]
    assert "smoke" in record["needs"]
    assert "releases/" in steps_text(record)


def test_the_smoke_test_is_its_own_job_so_it_can_be_rerun_without_reapplying(deploy):
    """Re-running a job that holds `terraform apply tfplan` fails: the saved plan is stale."""
    _, wf = deploy
    apply, smoke = wf["jobs"]["apply"], wf["jobs"]["smoke"]
    assert "pytest" not in steps_text(apply)
    assert "terraform" not in steps_text(smoke)
    assert "apply" in smoke["needs"]
    assert "id-token" not in smoke.get("permissions", {}), "the smoke test needs no AWS access"
    assert {"api_base_url", "dashboard_url"} <= set(apply["outputs"])


def test_the_run_summary_links_the_deployed_dashboard(deploy):
    """The environment no longer carries a url (dev runs in none), so the summary does."""
    _, wf = deploy
    step = next(s for s in wf["jobs"]["apply"]["steps"] if s.get("id") == "outputs")
    assert "GITHUB_STEP_SUMMARY" in step["run"] and "dashboard_url" in step["run"]


def test_post_deploy_cache_invalidation(deploy):
    _, wf = deploy
    assert "cloudfront create-invalidation" in steps_text(wf["jobs"]["apply"])


def test_the_production_smoke_test_is_read_only_and_given_a_url_it_can_read(deploy):
    _, wf = deploy
    smoke = next(s for s in wf["jobs"]["smoke"]["steps"] if "pytest" in str(s.get("run")))
    assert "--env=${{ inputs.environment }}" not in smoke["run"], "env comes through env vars"
    assert smoke["env"]["E2E_READONLY_URL"] == "${{ vars.E2E_READONLY_URL }}"
    assert '--env="$ENVIRONMENT"' in smoke["run"]
    check = next(s for s in wf["jobs"]["smoke"]["steps"] if "run" in s)
    assert "E2E_READONLY_URL" in check["run"] and "::error" in check["run"]
    assert check["if"] == "${{ inputs.environment == 'prod' }}"


def test_the_smoke_test_gets_the_address_of_the_environment_just_applied_only(deploy):
    """The harness reads API_URL_<ENV> before API_URL. Setting both DEV and PROD names to one
    address hid which environment a run was meant for; the generic names say just that."""
    _, wf = deploy
    smoke = next(s for s in wf["jobs"]["smoke"]["steps"] if "pytest" in str(s.get("run")))
    addresses = {k: v for k, v in smoke["env"].items() if k.startswith(("API_URL", "DASHBOARD"))}
    assert addresses == {
        "API_URL": "${{ needs.apply.outputs.api_base_url }}",
        "DASHBOARD_URL": "${{ needs.apply.outputs.dashboard_url }}",
    }


def _collected(markers: str) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
        + ["-m", markers, "tests/e2e"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return int(re.search(r"(\d+)(?:/\d+)? tests? collected", result.stdout).group(1))


def test_the_smoke_gate_fails_on_any_skip_or_a_short_run(deploy):
    """Prod runs only the read-only smoke tests and dev runs all of them; in both, a skipped or
    missing test turns the job red (CI gate integrity). The minimum is what the deployed commit
    collects, not a number in today's workflow: a rollback runs an older commit's tests."""
    _, wf = deploy
    smoke = next(s for s in wf["jobs"]["smoke"]["steps"] if "pytest" in str(s.get("run")))
    assert (
        smoke["env"]["MARKERS"] == "${{ inputs.environment == 'prod' && 'e2e and smoke' || 'e2e' }}"
    )
    assert "MIN_TESTS" not in smoke["env"] and "--min-tests" not in smoke["run"]
    lines = smoke["run"].splitlines()
    collect = next(i for i, line in enumerate(lines) if "--collect-only" in line)
    run_tests = next(i for i, line in enumerate(lines) if "--junitxml=" in line)
    gate = next(i for i, line in enumerate(lines) if "scripts/check_junit.py" in line)
    assert collect < run_tests < gate
    assert '-m "$MARKERS"' in lines[collect] and '-m "$MARKERS"' in lines[run_tests]
    assert "> collected.txt" in lines[collect] and "--collected collected.txt" in lines[gate]
    assert _collected("e2e and smoke") >= 1, "prod needs read-only smoke tests"


def test_the_gate_counts_what_pytest_actually_collects(tmp_path):
    """check_junit reads pytest's own --collect-only -q output, so the two must agree."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_junit

    for markers in ("e2e and smoke", "e2e"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
            + ["-m", markers, "tests/e2e"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        listing = tmp_path / "collected.txt"
        listing.write_text(result.stdout, encoding="utf-8")
        assert check_junit.collected(listing) == _collected(markers), markers


@pytest.mark.negative
def test_a_smoke_run_without_an_address_is_red_in_ci():
    """The mutation check for the gate: an unset API_URL must fail, not skip."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("API_URL", "DASHBOARD_URL"))}
    env["CI"] = "true"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        + ["-m", "e2e and smoke", "tests/e2e", "--env=prod"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, result.stdout[-500:]
    assert "skipped" not in result.stdout.splitlines()[-1]


@pytest.mark.parametrize("name", all_workflows())
def test_no_workflow_can_quietly_ignore_a_failure_or_skip_a_review(name):
    text, _ = load(name)
    for forbidden in ("continue-on-error", "|| true", "-auto-approve", "set +e"):
        assert forbidden not in text, f"{name} uses {forbidden}"


def test_each_deploy_shows_the_release_checklist_before_and_after(deploy):
    _, wf = deploy
    assert "python scripts/checklist.py pre" in steps_text(wf["jobs"]["plan"])
    assert "python scripts/checklist.py post" in steps_text(wf["jobs"]["smoke"])


def test_the_deploy_pins_the_account_in_terraform(deploy):
    _, wf = deploy
    assert "allowed_account_ids" in steps_text(wf["jobs"]["plan"])


# ---- Promotion and release ---------------------------------------------------------------------


def test_only_the_prod_release_can_write_contents():
    writers = []
    for name in all_workflows():
        _, wf = load(name)
        for job_name, job in wf["jobs"].items():
            if job.get("permissions", {}).get("contents") == "write":
                writers.append(f"{name}:{job_name}")
    assert writers == ["promote-prod.yml:release"]


def test_a_release_is_tagged_only_after_prod_passed_its_smoke_test(promote):
    _, wf = promote
    assert "deploy" in wf["jobs"]["release"]["needs"]


def test_the_release_notes_are_the_changelog_since_the_previous_release(promote):
    _, wf = promote
    text = steps_text(wf["jobs"]["release"])
    assert "git describe --tags --abbrev=0" in text, "notes start after the previous release"
    assert "scripts/changelog.py" in text
    assert "gh release create" in text and "--notes-file" in text
    assert "--generate-notes" not in text


def test_the_release_tag_is_the_next_free_one_not_the_run_number(promote):
    """github.run_number restarts when a workflow is renamed, and v2.<n> may already exist."""
    text, wf = promote
    assert "run_number" not in text
    assert "scripts/next_version.py" in steps_text(wf["jobs"]["release"])


# ---- Plan on pull requests ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def pr_plan():
    return load("pr-plan.yml")


def test_every_pull_request_from_this_repository_gets_a_dev_plan(pr_plan):
    _, wf = pr_plan
    assert set(wf["on"]) == {"pull_request"}
    plan = wf["jobs"]["plan"]
    guard = str(plan["if"])
    assert "github.event.pull_request.head.repo.full_name == github.repository" in guard
    assert "vars.AWS_PLAN_ROLE_ARN != ''" in guard
    assert plan["defaults"]["run"]["working-directory"] == "terraform/envs/dev"


@pytest.mark.security
def test_the_pull_request_path_can_read_but_never_change_anything(pr_plan):
    text, wf = pr_plan
    plan = wf["jobs"]["plan"]
    assert plan["permissions"] == {"contents": "read", "id-token": "write"}
    assert "vars.AWS_PLAN_ROLE_ARN" in text and "AWS_DEPLOY_ROLE_ARN" not in text
    assert "terraform apply" not in text
    assert "-lock=false" in steps_text(plan), "a read-only role cannot take the state lock"
    assert "-detailed-exitcode" in steps_text(plan)


def test_the_plan_is_posted_by_a_job_that_holds_no_aws_access(pr_plan):
    _, wf = pr_plan
    comment = wf["jobs"]["comment"]
    assert comment["permissions"] == {"pull-requests": "write"}
    assert "plan" in comment["needs"]
    assert "gh pr comment" in steps_text(comment)


# ---- Drift -------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def drift():
    return load("drift.yml")


def test_drift_is_checked_weekly_in_every_environment(drift):
    _, wf = drift
    assert {"schedule", "workflow_dispatch"} == set(wf["on"])
    detect = wf["jobs"]["detect"]
    assert detect["strategy"]["matrix"]["environment"] == ["dev", "prod"]
    assert detect["strategy"]["fail-fast"] is False, "drift in one must not hide the other"


@pytest.mark.security
def test_drift_detection_only_reads(drift):
    text, wf = drift
    detect = wf["jobs"]["detect"]
    assert detect["permissions"] == {"contents": "read", "id-token": "write"}
    assert "vars.AWS_PLAN_ROLE_ARN" in text and "AWS_DEPLOY_ROLE_ARN" not in text
    plan = steps_text(detect)
    for flag in ("-refresh-only", "-detailed-exitcode", "-lock=false"):
        assert flag in plan, flag
    assert "terraform apply" not in text


def test_drift_compares_against_what_was_actually_released(drift):
    _, wf = drift
    plan = steps_text(wf["jobs"]["detect"])
    assert 'scripts/release.sh "$BUCKET" "$ENVIRONMENT"' in plan
    assert "bundles/" in plan and "tfvars.json" in plan


def test_drift_opens_an_issue_from_a_job_that_holds_no_aws_access(drift):
    """issues: write on the reporting job only (DevOps 6.5)."""
    _, wf = drift
    report = wf["jobs"]["report"]
    assert report["permissions"] == {"issues": "write"}
    assert "detect" in report["needs"]
    text = steps_text(report)
    assert "gh issue create" in text and "gh issue list" in text, "one open issue, not one a week"


# ---- Every workflow -----------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.parametrize("name", all_workflows())
def test_the_only_github_environment_is_the_reviewed_production_one(name):
    """The deploy role trusts environment:production from any branch; any other environment
    would need its own trust, and an unreviewed one would be a way around main."""
    text, wf = load(name)
    assert "development" not in text
    for job_name, job in wf["jobs"].items():
        environment = job.get("environment")
        if environment is not None:
            assert "production" in str(environment), f"{name}:{job_name} uses {environment}"


@pytest.mark.parametrize("name", all_workflows())
def test_every_job_has_a_timeout(name):
    """The default is six hours: a hung apply would hold the deploy queue and the state lock."""
    _, wf = load(name)
    for job_name, job in wf["jobs"].items():
        if "uses" in job:
            continue  # a call: the called workflow's jobs carry their own
        assert 1 <= job.get("timeout-minutes", 0) <= 60, f"{name}:{job_name}"


# The first step of every job a dispatch starts with: deploy-environment.yml's plan (called by
# deploy-dev, promote-prod and rollback), promote-prod's resolve, and drift's detect.
BRANCH_GUARDS = [
    ("deploy-environment.yml", "plan"),
    ("promote-prod.yml", "resolve"),
    ("drift.yml", "detect"),
]


@pytest.mark.parametrize("name, job", BRANCH_GUARDS)
def test_deploys_and_drift_refuse_to_run_from_another_branch(name, job):
    """workflow_dispatch can start any branch's copy of a workflow. Role trust, the commit check
    and the production branch rule already stop it; this stops it first, and in red: a skipped
    run would let someone believe a rollback happened."""
    _, wf = load(name)
    first = wf["jobs"][job]["steps"][0]
    assert first["env"]["REF"] == "${{ github.ref }}"
    assert '"$REF" != "refs/heads/main"' in first["run"] and "exit 1" in first["run"]


@pytest.mark.parametrize("name", all_workflows())
def test_a_wrong_branch_is_never_skipped_quietly(name):
    """A job skipped on the branch would hide that the guard inside never ran."""
    _, wf = load(name)
    assert "main-only" not in wf["jobs"]
    for job_name, job in wf["jobs"].items():
        assert "github.ref" not in str(job.get("if", "")), f"{name}:{job_name}: a skip is silent"


def test_ci_cancels_superseded_pull_request_and_branch_runs_but_never_mains(ci):
    """A pull request, or a push to a branch other than main, cancels its superseded run. A run
    on main (deploy-dev.yml calls CI) gets a group of its own: nothing a deploy waits on."""
    text, wf = ci
    group = wf["concurrency"]["group"]
    assert "github.event.pull_request.number" in group and "github.run_id" in group
    assert "github.ref != 'refs/heads/main' && github.ref" in group
    assert group.startswith("ci-${{ github.event_name }}-"), "a deploy's CI never meets a push's"
    assert wf["concurrency"]["cancel-in-progress"] is True
    assert "deploy.yml" not in text, "the stale pointer to the removed workflow"


def test_a_new_push_cancels_the_pull_request_plan_it_supersedes():
    """Otherwise an older plan can finish last and be the comment a reviewer reads."""
    _, wf = load("pr-plan.yml")
    assert "github.event.pull_request.number" in wf["concurrency"]["group"]
    assert wf["concurrency"]["cancel-in-progress"] is True


def test_the_apply_job_has_time_for_a_slow_cloudfront_change(deploy):
    """Hitting the timeout cancels terraform apply midway and can leave the state lock held."""
    _, wf = deploy
    assert wf["jobs"]["apply"]["timeout-minutes"] == 60


def test_the_terraform_linter_is_pinned(ci):
    _, wf = ci
    setup = next(s for s in wf["jobs"]["terraform"]["steps"] if "setup-tflint" in s.get("uses", ""))
    assert re.fullmatch(r"v\d+\.\d+\.\d+", setup["with"]["tflint_version"])


@pytest.mark.parametrize("name", all_workflows())
def test_every_step_runs_in_bash_with_pipefail(name):
    """Without `shell:`, GitHub runs `bash -e {0}`: a failure before the last command of a
    pipeline passes unnoticed. `shell: bash` adds -o pipefail, which tests/test_pipeline_scripts.py
    also uses, so the steps it runs behave as they do on GitHub."""
    _, wf = load(name)
    assert wf.get("defaults", {}).get("run", {}).get("shell") == "bash", name
    for job_name, job in wf["jobs"].items():
        run = job.get("defaults", {}).get("run", {})
        assert run.get("shell", "bash") == "bash", f"{name}:{job_name}"
        for step in job.get("steps", []):
            assert step.get("shell", "bash") == "bash", f"{name}:{job_name}:{step.get('name')}"


@pytest.mark.parametrize("name", all_workflows())
def test_the_bundle_digest_is_computed_with_openssl_not_parsed_from_json(name):
    text, _ = load(name)
    assert "json.load" not in text, f"{name}: hash the bundle with openssl instead"


# Options of scripts/build_bundle.py that every commit with a stored bundle has (both predate
# the first stored bundle). The deploy and drift jobs run the deployed commit's own copy of the
# script, so a newer option would break a rollback to, or the drift check of, an older release.
STABLE_BUILD_OPTIONS = {"--out", "--rev"}


def _commands(text: str) -> list[str]:
    """Shell lines with backslash continuations joined, so no option hides on a later line."""
    return re.sub(r"\\\n\s*", " ", text).splitlines()


def _build_calls(wf) -> list[str]:
    """Options passed to scripts/build_bundle.py, read from the parsed run blocks (so a folded
    `run: >` is one line) with backslash continuations joined."""
    calls = []
    for job in wf["jobs"].values():
        for step in job.get("steps", []):
            for line in _commands(str(step.get("run", ""))):
                calls += re.findall(r"scripts/build_bundle\.py(.*)", line)
    return calls


@pytest.mark.parametrize(
    "name, expect_calls", [("deploy-environment.yml", True), ("drift.yml", False)]
)
def test_the_deployed_commits_build_script_is_called_only_with_options_it_has(name, expect_calls):
    text, wf = load(name)
    calls = _build_calls(wf)
    assert bool(calls) is expect_calls, calls
    for options in calls:
        assert set(re.findall(r"--[a-z-]+", options)) <= STABLE_BUILD_OPTIONS, options
    assert "openssl dgst -sha256 -binary" in text, "the digest needs no script at all"


def test_the_rebuild_check_builds_the_deployed_commit_not_the_working_tree(deploy):
    text, _ = deploy
    rebuild = next(line for line in _commands(text) if "rebuilt/vigilwatch.zip" in line)
    assert '--rev "$SHA"' in rebuild and "--allow-dirty" not in rebuild


@pytest.mark.parametrize("name", all_workflows())
def test_no_workflow_has_static_credentials(name):
    text, _ = load(name)
    assert "aws-access-key-id" not in text and "AWS_SECRET_ACCESS_KEY" not in text


@pytest.mark.parametrize("name", all_workflows())
def test_top_level_permissions_are_read_only(name):
    _, wf = load(name)
    assert wf["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("name", all_workflows())
def test_every_job_that_assumes_a_role_first_proves_it_is_in_the_right_account(name):
    """allowed_account_ids stops Terraform; this stops every other AWS call before it runs."""
    _, wf = load(name)
    for job_name, job in wf["jobs"].items():
        steps = job.get("steps", [])
        assume = [
            i for i, s in enumerate(steps) if "configure-aws-credentials" in s.get("uses", "")
        ]
        for i in assume:
            guard = steps[i + 1]
            assert "aws sts get-caller-identity" in guard.get("run", ""), f"{job_name}"
            assert guard["env"]["EXPECTED"] == "${{ vars.AWS_ACCOUNT_ID }}", f"{job_name}"
            assert "exit 1" in guard["run"], f"{job_name}"


@pytest.mark.parametrize("name", all_workflows())
def test_no_workflow_can_destroy_infrastructure(name):
    text, _ = load(name)
    assert not re.search(r"terraform\s+destroy|-destroy\b", text)


@pytest.mark.parametrize("name", all_workflows())
def test_actions_are_pinned_to_versions(name):
    text, _ = load(name)
    for ref in re.findall(r"uses:\s*([^\s]+)", text):
        if ref.startswith("./"):
            continue
        assert "@" in ref and not ref.endswith(("@main", "@master")), ref


@pytest.mark.parametrize("name", all_workflows())
def test_terraform_version_supports_native_state_locking(name):
    text, _ = load(name)
    for version in re.findall(r"terraform_version:\s*\"?([\d.]+)", text):
        major, minor = (int(x) for x in version.split(".")[:2])
        assert (major, minor) >= (1, 10), version


def test_terraform_version_has_a_single_source_of_truth():
    pin_file = WORKFLOWS.parent.parent / ".terraform-version"
    assert pin_file.exists(), ".terraform-version is missing"
    pinned = pin_file.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned), pinned
    for name in all_workflows():
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        if "setup-terraform" not in text:
            continue
        versions = re.findall(r'TF_VERSION:\s*"([\d.]+)"', text)
        assert versions == [pinned], f"{name} pins {versions}, expected {pinned}"
