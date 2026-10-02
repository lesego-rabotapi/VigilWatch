"""Documentation must describe the system that actually exists."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = sorted([ROOT / "README.md", ROOT / "systemOverview.md", *(ROOT / "docs").rglob("*.md")])
TEXT = {p: p.read_text(encoding="utf-8") for p in DOCS}
OUTPUTS = {
    name
    for path in (ROOT / "terraform" / "outputs.tf", ROOT / "terraform" / "bootstrap" / "outputs.tf")
    for name in re.findall(r'output\s+"([a-z_]+)"', path.read_text())
}


def test_required_documents_exist():
    for name in ("README.md", "docs/README.md", "docs/RUNBOOK.md", "systemOverview.md"):
        assert (ROOT / name).exists(), name
    assert len(list((ROOT / "docs" / "adr").glob("*.md"))) >= 4


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_stale_references(path):
    stale = ["api_handler", "stats_api", "aws_api_gateway_rest_api", "uptime_checks", "xihi7lu6jh"]
    found = [s for s in stale if s in TEXT[path]]
    assert not found, found


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_code_fences_are_balanced(path):
    assert TEXT[path].count("```") % 2 == 0


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_terraform_outputs_mentioned_exist(path):
    mentioned = set(re.findall(r"output(?: -raw| -json)? ([a-z_]+)", TEXT[path]))
    assert mentioned <= OUTPUTS, mentioned - OUTPUTS


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(path):
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", TEXT[path]):
        if re.match(r"^[a-z]+:", target):
            continue
        assert (path.parent / target).exists(), f"{path.name} -> {target}"


def test_readme_matches_the_stack():
    readme = TEXT[ROOT / "README.md"]
    for fact in ("HTTP API", "python3.12", "1.10", "always-free", "terraform test", "pytest"):
        assert fact in readme, fact


def test_runbook_covers_operations():
    runbook = TEXT[ROOT / "docs" / "RUNBOOK.md"]
    for section in ("Bootstrap", "First deploy", "Migrat", "Rollback", "Cost", "Alarm"):
        assert section in runbook, section
