"""Release notes come from the conventional commit subjects since the previous release."""

import subprocess

import changelog
import pytest

pytestmark = pytest.mark.req("VW-017")

SUBJECTS = [
    "feat(pipeline): promote prod by hand",
    "test(pipeline): promote prod by hand",
    "fix(bundle): read rename records whole",
    "fix!: drop the old state key",
    "docs(runbook): retire the old stack",
    "refactor(infra): one helper for bootstrap statements",
    "Merge pull request #4 from somewhere",
    "update readme",
]


def test_subjects_are_grouped_by_their_type():
    notes = changelog.render("v2.7", SUBJECTS)
    sections = notes.split("\n### ")
    assert sections[0].startswith("## v2.7")
    titles = [s.splitlines()[0] for s in sections[1:]]
    assert titles == ["Features", "Fixes", "Documentation", "Other changes"]
    assert "- **pipeline:** promote prod by hand" in notes
    assert "- **bundle:** read rename records whole" in notes


def test_failing_test_commits_are_left_out_because_their_fix_is_listed():
    """Every change lands as a RED test commit then its fix: listing both repeats each change."""
    notes = changelog.render("v2.7", SUBJECTS)
    assert notes.count("promote prod by hand") == 1


def test_a_breaking_change_is_flagged():
    assert "- **BREAKING** drop the old state key" in changelog.render("v2.7", SUBJECTS)


def test_merge_commits_are_left_out_and_free_text_is_kept_as_other():
    notes = changelog.render("v2.7", SUBJECTS)
    assert "Merge pull request" not in notes
    assert "- update readme" in notes


def test_a_release_with_nothing_new_says_so():
    assert "No changes" in changelog.render("v2.8", [])


def test_the_command_reads_subjects_from_git(tmp_path, capsys):
    def git(*args):
        config = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run(["git", *config, *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "feat: first")
    git("commit", "-q", "--allow-empty", "-m", "fix(api): second")
    assert changelog.main(["HEAD", "--version", "v1", "--repo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "- first" in out and "- **api:** second" in out
