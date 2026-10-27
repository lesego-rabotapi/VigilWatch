"""The built bundle, alone, must import and answer: what Lambda will load is what was tested.

CI runs scripts/verify_package.py inside the public.ecr.aws/lambda/python:3.12 image. Here it runs
in an isolated interpreter (-I) that sees only the bundle, which is enough to prove it catches a
bundle with a missing module (the mutation check).
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import build_bundle
import verify_package

pytestmark = pytest.mark.req("VW-017")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_package.py"


def verify(bundle: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(bundle)],
        cwd=tmp_path,  # nothing of the repository on the path
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_real_bundle_imports_and_answers(tmp_path):
    bundle = build_bundle.build(ROOT / "lambda", tmp_path / "b.zip", rev="HEAD").path
    result = verify(bundle, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    for handler in verify_package.HANDLERS:
        assert handler in result.stdout


@pytest.mark.negative
def test_a_bundle_missing_a_module_fails(tmp_path):
    """Lessons 3 and 4: a package that imports fine in the repository can be broken on its own."""
    source = tmp_path / "lambda"
    shutil.copytree(ROOT / "lambda", source, ignore=shutil.ignore_patterns("__pycache__"))
    (source / "common" / "status.py").unlink()
    bundle = build_bundle.build(source, tmp_path / "broken.zip").path
    result = verify(bundle, tmp_path)
    assert result.returncode == 1
    assert "common.status" in result.stdout + result.stderr


@pytest.mark.negative
def test_a_handler_that_answers_wrongly_fails(tmp_path):
    source = tmp_path / "lambda"
    shutil.copytree(ROOT / "lambda", source, ignore=shutil.ignore_patterns("__pycache__"))
    handler = source / "get_checks.py"
    handler.write_text(
        handler.read_text(encoding="utf-8") + "\n\ndef lambda_handler(event, context):\n"
        "    return {'statusCode': 500}\n",
        encoding="utf-8",
    )
    result = verify(build_bundle.build(source, tmp_path / "b.zip").path, tmp_path)
    assert result.returncode == 1
    assert "get_checks" in result.stdout + result.stderr


def test_it_checks_exactly_the_handlers_terraform_deploys():
    compute = (ROOT / "terraform" / "modules" / "compute" / "main.tf").read_text(encoding="utf-8")
    deployed = set(re.findall(r'handler\s*=\s*"([\w.]+)"', compute))
    assert set(verify_package.HANDLERS) == deployed
