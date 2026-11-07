"""The release checklist is one document, shown in each deploy's job summary."""

from pathlib import Path

import pytest

import checklist

pytestmark = pytest.mark.req("VW-017")

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "RELEASE_CHECKLIST.md"


@pytest.mark.parametrize("phase", ["pre", "post"])
def test_each_phase_has_its_own_section_of_unticked_items(phase):
    text = checklist.section(phase)
    assert text.startswith(f"## {checklist.HEADINGS[phase]}")
    items = [line for line in text.splitlines() if line.startswith("- [ ] ")]
    assert len(items) >= 5, items


def test_the_phases_do_not_overlap():
    pre, post = checklist.section("pre"), checklist.section("post")
    assert checklist.HEADINGS["post"] not in pre and checklist.HEADINGS["pre"] not in post


@pytest.mark.negative
def test_an_unknown_phase_is_refused():
    with pytest.raises(ValueError, match="pre, post"):
        checklist.section("during")


def test_the_command_prints_the_section(capsys):
    assert checklist.main(["post"]) == 0
    assert capsys.readouterr().out.startswith("## Post-deployment")


def test_the_checklist_names_this_projects_own_checks():
    """Specific, not generic: each item points at something this pipeline really produces."""
    text = DOC.read_text(encoding="utf-8")
    for evidence in ("releases/", "check_junit", "deletion", "E2E_READONLY_URL", "rollback.yml"):
        assert evidence in text, evidence
