"""Stage 11 policy: the integration layer is a decided, gated part of the pipeline.

The backend is chosen in an ADR, the layer may skip on a laptop but never in CI, and CI runs it as
a job of its own whose report is held to "nothing skipped" (CI gate integrity).
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.integration.backend import BackendUnavailable, require

ROOT = Path(__file__).resolve().parent.parent
ADR = ROOT / "docs" / "adr" / "0010-integration-backend.md"

pytestmark = pytest.mark.req("VW-017")


def test_the_backend_choice_is_recorded_with_what_was_not_chosen():
    text = ADR.read_text(encoding="utf-8")
    assert re.search(r"^- Status: accepted \(\d{4}-\d{2}-\d{2}\)$", text, re.M)
    for heading in ("## Context", "## Decision", "## Not adopted"):
        assert heading in text, heading
    decision = text.split("## Decision", 1)[1].split("## Not adopted", 1)[0]
    assert "moto server" in decision
    assert "LocalStack" in text.split("## Not adopted", 1)[1]


def test_the_adr_labels_what_it_did_not_measure():
    """No unmeasured claim is published: LocalStack was not run, and the ADR says so."""
    text = ADR.read_text(encoding="utf-8")
    assert "UNVERIFIED" in text


def test_a_missing_backend_skips_on_a_laptop():
    with pytest.raises(pytest.skip.Exception):
        require(BackendUnavailable("no moto server"), ci=False)


def test_a_missing_backend_fails_in_ci_instead_of_skipping():
    with pytest.raises(pytest.fail.Exception, match="no moto server"):
        require(BackendUnavailable("no moto server"), ci=True)


def test_an_available_backend_is_not_an_obstacle():
    require(None, ci=True)
    require(None, ci=False)


def _ci_jobs():
    data = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    return data["jobs"]


def _run_text(job):
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def test_ci_runs_the_integration_layer_as_its_own_job():
    jobs = _ci_jobs()
    assert "integration" in jobs
    text = _run_text(jobs["integration"])
    assert "pip install -r requirements-dev.txt" in text
    assert "-m integration" in text


def test_the_integration_job_fails_on_any_skip_or_a_short_run():
    text = _run_text(_ci_jobs()["integration"])
    lines = text.splitlines()
    collect = next(i for i, line in enumerate(lines) if "--collect-only" in line)
    run_tests = next(i for i, line in enumerate(lines) if "--junitxml=" in line)
    gate = next(i for i, line in enumerate(lines) if "scripts/check_junit.py" in line)
    assert collect < run_tests < gate
    assert "-m integration" in lines[collect] and "-m integration" in lines[run_tests]
    assert "--collected" in lines[gate]


def test_the_python_job_leaves_integration_to_its_own_job():
    text = _run_text(_ci_jobs()["python"])
    assert re.search(r'pytest .*-m "not integration and not e2e"', text)


def test_the_integration_job_cannot_quietly_pass():
    job = _ci_jobs()["integration"]
    assert "continue-on-error" not in job
    assert not any(
        "continue-on-error" in step or "|| true" in str(step.get("run", ""))
        for step in job["steps"]
    )
    assert job.get("timeout-minutes")


def test_the_moto_server_extra_is_a_development_requirement():
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r"moto\[[^\]]*\bserver\b[^\]]*\]", requirements)


def test_the_layer_is_collected_and_every_test_in_it_is_marked():
    result = subprocess.run(  # noqa: S603 (fixed argv, our own interpreter)
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
        + ["-m", "integration", "tests/integration"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"^(\d+)(?:/\d+)? tests? collected", result.stdout, re.M)
    assert match and int(match.group(1)) >= 5, result.stdout
