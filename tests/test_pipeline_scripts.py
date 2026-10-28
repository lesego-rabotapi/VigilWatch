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


# ---- The release record: missing is not the same as unreadable --------------------------------

READER = "bash scripts/release.sh state-bucket dev"


def test_the_reader_prints_the_release_record(tmp_path, bundle):
    _, digest = bundle
    ran = run(READER, tmp_path, env={"RECORD": f"{SHA} {digest}"})
    assert ran.status == 0, ran.output
    assert ran.output.strip() == f"{SHA} {digest}"


def test_an_environment_never_released_has_an_empty_record(tmp_path):
    ran = run(READER, tmp_path)
    assert ran.status == 0, ran.output
    assert ran.output == ""


@pytest.mark.negative
def test_an_unreadable_record_fails_instead_of_meaning_never_released(tmp_path):
    """A wrong bucket name or a missing permission must not read as 'nothing released yet':
    drift would then report no drift every week."""
    ran = run(READER, tmp_path, env={"AWS_FAILS": "1"})
    assert ran.status != 0
    assert "AccessDenied" in ran.output


@pytest.mark.negative
@pytest.mark.parametrize("record", ["", SHA, f"{SHA[:-1]} xyz=", f"{SHA} {'A' * 43}= extra"])
def test_a_malformed_record_fails(tmp_path, record):
    ran = run(READER, tmp_path, env={"RECORD": record})
    assert ran.status != 0
    assert "::error::" in ran.output


def test_shell_scripts_keep_unix_line_endings_on_every_checkout():
    """bash fails on a carriage return, and Windows checkouts convert text files."""
    assert "*.sh text eol=lf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


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
def test_promotion_before_any_dev_release_says_to_deploy_dev_first(tmp_path):
    ran = run(find_step(*REQUIRE)["run"], tmp_path)
    assert ran.status == 1
    assert "::error::dev has no release yet" in ran.output


@pytest.mark.negative
def test_promotion_stops_when_the_record_cannot_be_read(tmp_path):
    ran = run(find_step(*REQUIRE)["run"], tmp_path, env={"AWS_FAILS": "1"})
    assert ran.status != 0
    assert "DEV_BUNDLE_SHA256" not in ran.env


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


REBUILD = ("deploy-environment.yml", "plan", "Check the stored bundle is this commit's code")


def _head_bundle(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_bundle

    return build_bundle.build(ROOT / "lambda", tmp_path / "stored" / "vigilwatch.zip").path


def test_a_stored_bundle_that_rebuilds_from_its_commit_is_deployed(tmp_path):
    """A rollback has no current release record to compare with, but the build is
    reproducible: the commit itself says which bytes are right."""
    ran = run(
        find_step(*REBUILD)["run"],
        tmp_path,
        env={"BUNDLE": _head_bundle(tmp_path).as_posix(), "RUNNER_TEMP": str(tmp_path)},
    )
    assert ran.status == 0, ran.output


@pytest.mark.negative
@pytest.mark.security
def test_a_stored_bundle_that_is_not_its_commits_code_is_refused(tmp_path, bundle):
    path, _ = bundle
    ran = run(
        find_step(*REBUILD)["run"],
        tmp_path,
        env={"BUNDLE": path.as_posix(), "RUNNER_TEMP": str(tmp_path)},
    )
    assert ran.status == 1
    assert "::error::" in ran.output


def test_every_deploy_that_fetches_a_bundle_checks_it_before_planning():
    data = yaml.safe_load((WORKFLOWS / "deploy-environment.yml").read_text(encoding="utf-8"))
    names = [s.get("name") for s in data["jobs"]["plan"]["steps"]]
    fetch, check = names.index("Fetch the stored bundle"), names.index(REBUILD[2])
    assert fetch < check < names.index("Describe the bundle for Terraform")
    assert find_step(*REBUILD)["if"] == "${{ !inputs.build }}"


DRIFT_FETCH = ("drift.yml", "detect", "Fetch the released bundle")
DRIFT_FIND = ("drift.yml", "detect", "Find the released commit")


def test_drift_compares_the_released_commit_and_digest(tmp_path, bundle):
    _, digest = bundle
    ran = run(
        find_step(*DRIFT_FIND)["run"],
        tmp_path,
        env={"ENVIRONMENT": "prod", "RECORD": f"{SHA} {digest}"},
    )
    assert ran.status == 0, ran.output
    assert ran.outputs == {"sha": SHA, "digest": digest}


def test_drift_skips_an_environment_never_released(tmp_path):
    ran = run(find_step(*DRIFT_FIND)["run"], tmp_path, env={"ENVIRONMENT": "prod"})
    assert ran.status == 0, ran.output
    assert "::notice::" in ran.output
    assert ran.outputs == {}


@pytest.mark.negative
def test_drift_fails_when_the_record_cannot_be_read(tmp_path):
    """Before: any S3 error was read as 'no release', and the check went quiet for good."""
    ran = run(
        find_step(*DRIFT_FIND)["run"],
        tmp_path,
        env={"ENVIRONMENT": "prod", "AWS_FAILS": "1"},
    )
    assert ran.status != 0
    assert "::notice::" not in ran.output


def test_drift_checks_out_the_repository_before_reading_the_record():
    """The reader is a script in the repository; the released commit is checked out after."""
    data = yaml.safe_load((WORKFLOWS / "drift.yml").read_text(encoding="utf-8"))
    names = [s.get("name") or s.get("uses", "") for s in data["jobs"]["detect"]["steps"]]
    first_checkout = next(i for i, n in enumerate(names) if n.startswith("actions/checkout"))
    assert first_checkout < names.index("Find the released commit")


# ---- Plan on pull requests ----------------------------------------------------------------------

PR_PLAN = ("pr-plan.yml", "plan", "terraform plan")
FAKE_TERRAFORM = 'printf "%s\\n" "$PLAN_TEXT"; exit "$PLAN_STATUS"'
RESOURCE_PLAN = """
  # module.vigilwatch.aws_lambda_function.checker will be updated in-place
  ~ resource "aws_lambda_function" "checker" {
    }

Plan: 0 to add, 1 to change, 0 to destroy.
"""
OUTPUTS_ONLY_PLAN = """
Changes to Outputs:
  + checker_function_name = "vigilwatch-dev-uptime-check"

You can apply this plan to save these new output values to the Terraform
state, without changing any real infrastructure.
"""


def _pr_plan(tmp_path, text, status):
    return run(
        find_step(*PR_PLAN)["run"],
        tmp_path,
        env={"PLAN_TEXT": text, "PLAN_STATUS": str(status)},
        stubs={"terraform": FAKE_TERRAFORM},
        cwd=tmp_path,
    )


def test_the_pull_request_comment_lists_changed_resources_and_the_totals(tmp_path):
    ran = _pr_plan(tmp_path, RESOURCE_PLAN, 2)
    assert ran.status == 0, ran.output
    comment = (tmp_path / "comment.md").read_text(encoding="utf-8")
    assert "aws_lambda_function.checker will be updated" in comment
    assert "Plan: 0 to add, 1 to change, 0 to destroy." in comment


def test_a_plan_that_changes_only_outputs_still_gets_a_comment(tmp_path):
    """Exit code 2 with no 'Plan:' line: grep found nothing and failed the job."""
    ran = _pr_plan(tmp_path, OUTPUTS_ONLY_PLAN, 2)
    assert ran.status == 0, ran.output
    comment = (tmp_path / "comment.md").read_text(encoding="utf-8")
    assert "Only output values change" in comment
    assert "checker_function_name" in comment


def test_a_plan_with_no_changes_says_so(tmp_path):
    ran = _pr_plan(tmp_path, "No changes. Your infrastructure matches the configuration.", 0)
    assert ran.status == 0, ran.output
    assert "No changes." in (tmp_path / "comment.md").read_text(encoding="utf-8")


@pytest.mark.negative
def test_a_failed_plan_fails_the_job_and_shows_why(tmp_path):
    ran = _pr_plan(tmp_path, "Error: no valid credential sources", 1)
    assert ran.status == 1
    assert "no valid credential sources" in ran.output


# ---- Tagging the release -----------------------------------------------------------------------

TAG = ("promote-prod.yml", "release", "Choose the tag")


def test_the_tag_is_the_next_free_v2_number(tmp_path):
    ran = run(find_step(*TAG)["run"], tmp_path)
    assert ran.status == 0, ran.output
    assert ran.env["TAG"].startswith("v2.")


@pytest.mark.negative
def test_a_failure_choosing_the_tag_stops_the_step(tmp_path):
    """echo "TAG=$(...)" succeeds even when the command inside fails, leaving TAG empty."""
    ran = run(find_step(*TAG)["run"], tmp_path, stubs={"python": "exit 1"})
    assert ran.status != 0
    assert "TAG" not in ran.env


# ---- Choosing the commit to promote -------------------------------------------------------------

RESOLVE = ("promote-prod.yml", "resolve", "Choose the commit to promote")


def test_promotion_defaults_to_the_commit_dev_last_released(tmp_path, bundle):
    _, digest = bundle
    ran = run(
        find_step(*RESOLVE)["run"],
        tmp_path,
        env={"REQUESTED": "", "RECORD": f"{SHA} {digest}"},
    )
    assert ran.status == 0, ran.output
    assert ran.outputs["sha"] == SHA


def test_a_requested_commit_is_passed_on_for_the_deploy_to_check(tmp_path):
    ran = run(find_step(*RESOLVE)["run"], tmp_path, env={"REQUESTED": OTHER_SHA})
    assert ran.status == 0, ran.output
    assert ran.outputs["sha"] == OTHER_SHA


@pytest.mark.negative
def test_promotion_with_no_dev_release_says_so(tmp_path):
    ran = run(find_step(*RESOLVE)["run"], tmp_path, env={"REQUESTED": ""})
    assert ran.status == 1
    assert "::error::dev has no release yet" in ran.output


@pytest.mark.negative
def test_promotion_stops_when_it_cannot_read_what_dev_released(tmp_path):
    ran = run(find_step(*RESOLVE)["run"], tmp_path, env={"REQUESTED": "", "AWS_FAILS": "1"})
    assert ran.status != 0
    assert "sha" not in ran.outputs


@pytest.mark.security
def test_choosing_the_commit_only_reads_so_it_uses_the_read_only_role():
    data = yaml.safe_load((WORKFLOWS / "promote-prod.yml").read_text(encoding="utf-8"))
    resolve = data["jobs"]["resolve"]
    roles = [
        s["with"]["role-to-assume"]
        for s in resolve["steps"]
        if "configure-aws-credentials" in s.get("uses", "")
    ]
    assert roles == ["${{ vars.AWS_PLAN_ROLE_ARN }}"]
    assert "vars.AWS_PLAN_ROLE_ARN != ''" in resolve["if"]
    assert any("actions/checkout" in s.get("uses", "") for s in resolve["steps"])


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
