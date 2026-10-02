"""Pipeline policy: quality gates on every change, safe and keyless deploys."""

import re
from pathlib import Path

import pytest
import yaml

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
    for cmd in ("terraform fmt -check", "init -backend=false", "terraform validate", "terraform test"):
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
    writers = [n for n, j in wf["jobs"].items() if j.get("permissions", {}).get("contents") == "write"]
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
