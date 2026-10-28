"""A smoke run is green only if every expected test ran and none was skipped."""

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


def test_a_complete_run_passes(tmp_path, capsys):
    assert check_junit.main([str(report(tmp_path)), "--min-tests", "4"]) == 0
    assert "4 ran" in capsys.readouterr().out


@pytest.mark.negative
def test_a_skipped_test_fails_the_gate(tmp_path, capsys):
    """A skipped smoke test proves nothing, so the deploy it guards must not look green."""
    assert check_junit.main([str(report(tmp_path, skipped=1)), "--min-tests", "4"]) == 1
    assert "skipped" in capsys.readouterr().out


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize("tests, passes", [(3, False), (4, True), (5, True)])
def test_fewer_tests_than_expected_fails_the_gate(tmp_path, tests, passes):
    """A marker or path mistake that deselects tests must not pass as a smaller green run."""
    assert (
        check_junit.main([str(report(tmp_path, tests=tests)), "--min-tests", "4"]) == 0
    ) is passes


@pytest.mark.negative
@pytest.mark.parametrize("field", ["failures", "errors"])
def test_failures_and_errors_fail_the_gate(tmp_path, field):
    assert check_junit.main([str(report(tmp_path, **{field: 1})), "--min-tests", "4"]) == 1


def test_counts_are_summed_over_every_suite(tmp_path):
    path = tmp_path / "e2e.xml"
    path.write_text(
        '<testsuites><testsuite tests="2" skipped="0" failures="0" errors="0"/>'
        '<testsuite tests="2" skipped="1" failures="0" errors="0"/></testsuites>',
        encoding="utf-8",
    )
    assert check_junit.counts(path) == {"tests": 4, "skipped": 1, "failures": 0, "errors": 0}


def collected(tmp_path, count):
    """What `pytest --collect-only -q` prints: one node id per test, then a summary."""
    path = tmp_path / "collected.txt"
    ids = [f"tests/e2e/test_smoke.py::test_{n}" for n in range(count)]
    path.write_text("\n".join([*ids, "", f"{count} tests collected in 0.05s"]), encoding="utf-8")
    return path


def test_the_minimum_can_be_what_the_deployed_commit_collects(tmp_path, capsys):
    """A rollback runs an older commit's tests; a minimum fixed in today's workflow would fail
    it after the apply."""
    args = [str(report(tmp_path, tests=3)), "--collected", str(collected(tmp_path, 3))]
    assert check_junit.main(args) == 0
    assert "3 ran" in capsys.readouterr().out


@pytest.mark.negative
def test_running_fewer_tests_than_were_collected_fails(tmp_path):
    args = [str(report(tmp_path, tests=3)), "--collected", str(collected(tmp_path, 4))]
    assert check_junit.main(args) == 1


@pytest.mark.negative
def test_a_commit_that_collects_nothing_fails(tmp_path, capsys):
    args = [str(report(tmp_path, tests=0)), "--collected", str(collected(tmp_path, 0))]
    assert check_junit.main(args) == 1
    assert "nothing was collected" in capsys.readouterr().out


@pytest.mark.negative
def test_a_minimum_is_required(tmp_path):
    with pytest.raises(SystemExit):
        check_junit.main([str(report(tmp_path))])


@pytest.mark.negative
def test_a_missing_report_fails_instead_of_passing_on_nothing(tmp_path, capsys):
    assert check_junit.main([str(tmp_path / "none.xml"), "--min-tests", "1"]) == 1
    assert "no test report" in capsys.readouterr().out
