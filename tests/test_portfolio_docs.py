"""The portfolio documents: what a reviewer reads first has to be true, dated and traceable."""

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("VW-019")

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
TAGS = {"CI", "MOCK", "REPO", "NEEDS-AWS"}
LINK = re.compile(r"\]\(((?!https?://|#)[^)\s]+)\)")


def section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"missing section: {heading}"
    return match.group(1)


def bullets(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("- ")]


def broken_links(text: str, base: Path) -> list[str]:
    return [t for t in LINK.findall(text) if not (base / t.split("#")[0]).exists()]


# ---- README (9.1, 9.4) ----------------------------------------------------------------------


def test_the_subtitle_does_not_overclaim_the_free_tier():
    head = "\n".join(README.splitlines()[:6]).lower()
    assert "always-free" not in head and "always free" not in head
    assert "12 months" in README, "API Gateway's free tier is time-limited; say so"


def test_the_readme_has_ci_badges_for_the_real_workflows():
    for workflow in ("ci.yml", "deploy-dev.yml"):
        assert (ROOT / ".github" / "workflows" / workflow).exists()
        assert f"actions/workflows/{workflow}/badge.svg" in README, workflow


def test_the_coverage_figures_match_the_gates():
    gate = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["coverage"]["report"]
    assert f"{int(gate['fail_under'])}%" in README
    assert "85%" not in README, "the gate was raised to 90%"


def test_the_architecture_is_a_mermaid_diagram_that_includes_sign_in():
    diagram = re.search(r"```mermaid\n(.*?)```", README, re.S)
    assert diagram, "no mermaid diagram"
    for part in ("Cognito", "CloudFront", "DynamoDB", "EventBridge", "SNS"):
        assert part in diagram.group(1), part


def test_there_is_a_two_command_path_that_needs_no_aws_account():
    block = section(README, "Try it without AWS")
    assert "pip install -r requirements-dev.txt" in block
    assert "python scripts/local_api.py" in block


def test_the_readme_no_longer_describes_the_system_before_sign_in_and_the_modules():
    for stale in ("No authentication", "4 alarms", "4 custom metrics", "85%"):
        assert stale not in README, stale


def test_every_adr_is_indexed_with_an_evidence_tag():
    index = section(README, "Engineering decisions")
    rows = [line for line in index.splitlines() if line.startswith("|") and "docs/adr/" in line]
    indexed = {m for row in rows for m in re.findall(r"docs/adr/(\d{4}-[\w-]+\.md)", row)}
    on_disk = {p.name for p in (ROOT / "docs" / "adr").glob("*.md")}
    assert indexed == on_disk, (on_disk - indexed, indexed - on_disk)
    for row in rows:
        tags = set(re.findall(r"`([A-Z-]+)`", row))
        assert tags and tags <= TAGS, row


def test_lessons_are_dated_linked_and_tagged():
    lessons = bullets(section(README, "Lessons learned"))
    assert len(lessons) >= 5
    for lesson in lessons:
        assert re.match(r"- \*\*\d{4}-\d{2}-\d{2}\b", lesson), f"undated: {lesson[:60]}"
        assert LINK.search(lesson), f"no link: {lesson[:60]}"
        assert set(re.findall(r"`([A-Z-]+)`", lesson)) & TAGS, f"no evidence tag: {lesson[:60]}"


def test_trade_offs_point_at_the_decision_that_made_them():
    trade_offs = bullets(section(README, "Engineering trade-offs"))
    assert trade_offs
    for trade_off in trade_offs:
        assert LINK.search(trade_off), f"no link: {trade_off[:60]}"


def test_every_relative_link_in_the_readme_resolves():
    assert broken_links(README, ROOT) == []


# ---- the logo (9.6) -------------------------------------------------------------------------


def test_the_dashboard_logo_is_a_real_file_the_page_uses():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    src = re.search(r'<img src="(assets/[^"]+)" alt="VigilWatch logo"', html)
    assert src, "the header has no logo"
    assert (ROOT / "frontend" / src.group(1)).stat().st_size > 200, "empty logo file"
    for asset in (ROOT / "frontend" / "assets").iterdir():
        assert asset.stat().st_size > 0, f"{asset.name} is an empty file"


# ---- performance (9.3) ----------------------------------------------------------------------


def test_the_performance_page_publishes_a_method_and_no_unmeasured_figure():
    text = (ROOT / "docs" / "performance.md").read_text(encoding="utf-8")
    assert "NEEDS-AWS" in text
    assert "scripts/measure_cold_start.py" in text
    header, rule, *rows = [line for line in text.splitlines() if line.startswith("|")]
    assert "Init p50" in header and "Init p95" in header and "Region" in header
    assert set(rule) <= set("|- "), rule
    assert rows == [], "a results row appeared before anything was measured"
    assert "No figure is published until it has been measured" in text
    assert broken_links(text, ROOT / "docs") == []


# ---- interview notes (9.5) ------------------------------------------------------------------


def test_each_interview_answer_is_short_and_points_at_evidence():
    text = (ROOT / "docs" / "interview-notes.md").read_text(encoding="utf-8")
    questions = re.split(r"^### ", text, flags=re.M)[1:]
    assert len(questions) >= 8
    for block in questions:
        title, *body = block.splitlines()
        lines = [line for line in body if line.strip() and not line.startswith("#")]
        assert title.rstrip().endswith("?"), title
        assert 3 <= len(lines) <= 5, f"{title}: {len(lines)} lines"
        assert LINK.search("\n".join(lines)), f"{title}: no link to evidence"
    assert broken_links(text, ROOT / "docs") == []
