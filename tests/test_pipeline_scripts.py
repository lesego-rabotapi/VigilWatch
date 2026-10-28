"""The shell the workflows run, executed against fakes of `aws` and `terraform`.

tests/test_workflows.py reads the workflow files. These tests run their steps the way GitHub
runs them (bash -eo pipefail), with fake commands that answer like the real ones, so a step that
only looks right is caught too.
"""

import base64
import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.req("VW-017")

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
BASH = shutil.which("bash")
SHA = "a" * 40
OTHER_SHA = "b" * 40

# A fake AWS CLI for the S3 calls the workflows make. RECORD is the content of the release
# record (unset: there is none). AWS_FAILS makes every call fail the way a wrong bucket or a
# missing permission does. Every call is logged to AWS_LOG; objects written from stdin are
# saved under AWS_WRITTEN; a download to a file copies FIXTURE.
FAKE_AWS = r"""
echo "$*" >> "$AWS_LOG"
if [ -n "${AWS_FAILS:-}" ]; then
  echo "An error occurred (AccessDenied) when calling the operation: Access Denied" >&2
  exit 254
fi
if [ "$1 $2" = "s3api list-objects-v2" ]; then
  while [ "$#" -gt 0 ]; do
    if [ "$1" = "--prefix" ]; then prefix="$2"; fi
    shift
  done
  if [ -n "${RECORD+set}" ]; then echo "$prefix"; else echo None; fi
  exit 0
fi
if [ "$1 $2" = "s3 cp" ]; then
  if [ "$3" = "-" ]; then
    cat > "$AWS_WRITTEN"
    echo "$4" >> "$AWS_WRITTEN.key"
  elif [ "$4" = "-" ]; then
    if [ -z "${RECORD+set}" ]; then
      echo "fatal error: An error occurred (404) when calling the HeadObject operation" >&2
      exit 1
    fi
    printf '%s' "$RECORD"
  else
    cp "$FIXTURE" "$4"
  fi
  exit 0
fi
echo "fake aws: unexpected call: $*" >&2
exit 2
"""

FAKE_PYTHON = 'exec "$PYTHON_UNDER_TEST" "$@"'


@dataclass
class Ran:
    status: int
    output: str
    outputs: dict
    env: dict
    summary: str
    tmp: Path


def find_step(workflow: str, job: str, name: str) -> dict:
    data = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    for step in data["jobs"][job]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"{workflow}:{job} has no step named {name!r}")


def _pairs(path: Path) -> dict:
    if not path.exists():
        return {}
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())


def run(script: str, tmp_path: Path, env=None, stubs=None, cwd=ROOT) -> Ran:
    """Run a step's script as GitHub does, with the fake commands first on PATH."""
    assert BASH, "bash is needed to run the workflow steps"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in {"aws": FAKE_AWS, "python": FAKE_PYTHON, **(stubs or {})}.items():
        path = bin_dir / name
        path.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8", newline="\n")
        path.chmod(0o755)
    script_path = tmp_path / "step.sh"
    script_path.write_text(script, encoding="utf-8", newline="\n")
    files = {
        "GITHUB_ENV": tmp_path / "github_env",
        "GITHUB_OUTPUT": tmp_path / "github_output",
        "GITHUB_STEP_SUMMARY": tmp_path / "summary.md",
    }
    full_env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "PYTHON_UNDER_TEST": os.environ.get("PYTHON_UNDER_TEST", shutil.which("python") or ""),
        "AWS_LOG": str(tmp_path / "aws.log"),
        "AWS_WRITTEN": str(tmp_path / "written"),
        "GITHUB_WORKSPACE": str(tmp_path),
        "BUCKET": "state-bucket",
        "SHA": SHA,
        **{key: str(path) for key, path in files.items()},
        **(env or {}),
    }
    result = subprocess.run(
        [BASH, "--noprofile", "--norc", "-eo", "pipefail", str(script_path)],
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    summary = files["GITHUB_STEP_SUMMARY"]
    return Ran(
        result.returncode,
        result.stdout + result.stderr,
        _pairs(files["GITHUB_OUTPUT"]),
        _pairs(files["GITHUB_ENV"]),
        summary.read_text(encoding="utf-8") if summary.exists() else "",
        tmp_path,
    )


@pytest.fixture(autouse=True)
def _python_under_test(monkeypatch):
    import sys

    monkeypatch.setenv("PYTHON_UNDER_TEST", sys.executable)


@pytest.fixture
def bundle(tmp_path):
    """A stand-in bundle and the digest Terraform would be given for it."""
    path = tmp_path / "build" / "vigilwatch.zip"
    path.parent.mkdir()
    path.write_bytes(b"bundle bytes")
    digest = base64.b64encode(hashlib.sha256(b"bundle bytes").digest()).decode()
    return path, digest


# ---- Build once: prod deploys the bytes dev ran, proven by digest ------------------------------

REQUIRE = ("deploy-environment.yml", "plan", "Promote only what dev last deployed successfully")
DESCRIBE = ("deploy-environment.yml", "plan", "Describe the bundle for Terraform")
RECORD = ("deploy-environment.yml", "record", "Record the commit this environment now runs")


def test_promotion_carries_the_digest_dev_released_into_the_plan(tmp_path, bundle):
    _, digest = bundle
    ran = run(find_step(*REQUIRE)["run"], tmp_path, env={"RECORD": f"{SHA} {digest}"})
    assert ran.status == 0, ran.output
    assert ran.env["DEV_BUNDLE_SHA256"] == digest


@pytest.mark.negative
def test_promotion_refuses_a_commit_dev_did_not_release(tmp_path, bundle):
    _, digest = bundle
    ran = run(find_step(*REQUIRE)["run"], tmp_path, env={"RECORD": f"{OTHER_SHA} {digest}"})
    assert ran.status == 1
    assert f"::error::dev last released {OTHER_SHA}" in ran.output


def test_the_bundle_digest_goes_to_the_plan_summary_and_the_job_outputs(tmp_path, bundle):
    path, digest = bundle
    ran = run(find_step(*DESCRIBE)["run"], tmp_path, env={"BUNDLE": path.as_posix()})
    assert ran.status == 0, ran.output
    assert ran.outputs["sha256"] == digest
    assert digest in ran.summary


@pytest.mark.negative
@pytest.mark.security
def test_prod_refuses_a_stored_bundle_that_is_not_the_one_dev_ran(tmp_path, bundle):
    """bundles/<sha>.zip can be overwritten; the release record says which bytes dev tested."""
    path, digest = bundle
    ran = run(
        find_step(*DESCRIBE)["run"],
        tmp_path,
        env={"BUNDLE": path.as_posix(), "DEV_BUNDLE_SHA256": "X" * 43 + "="},
    )
    assert ran.status == 1
    assert "::error::" in ran.output and "dev released" in ran.output
    assert "sha256" not in ran.outputs


def test_prod_deploys_a_stored_bundle_with_the_digest_dev_released(tmp_path, bundle):
    path, digest = bundle
    ran = run(
        find_step(*DESCRIBE)["run"],
        tmp_path,
        env={"BUNDLE": path.as_posix(), "DEV_BUNDLE_SHA256": digest},
    )
    assert ran.status == 0, ran.output


def test_the_release_record_holds_the_commit_and_its_bundle_digest(tmp_path, bundle):
    _, digest = bundle
    ran = run(
        find_step(*RECORD)["run"],
        tmp_path,
        env={"ENVIRONMENT": "dev", "DIGEST": digest},
    )
    assert ran.status == 0, ran.output
    assert (tmp_path / "written").read_text(encoding="utf-8") == f"{SHA} {digest}"
    assert (tmp_path / "written.key").read_text(encoding="utf-8").strip() == (
        "s3://state-bucket/releases/dev"
    )


@pytest.mark.negative
def test_a_release_without_a_digest_is_not_recorded(tmp_path):
    ran = run(find_step(*RECORD)["run"], tmp_path, env={"ENVIRONMENT": "dev", "DIGEST": ""})
    assert ran.status == 1
    assert not (tmp_path / "written").exists()


def test_the_record_job_is_given_the_digest_the_plan_deployed():
    data = yaml.safe_load((WORKFLOWS / "deploy-environment.yml").read_text(encoding="utf-8"))
    plan, record = data["jobs"]["plan"], data["jobs"]["record"]
    assert plan["outputs"]["bundle_sha256"] == "${{ steps.bundle.outputs.sha256 }}"
    assert {"plan", "smoke"} <= set(record["needs"])
    step = find_step(*RECORD)
    assert step["env"]["DIGEST"] == "${{ needs.plan.outputs.bundle_sha256 }}"


DRIFT_FETCH = ("drift.yml", "detect", "Fetch the released bundle")


@pytest.mark.negative
def test_drift_refuses_a_stored_bundle_that_is_not_the_released_one(tmp_path, bundle):
    path, _ = bundle
    target = tmp_path / "terraform" / ".build" / "vigilwatch.zip"
    ran = run(
        find_step(*DRIFT_FETCH)["run"],
        tmp_path,
        env={"BUNDLE": target.as_posix(), "FIXTURE": str(path), "DIGEST": "X" * 43 + "="},
    )
    assert ran.status == 1
    assert "::error::" in ran.output


def test_drift_plans_with_the_released_bundle(tmp_path, bundle):
    path, digest = bundle
    target = tmp_path / "terraform" / ".build" / "vigilwatch.zip"
    ran = run(
        find_step(*DRIFT_FETCH)["run"],
        tmp_path,
        env={"BUNDLE": target.as_posix(), "FIXTURE": str(path), "DIGEST": digest},
    )
    assert ran.status == 0, ran.output
    assert target.with_name("vigilwatch.tfvars.json").exists()
