"""The test-mix report: how many tests each layer has and how many target failure paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from test_mix import render, summarize

pytestmark = pytest.mark.req("VW-019")

ROOT = Path(__file__).resolve().parents[2]


def item(*markers):
    return SimpleNamespace(iter_markers=lambda: [SimpleNamespace(name=m) for m in markers])


def test_counts_are_grouped_by_layer_and_kind():
    rows = summarize(
        [
            item("unit"),
            item("unit", "negative"),
            item("unit", "boundary", "negative"),
            item("mock", "security"),
            item("contract"),
        ]
    )
    assert rows["unit"] == {"tests": 3, "negative": 2, "boundary": 1, "security": 0}
    assert rows["mock"] == {"tests": 1, "negative": 0, "boundary": 0, "security": 1}
    assert rows["contract"]["tests"] == 1


def test_items_without_a_layer_are_not_counted():
    assert summarize([item("req")]) == {}


def test_render_produces_a_markdown_table_with_totals():
    text = render(summarize([item("unit", "negative"), item("unit"), item("mock", "boundary")]))
    assert "| Layer | Tests | negative | boundary | security |" in text
    assert "| unit | 2 | 1 | 0 | 0 |" in text
    assert "| **Total** | 3 | 1 | 1 | 0 |" in text
    assert "negative-marked" in text


def test_render_handles_an_empty_suite():
    assert "| **Total** | 0 | 0 | 0 | 0 |" in render({})
