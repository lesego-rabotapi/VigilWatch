"""Each prod release gets the next free v2.<n> tag, whatever workflow run numbers say."""

import pytest

import next_version

pytestmark = pytest.mark.req("VW-017")


def test_the_next_tag_follows_the_highest_existing_one():
    assert next_version.next_tag(["v2.3", "v2.10", "v2.9"]) == "v2.11"


def test_the_first_release_of_a_major_version_is_one():
    assert next_version.next_tag(["v1.48", "v1.49"]) == "v2.1"
    assert next_version.next_tag([]) == "v2.1"


@pytest.mark.negative
def test_tags_of_other_forms_are_ignored():
    """The old pipeline tagged v1.<run number>; a renamed workflow restarts its run number at 1,
    so the run number alone would collide with a tag that already exists."""
    assert next_version.next_tag(["v2.x", "v2.3-rc1", "v20.1", "release-v2.7", "v2.4"]) == "v2.5"


def test_the_command_reads_git_tag_output(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("v1.49\nv2.1\nv2.2\n"))
    assert next_version.main([]) == 0
    assert capsys.readouterr().out == "v2.3\n"
