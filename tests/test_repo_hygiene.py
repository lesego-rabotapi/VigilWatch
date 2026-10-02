"""Repository hygiene: build output, state and caches must never be committed."""

import fnmatch
import subprocess
from pathlib import Path

import pytest

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
