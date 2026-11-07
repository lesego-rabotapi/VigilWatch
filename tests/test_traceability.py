"""Every requirement must be proven by at least one test, and every test reference must be real.

Requirements live in docs/design/requirements.md as `### VW-nnn: title` stories.
Tests cite them with `pytest.mark.req("VW-nnn")` (Python), `@VW-nnn` tags (Gherkin)
or `req: VW-nnn` comments (JS, Terraform).
"""

import re
from pathlib import Path

import pytest

from traceability import build_matrix, load_requirements, render_matrix, scan_references

ROOT = Path(__file__).resolve().parent.parent
ID = re.compile(r"^VW-\d{3}$")


def test_requirements_document_defines_unique_well_formed_stories():
    stories = load_requirements()
    ids = [s["id"] for s in stories]
    assert len(ids) >= 15
    assert len(ids) == len(set(ids)), "duplicate requirement IDs"
    assert all(ID.match(i) for i in ids)
    assert ids == sorted(ids), "keep stories in ID order"


def test_every_story_has_a_title_and_acceptance_criteria():
    for story in load_requirements():
        assert story["title"], story["id"]
        assert len(story["acceptance"]) >= 1, f"{story['id']} has no acceptance criteria"


def test_every_requirement_is_covered_by_at_least_one_test():
    matrix = build_matrix()
    uncovered = [row["id"] for row in matrix if not row["tests"]]
    assert uncovered == [], f"requirements with no test: {uncovered}"


def test_every_reference_in_a_test_points_to_a_real_requirement():
    known = {s["id"] for s in load_requirements()}
    unknown = {ref: files for ref, files in scan_references().items() if ref not in known}
    assert unknown == {}, f"tests cite unknown requirements: {unknown}"


def test_committed_traceability_matrix_is_up_to_date():
    committed = (ROOT / "docs" / "design" / "traceability.md").read_text(encoding="utf-8")
    assert committed == render_matrix(), "run: python scripts/traceability.py --write"


@pytest.mark.parametrize(
    "layer", ["unit", "mock", "bdd", "contract", "policy", "frontend", "infrastructure", "e2e"]
)
def test_matrix_names_the_layer_of_each_covering_test(layer):
    layers = {t["layer"] for row in build_matrix() for t in row["tests"]}
    assert layer in layers, f"no requirement is proven at the {layer} layer"
