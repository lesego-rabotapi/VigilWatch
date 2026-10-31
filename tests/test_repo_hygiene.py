"""Repository hygiene: build output, state and caches must never be committed."""

import fnmatch
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("VW-018")

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_TRACKED = [
    "*.tfstate",
    "*.tfstate.*",
    "*.zip",
    "*.pyc",
    "*/__pycache__/*",
    "*/.terraform/*",
]

MUST_BE_IGNORED = [
    "terraform/terraform.tfstate",
    "terraform/terraform.tfstate.backup",
    "terraform/.terraform/providers/x",
    "terraform/.build/lambda.zip",
    "lambda/__pycache__/x.cpython-312.pyc",
    ".venv/pyvenv.cfg",
    "terraform/prod.tfvars",
    "frontend/node_modules/x/index.js",
    "backups/endpoints.jsonl",  # the monitored URLs: scripts/backup_tables.py output
    "backups/endpoints.jsonl.partial",
]


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def _tracked_files():
    out = _git("ls-files")
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return out.stdout.splitlines()


@pytest.mark.parametrize("pattern", FORBIDDEN_TRACKED)
def test_no_forbidden_files_tracked(pattern):
    offenders = [f for f in _tracked_files() if fnmatch.fnmatch(f, pattern)]
    assert offenders == [], f"tracked files match {pattern}: {offenders}"


def test_no_terraform_outside_terraform_dir():
    stray = [f for f in _tracked_files() if f.endswith(".tf") and "/" not in f]
    assert stray == [], f"stray root-level terraform files: {stray}"


@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_gitignore_covers(path):
    _tracked_files()  # skip if not a git checkout
    assert _git("check-ignore", "-q", "--no-index", path).returncode == 0, path


def test_provider_lock_file_is_not_ignored():
    _tracked_files()
    assert _git("check-ignore", "-q", "--no-index", "terraform/.terraform.lock.hcl").returncode == 1


@pytest.mark.parametrize("path", ["lambda/uptime_check.py", "lambda/common/state.py"])
def test_bundled_sources_are_checked_out_with_lf_line_endings(path):
    """The bundle hash must not depend on the OS that checked the code out (core.autocrlf)."""
    _tracked_files()  # skip if not a git checkout
    out = _git("check-attr", "eol", "--", path).stdout
    assert out.strip().endswith("eol: lf"), out


@pytest.mark.negative
@pytest.mark.parametrize("path", ["lambda/certs/ca.der", "lambda/data/model.bin"])
def test_binary_files_in_the_bundle_are_not_forced_to_be_text(path):
    """Forcing text on a binary would rewrite its CRLF byte pairs on commit and corrupt it."""
    _tracked_files()
    out = _git("check-attr", "text", "eol", "--", path).stdout
    assert "text: set" not in out and "eol: lf" not in out, out


def test_gitignore_comments_describe_the_current_build():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "archive_file" not in text, "bundles come from scripts/build_bundle.py now"


def test_pytest_stays_below_the_release_pytest_bdd_does_not_support():
    """pytest 9.2 removed FixtureManager._arg2fixturedefs, which pytest-bdd 9.0 reads, so every
    BDD scenario errors. A fresh CI install picks the newest pytest; the cap keeps the pair working
    until pytest-bdd supports it."""
    lines = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    pytest_line = next(line for line in lines if line.split(">")[0].split("<")[0] == "pytest")
    assert "<9.2" in pytest_line, pytest_line
