"""Module dependencies point one way: a module may import only from a lower layer.

Layers (lower number = more fundamental):
  0  leaf helpers and contracts: no imports from other common modules
  1  single-purpose components (probe, alerts, one repository each)
  2  composition: the Repo facade and the incident/alert state machine
  3  entry points of the package: the checker facade and the dashboard view
Lambda handlers (lambda/*.py) sit above all of them and may import anything.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("VW-019")

COMMON = Path(__file__).resolve().parents[2] / "lambda" / "common"

LAYER = {
    "aws": 0,
    "dynamo": 0,
    "errors": 0,
    "http": 0,
    "logs": 0,
    "ports": 0,
    "retention": 0,
    "settings": 0,
    "status": 0,
    "timefmt": 0,
    "urlguard": 0,
    "alerts": 1,
    "controls": 1,
    "endpoints_repo": 1,
    "history_repo": 1,
    "incidents_repo": 1,
    "probe": 1,
    "api": 2,
    "repo": 2,
    "state": 2,
    "checker": 3,
    "view": 3,
}


def _modules():
    return {p.stem for p in COMMON.glob("*.py") if p.stem != "__init__"}


def _imports(module):
    """Names of common modules that `module` imports."""
    tree = ast.parse((COMMON / f"{module}.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "common":
                found |= {alias.name for alias in node.names}
            elif node.module.startswith("common."):
                found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            found |= {a.name.split(".")[1] for a in node.names if a.name.startswith("common.")}
    return found


def test_every_common_module_is_assigned_a_layer():
    assert _modules() == set(LAYER), (
        f"unassigned: {_modules() - set(LAYER)}, missing: {set(LAYER) - _modules()}"
    )


def test_modules_import_only_from_lower_layers():
    violations = [
        f"{module} (layer {LAYER[module]}) imports {dep} (layer {LAYER[dep]})"
        for module in sorted(_modules())
        for dep in sorted(_imports(module))
        if dep in LAYER and LAYER[dep] >= LAYER[module]
    ]
    assert violations == [], violations


def test_leaf_modules_import_nothing_from_the_package():
    for module in (m for m, layer in LAYER.items() if layer == 0):
        assert _imports(module) == set(), f"{module} is a leaf but imports {_imports(module)}"


def test_only_the_aws_module_creates_boto3_clients():
    offenders = []
    for module in sorted(_modules() - {"aws"}):
        source = (COMMON / f"{module}.py").read_text(encoding="utf-8")
        if "boto3.client(" in source or "boto3.resource(" in source:
            offenders.append(module)
    assert offenders == [], f"create clients through common.aws: {offenders}"
