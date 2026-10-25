"""Design documents: sequence diagrams must show failure paths and match the code."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("VW-019")

ROOT = Path(__file__).resolve().parent.parent
SEQUENCES = ROOT / "docs" / "design" / "sequences.md"
FLOWS = ["Register a URL", "Scheduled check", "Alerting", "Read status"]


def _sections():
    """Map each `## heading` to the mermaid diagram under it."""
    text = SEQUENCES.read_text(encoding="utf-8")
    sections = {}
    for match in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.S | re.M):
        diagram = re.search(r"```mermaid\n(.*?)```", match.group(2), re.S)
        if diagram:
            sections[match.group(1).strip()] = diagram.group(1)
    return sections


def test_each_core_flow_has_a_sequence_diagram():
    assert set(FLOWS) <= set(_sections()), f"missing flows: {set(FLOWS) - set(_sections())}"


@pytest.mark.parametrize("flow", FLOWS)
def test_diagram_is_a_sequence_diagram_with_participants(flow):
    diagram = _sections()[flow]
    assert diagram.lstrip().startswith("sequenceDiagram")
    assert len(re.findall(r"^\s*participant ", diagram, re.M)) >= 3


@pytest.mark.parametrize("flow", FLOWS)
def test_diagram_shows_business_and_unexpected_failure_paths(flow):
    diagram = _sections()[flow]
    assert re.search(r"^\s*alt ", diagram, re.M), f"{flow}: no alt branch"
    assert re.search(r"^\s*else ", diagram, re.M), f"{flow}: no else branch"
    assert "Business error" in diagram, f"{flow}: business-error path missing"
    assert "Unexpected error" in diagram, f"{flow}: unexpected-error path missing"


def test_diagrams_only_name_modules_that_exist():
    text = SEQUENCES.read_text(encoding="utf-8")
    functions = set(re.findall(r"\b(register_endpoint|uptime_check|get_checks)\b", text))
    assert functions == {"register_endpoint", "uptime_check", "get_checks"}
    for name in functions:
        assert (ROOT / "lambda" / f"{name}.py").exists(), name
    modules = set(re.findall(r"\bcommon\.(\w+)", text))
    assert modules, "diagrams should reference the shared modules"
    for module in modules:
        assert (ROOT / "lambda" / "common" / f"{module}.py").exists(), module


def test_runtime_decisions_adr_records_what_was_deliberately_not_adopted():
    text = (ROOT / "docs" / "adr" / "0008-runtime-patterns.md").read_text(encoding="utf-8")
    for term in ("Powertools", "SnapStart", "native JSON", "NEEDS-AWS", "cached"):
        assert term in text, f"ADR 0008 does not discuss {term}"
    assert "Status:" in text
