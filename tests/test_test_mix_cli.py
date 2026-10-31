"""The test-mix script, run end to end against this repository (slow: it collects the suite)."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("VW-019")

ROOT = Path(__file__).resolve().parent.parent


def test_the_script_reports_on_this_repository():
    done = subprocess.run(  # noqa: S603 (our own interpreter and script)
        [sys.executable, str(ROOT / "scripts" / "test_mix.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-800:]
    for layer in ("unit", "mock", "contract", "bdd", "policy"):
        assert f"| {layer} |" in done.stdout, layer
