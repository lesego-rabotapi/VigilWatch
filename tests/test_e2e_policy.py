"""Rules for end-to-end tests: no deployed endpoints in code, no AWS access, writes guarded."""

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("VW-017")

TESTS = Path(__file__).resolve().parent
ENDPOINT_PATTERNS = re.compile(r"execute-api|cloudfront\.net|\.amazonaws\.com|\.kimmyai\.")
SELF = Path(__file__).name


def _python_files(*parts):
    return sorted(p for p in TESTS.joinpath(*parts).rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.security
def test_no_deployed_endpoint_appears_in_test_code():
    offenders = [
        f"{path.relative_to(TESTS)}:{n}"
        for path in _python_files()
        if path.name != SELF
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if ENDPOINT_PATTERNS.search(line)
    ]
    assert offenders == [], f"URLs must come from environment variables: {offenders}"


@pytest.mark.parametrize("area", ["e2e", "proxies"])
def test_end_to_end_code_never_talks_to_aws_directly(area):
    """Everything goes through the API (the gateway is the proxy under test)."""
    offenders = []
    for path in _python_files(area):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [
                f"{path.name}: {n}" for n in names if n.split(".")[0] in {"boto3", "botocore"}
            ]
    assert offenders == []


def test_e2e_tests_that_write_must_request_the_writable_fixture():
    """A test calling register() must depend on `writable`, which skips in read-only runs."""
    problems = []
    for path in _python_files("e2e"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            writes = any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "register"
                for call in ast.walk(node)
            )
            takes_guard = "writable" in {arg.arg for arg in node.args.args}
            if writes and not takes_guard:
                problems.append(f"{path.name}::{node.name}")
    assert problems == [], f"write tests without the `writable` guard: {problems}"


def test_every_e2e_test_declares_whether_it_is_safe_to_run_in_production():
    """Read-only tests carry the smoke marker; everything else must use the writable guard."""
    unlabeled = []
    for path in _python_files("e2e"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                marked_smoke = any("smoke" in ast.dump(d) for d in node.decorator_list)
                guarded = "writable" in {arg.arg for arg in node.args.args}
                if not (marked_smoke or guarded):
                    unlabeled.append(f"{path.name}::{node.name}")
    assert unlabeled == [], unlabeled
