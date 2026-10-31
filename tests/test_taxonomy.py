"""Test taxonomy: every test belongs to exactly one layer, and layers keep their promises.

unit         pure logic, no AWS libraries
mock         handlers and repositories against moto
integration  a real or emulated backend (reserved: LocalStack/moto server, then deployed DEV)
contract     API shape against the OpenAPI-derived schema
bdd          Gherkin scenarios (run on the mock layer)
e2e          deployed API, read-only in prod (deselected by default)
policy       repository, workflow, documentation and traceability rules
"""

import configparser
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.taxonomy import LAYERS, find_unmarked, layer_for

pytestmark = pytest.mark.req("VW-018")

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "relative, layer",
    [
        ("tests/unit/test_status.py", "unit"),
        ("tests/mock/test_repo.py", "mock"),
        ("tests/integration/test_localstack.py", "integration"),
        ("tests/contract/test_openapi.py", "contract"),
        ("tests/step_defs/test_monitoring.py", "bdd"),
        ("tests/e2e/test_smoke.py", "e2e"),
        ("tests/test_docs.py", "policy"),
        ("tests/test_taxonomy.py", "policy"),
    ],
)
def test_layer_is_derived_from_the_location(relative, layer):
    assert layer_for(relative) == layer


@pytest.mark.parametrize(
    "relative", ["tests/mystery/test_x.py", "tests/unit_ish/test_y.py", "elsewhere/test_z.py"]
)
def test_unknown_locations_have_no_layer(relative):
    assert layer_for(relative) is None


def _item(path, *markers):
    return SimpleNamespace(
        nodeid=path,
        path=ROOT / path,
        iter_markers=lambda: [SimpleNamespace(name=m) for m in markers],
    )


def test_find_unmarked_reports_items_without_a_layer_marker():
    items = [_item("tests/unit/test_a.py", "unit"), _item("tests/mystery/test_b.py", "req")]
    assert [i.nodeid for i in find_unmarked(items)] == ["tests/mystery/test_b.py"]


def test_find_unmarked_flags_items_with_two_layers():
    items = [_item("tests/unit/test_a.py", "unit", "mock")]
    assert find_unmarked(items), "a test in two layers is ambiguous"


def test_every_layer_marker_is_registered():
    parser = configparser.ConfigParser()
    parser.read(ROOT / "pytest.ini", encoding="utf-8")
    registered = {
        line.split(":")[0].strip()
        for line in parser["pytest"]["markers"].splitlines()
        if line.strip()
    }
    assert set(LAYERS) <= registered, set(LAYERS) - registered
    assert {"smoke", "negative", "boundary", "security", "req"} <= registered


def test_every_collected_test_has_exactly_one_layer_marker(request):
    assert find_unmarked(request.session.items) == []


def test_moto_based_tests_live_in_the_mock_layer():
    for name in ("test_repo.py", "test_uptime_check.py", "test_register_endpoint.py"):
        assert (ROOT / "tests" / "mock" / name).exists(), name
    leftovers = list((ROOT / "tests" / "integration").glob("test_*.py"))
    assert leftovers == [], "tests/integration is reserved for real or emulated backends"


def test_unit_layer_runs_without_importing_moto():
    code = (
        "import sys, pytest; "
        "rc = pytest.main(['-m', 'unit', '-q', '-p', 'no:cacheprovider']); "
        "print('MOTO_IMPORTED', 'moto' in sys.modules); sys.exit(rc)"
    )
    done = subprocess.run(  # noqa: S603 (fixed argv, our own interpreter)
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout[-1500:]
    assert "MOTO_IMPORTED False" in done.stdout, "unit tests must not need moto"
