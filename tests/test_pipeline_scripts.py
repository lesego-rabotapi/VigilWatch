"""The shell the workflows run, executed against fakes of `aws` and `terraform`.

tests/test_workflows.py reads the workflow files. These tests run their steps the way GitHub
runs them (bash -eo pipefail), with fake commands that answer like the real ones, so a step that
only looks right is caught too.
"""

import base64
import hashlib
import json
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

# A fake AWS CLI for the calls the workflows make. RECORD is the content of the release record
# read (unset: there is none). AWS_FAILS makes every call fail the way a wrong bucket or a
# missing permission does. Every call is logged to AWS_LOG; an object written from stdin is
# saved under AWS_STORE at its key, and reads find it there first; a download to a file copies
# FIXTURE.
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
  if [ -f "$AWS_STORE/$prefix" ] || [ -n "${RECORD+set}" ]; then echo "$prefix"; else echo None; fi
  exit 0
fi
if [ "$1 $2" = "s3 cp" ]; then
  if [ "$3" = "-" ]; then
    key="${4#s3://*/}"
    mkdir -p "$AWS_STORE/$(dirname "$key")"
    cat > "$AWS_STORE/$key"
  elif [ "$4" = "-" ]; then
    key="${3#s3://*/}"
    if [ -f "$AWS_STORE/$key" ]; then
      cat "$AWS_STORE/$key"
      exit 0
    fi
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
        "AWS_STORE": str(tmp_path / "s3"),
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
    tfvars = json.loads(path.with_name("vigilwatch.tfvars.json").read_text(encoding="utf-8"))
    assert tfvars == {"bundle_path": path.as_posix(), "bundle_sha256": digest}, (
        "Terraform deploys under the digest that was checked and is recorded"
    )


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
    """releases/<env> says what runs now; releases/history/<env>/<sha> that it once passed."""
    _, digest = bundle
    _store(tmp_path, "releases/dev.applied", SHA)
    ran = run(find_step(*RECORD)["run"], tmp_path, env={"ENVIRONMENT": "dev", "DIGEST": digest})
    assert ran.status == 0, ran.output
    store = tmp_path / "s3"
    assert (store / "releases" / "dev").read_text(encoding="utf-8") == f"{SHA} {digest}"
    history = store / "releases" / "history" / "dev" / SHA
    assert history.read_text(encoding="utf-8") == f"{SHA} {digest}"


@pytest.mark.negative
def _store(tmp_path, key, content):
    path = tmp_path / "s3" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_a_release_without_a_digest_is_not_recorded(tmp_path):
    ran = run(find_step(*RECORD)["run"], tmp_path, env={"ENVIRONMENT": "dev", "DIGEST": ""})
    assert ran.status == 1
    assert not (tmp_path / "s3").exists()


@pytest.mark.negative
def test_a_rerun_after_a_newer_deploy_does_not_record_the_older_commit(tmp_path, bundle):
    """Re-running an old run's smoke and record jobs would record what no longer runs, even
    when the newer commit changed only infrastructure and the bundle is the same."""
    _, digest = bundle
    _store(tmp_path, "releases/dev.applied", OTHER_SHA)
    ran = run(find_step(*RECORD)["run"], tmp_path, env={"ENVIRONMENT": "dev", "DIGEST": digest})
    assert ran.status == 1
    assert "::error::" in ran.output and "newer deploy" in ran.output
    assert not (tmp_path / "s3" / "releases" / "dev").exists()


def test_the_apply_job_marks_the_commit_it_applied():
    data = yaml.safe_load((WORKFLOWS / "deploy-environment.yml").read_text(encoding="utf-8"))
    runs = [str(s.get("run", "")) for s in data["jobs"]["apply"]["steps"]]
    applied = next(i for i, r in enumerate(runs) if "terraform apply" in r)
    marker = next(i for i, r in enumerate(runs) if "releases/$ENVIRONMENT.applied" in r)
    assert applied < marker


ROLLBACK = ("deploy-environment.yml", "plan", "Roll back only to a commit dev released")


def test_a_rollback_target_dev_released_carries_its_digest_into_the_plan(tmp_path, bundle):
    _, digest = bundle
    ran = run(find_step(*ROLLBACK)["run"], tmp_path, env={"RECORD": f"{SHA} {digest}"})
    assert ran.status == 0, ran.output
    assert ran.env["DEV_BUNDLE_SHA256"] == digest
    assert f"releases/history/dev/{SHA}" in (tmp_path / "aws.log").read_text(encoding="utf-8")


@pytest.mark.negative
@pytest.mark.security
def test_a_rollback_to_a_commit_dev_never_released_is_refused(tmp_path):
    """A stored bundle only proves dev built it; its apply or smoke test may have failed."""
    ran = run(find_step(*ROLLBACK)["run"], tmp_path)
    assert ran.status == 1
    assert "::error::" in ran.output and "never released" in ran.output


def test_the_rollback_check_runs_only_for_rollbacks():
    step = find_step(*ROLLBACK)
    assert step["if"] == "${{ !inputs.build && !inputs.require_dev_release }}"


def test_the_record_job_is_given_the_digest_the_plan_deployed():
    data = yaml.safe_load((WORKFLOWS / "deploy-environment.yml").read_text(encoding="utf-8"))
    plan, record = data["jobs"]["plan"], data["jobs"]["record"]
    assert plan["outputs"]["bundle_sha256"] == "${{ steps.bundle.outputs.sha256 }}"
    assert {"plan", "smoke"} <= set(record["needs"])
    step = find_step(*RECORD)
    assert step["env"]["DIGEST"] == "${{ needs.plan.outputs.bundle_sha256 }}"


REBUILD = ("deploy-environment.yml", "plan", "Check the stored bundle is this commit's code")


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _head_bundle(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import build_bundle

    out = tmp_path / "stored" / "vigilwatch.zip"
    return build_bundle.build(ROOT / "lambda", out, rev="HEAD").path


def test_a_stored_bundle_that_rebuilds_from_its_commit_is_deployed(tmp_path):
    """A rollback has no current release record to compare with, but the build is
    reproducible: the commit itself says which bytes are right."""
    ran = run(
        find_step(*REBUILD)["run"],
        tmp_path,
        env={
            "BUNDLE": _head_bundle(tmp_path).as_posix(),
            "RUNNER_TEMP": str(tmp_path),
            "SHA": _head(),
        },
    )
    assert ran.status == 0, ran.output


@pytest.mark.negative
@pytest.mark.security
def test_a_stored_bundle_that_is_not_its_commits_code_is_refused(tmp_path, bundle):
    path, _ = bundle
    ran = run(
        find_step(*REBUILD)["run"],
        tmp_path,
        env={"BUNDLE": path.as_posix(), "RUNNER_TEMP": str(tmp_path), "SHA": _head()},
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


@pytest.mark.negative
def test_terraform_variables_stay_valid_json_for_any_bundle_path(tmp_path, bundle):
    """A path can hold a backslash (Windows) or a quote (legal on Linux); printf escaped neither."""
    path, digest = bundle
    if os.name != "nt":
        odd = path.parent / 'odd "quoted" \\ dir'
        odd.mkdir()
        path = path.rename(odd / path.name)
    else:
        assert "\\" in str(path)
    ran = run(find_step(*DESCRIBE)["run"], tmp_path, env={"BUNDLE": str(path)})
    assert ran.status == 0, ran.output
    tfvars = json.loads(path.with_name("vigilwatch.tfvars.json").read_text(encoding="utf-8"))
    assert tfvars == {"bundle_path": str(path), "bundle_sha256": digest}


DRIFT_REPORT = ("drift.yml", "report", "Open or update the drift issue")


FAKE_GH = 'echo "$*" >> "$GH_LOG"; for a in "$@"; do [ -f "$a" ] && cat "$a" >> "$GH_LOG"; done; :'


def _report(tmp_path, detect):
    return run(
        find_step(*DRIFT_REPORT)["run"],
        tmp_path,
        env={"DETECT": detect, "GH_LOG": str(tmp_path / "gh.log"), "RUN": "https://run"},
        stubs={"gh": FAKE_GH},
        cwd=tmp_path,
    )


def _result(tmp_path, environment, text):
    (tmp_path / f"drift-{environment}").mkdir()
    (tmp_path / f"drift-{environment}" / "drift.md").write_text(text, encoding="utf-8")


def test_a_clean_week_reports_no_drift_and_touches_no_issue(tmp_path):
    _result(tmp_path, "dev", "none\n")
    _result(tmp_path, "prod", "none\n")
    ran = _report(tmp_path, "success")
    assert ran.status == 0, ran.output
    assert "No drift." in ran.output
    assert not (tmp_path / "gh.log").exists()


def test_drift_found_goes_into_the_issue(tmp_path):
    _result(tmp_path, "dev", "none\n")
    _result(tmp_path, "prod", "### Drift in prod\n~ aws_lambda_function.checker\n")
    ran = _report(tmp_path, "success")
    assert ran.status == 0, ran.output
    log = (tmp_path / "gh.log").read_text(encoding="utf-8")
    assert "issue create" in log and "Drift in prod" in log


@pytest.mark.negative
@pytest.mark.parametrize("results", [[], ["dev"]], ids=["none-checked", "prod-unchecked"])
def test_a_failed_check_alone_opens_no_drift_issue_and_claims_no_clean_week(tmp_path, results):
    """A failed detect leg is a failed run, which GitHub reports; an issue titled 'drift
    detected' would send someone looking for a console change that never happened."""
    for environment in results:
        _result(tmp_path, environment, "none\n")
    ran = _report(tmp_path, "failure")
    assert ran.status == 0, ran.output
    assert "No drift." not in ran.output and "::warning::" in ran.output
    assert not (tmp_path / "gh.log").exists()


def test_drift_found_while_another_check_failed_says_so_in_the_issue(tmp_path):
    _result(tmp_path, "dev", "### Drift in dev\n~ aws_sns_topic.alerts\n")
    ran = _report(tmp_path, "failure")
    assert ran.status == 0, ran.output
    log = (tmp_path / "gh.log").read_text(encoding="utf-8")
    assert "Drift in dev" in log and "could not be checked" in log


def test_the_report_reads_every_environment_the_matrix_ran():
    """Results are read by glob, so an environment added to the matrix is reported too."""
    step = find_step(*DRIFT_REPORT)
    assert "drift-*/drift.md" in step["run"] and "dev prod" not in step["run"]
    assert step["env"]["DETECT"] == "${{ needs.detect.result }}"


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


# ---- Running from main only ---------------------------------------------------------------------

GUARDS = [
    ("deploy-environment.yml", "plan", "Check the inputs"),
    ("promote-prod.yml", "resolve", "Refuse any branch but main"),
    ("drift.yml", "detect", "Refuse any branch but main"),
]
VALID_INPUTS = {"ENVIRONMENT": "prod", "SHA": SHA}


@pytest.mark.negative
@pytest.mark.parametrize("guard", GUARDS, ids=lambda g: g[0])
def test_a_dispatch_from_another_branch_fails_loudly(tmp_path, guard):
    ran = run(find_step(*guard)["run"], tmp_path, env={**VALID_INPUTS, "REF": "refs/heads/x"})
    assert ran.status == 1
    assert "::error::" in ran.output and "refs/heads/x" in ran.output


@pytest.mark.parametrize("guard", GUARDS, ids=lambda g: g[0])
def test_a_run_from_main_goes_ahead(tmp_path, guard):
    ran = run(find_step(*guard)["run"], tmp_path, env={**VALID_INPUTS, "REF": "refs/heads/main"})
    assert ran.status == 0, ran.output


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
    assert "AWS_PLAN_ROLE_ARN" not in resolve["if"], "a missing role must fail, not skip in green"
    assert any("actions/checkout" in s.get("uses", "") for s in resolve["steps"])


PLAN_ROLE = ("promote-prod.yml", "resolve", "Require the read-only role")


@pytest.mark.negative
def test_promotion_without_the_read_only_role_fails_with_the_fix(tmp_path):
    ran = run(find_step(*PLAN_ROLE)["run"], tmp_path, env={"PLAN_ROLE": ""})
    assert ran.status == 1
    assert "::error::" in ran.output and "AWS_PLAN_ROLE_ARN" in ran.output


def test_promotion_with_the_read_only_role_goes_ahead(tmp_path):
    ran = run(find_step(*PLAN_ROLE)["run"], tmp_path, env={"PLAN_ROLE": "arn:aws:iam::0:role/x"})
    assert ran.status == 0, ran.output


# ---- Dev deploys main's newest commit -----------------------------------------------------------

BEHIND = ("deploy-environment.yml", "plan", "Never put dev behind what it runs")


@pytest.fixture
def history(tmp_path):
    """A repository whose main has two commits: (older, newest)."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "-q")
    shas = []
    for n in range(2):
        (repo / "f").write_text(str(n), encoding="utf-8")
        git("add", "f")
        git("commit", "-q", "-m", f"c{n}")
        shas.append(git("rev-parse", "HEAD"))
    git("update-ref", "refs/remotes/origin/main", shas[-1])
    (repo / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "release.sh", repo / "scripts" / "release.sh")
    return repo, shas


@pytest.mark.parametrize(
    "released, deploying, passes",
    [(None, 1, True), (0, 1, True), (1, 1, True), (1, 0, False)],
    ids=["first", "newer", "same", "older"],
)
def test_dev_never_goes_behind_the_commit_it_runs(tmp_path, history, released, deploying, passes):
    """Re-running a week-old dev deploy would put old code on dev and make it the commit
    promotion picks. A newer commit landing during a run's CI is fine: it queues behind."""
    repo, shas = history
    if released is not None:
        _store(tmp_path, "releases/dev", f"{shas[released]} {'A' * 43}=")
    ran = run(find_step(*BEHIND)["run"], tmp_path, env={"SHA": shas[deploying]}, cwd=repo)
    assert (ran.status == 0) is passes, ran.output
    if not passes:
        assert "::error::" in ran.output and "behind" in ran.output


def test_the_behind_check_runs_for_dev_builds_only():
    assert find_step(*BEHIND)["if"] == "${{ inputs.build }}"
    on_main = find_step("deploy-environment.yml", "plan", "Deploy only commits that are on main")
    assert "rev-parse origin/main" not in on_main["run"], "main's tip moves during a run's CI"


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
    tfvars = json.loads(target.with_name("vigilwatch.tfvars.json").read_text(encoding="utf-8"))
    assert tfvars["bundle_sha256"] == digest
