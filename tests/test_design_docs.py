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


def test_checker_honesty_adr_records_the_decision_and_its_limits():
    text = (ROOT / "docs" / "adr" / "0006-checker-honesty.md").read_text(encoding="utf-8")
    for term in (
        "INCONCLUSIVE",
        "control",
        "heartbeat",
        "single region",
        "any target that answers",
        "NEEDS-AWS",
        "Status:",
    ):
        assert term in text, f"ADR 0006 does not mention {term!r}"


def test_the_scheduled_check_diagram_shows_the_connectivity_controls():
    diagram = _sections()["Scheduled check"]
    assert "INCONCLUSIVE" in diagram
    assert "common.controls" in diagram
    assert "Business error" in diagram and "Unexpected error" in diagram


def test_pipeline_adr_records_promotion_rollback_drift_and_what_was_not_adopted():
    text = (ROOT / "docs" / "adr" / "0009-pipeline-and-promotion.md").read_text(encoding="utf-8")
    for term in (
        "bundles/<sha>.zip",
        "releases/dev",
        "rollback.yml",
        "-refresh-only",
        "vigilwatch-github-plan",
        "check_junit",
        "verify_package",
        "CHANGELOG.md",
        "shared root",
        "NEEDS-AWS",
    ):
        assert term in text, f"ADR 0009 does not mention {term!r}"


def test_environments_adr_records_the_decisions_and_the_free_tier_arithmetic():
    text = (ROOT / "docs" / "adr" / "0005-environments-and-modules.md").read_text(encoding="utf-8")
    for term in (
        "allowed_account_ids",
        "Build once",
        "No SIT",
        "METRICS_ENABLED",
        "deletion protection",
        "proxy",
        "NEEDS-AWS",
        "Status:",
    ):
        assert term in text, f"ADR 0005 does not mention {term!r}"


def test_environments_adr_records_that_prod_no_longer_allows_localhost():
    text = (ROOT / "docs" / "adr" / "0005-environments-and-modules.md").read_text(encoding="utf-8")
    assert "localhost" in text and "extra_cors_origins" in text
