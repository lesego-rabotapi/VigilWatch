"""A smoke run is green only if every test the deployed commit collects ran and none skipped."""

import pytest

import check_junit

pytestmark = pytest.mark.req("VW-017")


def report(tmp_path, tests=4, skipped=0, failures=0, errors=0):
    path = tmp_path / "e2e.xml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        f'<testsuite name="pytest" tests="{tests}" skipped="{skipped}" failures="{failures}" '
        f'errors="{errors}"></testsuite></testsuites>',
        encoding="utf-8",
    )
    return path


def collected(tmp_path, count=4, summary=None):
    """What `pytest --collect-only -q` prints: one node id per test, then a summary."""
    path = tmp_path / "collected.txt"
    ids = [f"tests/e2e/test_smoke.py::test_{n}" for n in range(count)]
    noun = "test" if count == 1 else "tests"
    summary = summary or f"{count} {noun} collected in 0.05s"
    path.write_text("\n".join([*ids, "", summary]), encoding="utf-8")
    return path


def gate(tmp_path, listing=None, **totals):
    listing = listing or collected(tmp_path)
    return check_junit.main([str(report(tmp_path, **totals)), "--collected", str(listing)])


def test_a_complete_run_passes(tmp_path, capsys):
    assert gate(tmp_path) == 0
    assert "4 ran" in capsys.readouterr().out


@pytest.mark.negative
def test_a_skipped_test_fails_the_gate(tmp_path, capsys):
    """A skipped smoke test proves nothing, so the deploy it guards must not look green."""
    assert gate(tmp_path, skipped=1) == 1
    assert "skipped" in capsys.readouterr().out


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize("tests, passes", [(3, False), (4, True), (5, True)])
def test_running_fewer_tests_than_were_collected_fails(tmp_path, tests, passes):
    """A marker or path mistake that deselects tests must not pass as a smaller green run."""
    assert (gate(tmp_path, tests=tests) == 0) is passes


@pytest.mark.negative
@pytest.mark.parametrize("field", ["failures", "errors"])
def test_failures_and_errors_fail_the_gate(tmp_path, field):
    assert gate(tmp_path, **{field: 1}) == 1


def test_counts_are_summed_over_every_suite(tmp_path):
    path = tmp_path / "e2e.xml"
    path.write_text(
        '<testsuites><testsuite tests="2" skipped="0" failures="0" errors="0"/>'
        '<testsuite tests="2" skipped="1" failures="0" errors="0"/></testsuites>',
        encoding="utf-8",
    )
    assert check_junit.counts(path) == {"tests": 4, "skipped": 1, "failures": 0, "errors": 0}


@pytest.mark.parametrize(
    "summary, expected",
    [
        ("4 tests collected in 0.05s", 4),
        ("1 test collected in 0.01s", 1),
        ("4/6 tests collected (2 deselected) in 0.05s", 4),
    ],
)
def test_the_minimum_is_pytests_own_count_of_what_the_commit_collects(tmp_path, summary, expected):
    """A rollback runs an older commit's tests; a minimum fixed in today's workflow would fail
    it after the apply."""
    assert check_junit.collected(collected(tmp_path, expected, summary)) == expected


@pytest.mark.negative
def test_node_ids_in_a_warnings_summary_do_not_raise_the_minimum(tmp_path):
    listing = tmp_path / "collected.txt"
    listing.write_text(
        "tests/e2e/test_smoke.py::test_a\n"
        "tests/e2e/test_smoke.py::test_b\n\n"
        "=== warnings summary ===\n"
        "tests/e2e/test_smoke.py::test_a\n"
        "  DeprecationWarning: something\n\n"
        "2 tests collected in 0.05s\n",
        encoding="utf-8",
    )
    assert check_junit.collected(listing) == 2


@pytest.mark.negative
@pytest.mark.parametrize("summary", ["no tests ran in 0.01s", "0 tests collected"])
def test_a_commit_that_collects_nothing_fails(tmp_path, capsys, summary):
    listing = collected(tmp_path, 0, summary)
    assert gate(tmp_path, listing=listing, tests=0) == 1
    assert "nothing was collected" in capsys.readouterr().out


@pytest.mark.negative
def test_the_collection_listing_is_required(tmp_path):
    with pytest.raises(SystemExit):
        check_junit.main([str(report(tmp_path))])


@pytest.mark.negative
def test_a_missing_report_fails_instead_of_passing_on_nothing(tmp_path, capsys):
    args = [str(tmp_path / "none.xml"), "--collected", str(collected(tmp_path))]
    assert check_junit.main(args) == 1
    assert "no test report" in capsys.readouterr().out


@pytest.mark.negative
def test_a_missing_listing_fails(tmp_path, capsys):
    args = [str(report(tmp_path)), "--collected", str(tmp_path / "none.txt")]
    assert check_junit.main(args) == 1
    assert "no collection listing" in capsys.readouterr().out
