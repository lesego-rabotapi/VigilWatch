"""Cold-start figures come from Lambda's own REPORT lines, parsed and summarised plainly."""

import io

import pytest

import measure_cold_start as mcs

pytestmark = pytest.mark.req("VW-020")

NL = chr(10)

COLD = (
    "REPORT RequestId: 11111111-aaaa Duration: 120.50 ms\tBilled Duration: 121 ms\t"
    "Memory Size: 128 MB\tMax Memory Used: 54 MB\tInit Duration: 231.56 ms"
)
WARM = (
    "REPORT RequestId: 22222222-bbbb Duration: 8.25 ms\tBilled Duration: 9 ms\t"
    "Memory Size: 128 MB\tMax Memory Used: 54 MB"
)


def test_a_cold_report_line_carries_its_init_duration():
    assert mcs.parse_report(COLD) == {
        "duration_ms": 120.5,
        "init_ms": 231.56,
        "billed_ms": 121,
        "memory_mb": 128,
        "max_memory_mb": 54,
    }


def test_a_warm_report_line_has_no_init_duration():
    assert mcs.parse_report(WARM)["init_ms"] is None


def test_lines_that_are_not_reports_are_ignored():
    assert mcs.parse_report("START RequestId: 1 Version: $LATEST") is None
    assert mcs.parse_report("2026-11-07T10:00:00Z INFO something") is None
    assert mcs.parse_report("") is None


def test_a_report_found_inside_a_timestamped_log_line_is_parsed():
    assert mcs.parse_report("2026-11-07T10:00:00.000Z " + COLD)["duration_ms"] == 120.5


@pytest.mark.parametrize(
    "values, p50, p95",
    [
        ([10, 20, 30], 20, 30),
        (list(range(1, 101)), 50, 95),
        ([7], 7, 7),
        ([5, 1, 3, 2, 4], 3, 5),  # unsorted input
    ],
)
def test_percentiles_are_nearest_rank(values, p50, p95):
    assert mcs.percentile(values, 50) == p50
    assert mcs.percentile(values, 95) == p95


def test_a_percentile_of_nothing_is_not_a_number():
    assert mcs.percentile([], 50) is None


def test_the_summary_separates_cold_from_warm():
    records = [mcs.parse_report(COLD), mcs.parse_report(WARM), mcs.parse_report(WARM)]
    summary = mcs.summarise(records)
    assert summary["invocations"] == 3
    assert summary["cold_starts"] == 1
    assert summary["init_p50_ms"] == 231.56
    assert summary["cold_duration_p50_ms"] == 120.5
    assert summary["warm_duration_p50_ms"] == 8.25


def test_a_log_with_no_cold_start_has_no_init_figure():
    summary = mcs.summarise([mcs.parse_report(WARM)])
    assert summary["cold_starts"] == 0
    assert summary["init_p50_ms"] is None and summary["init_p95_ms"] is None


def test_no_reports_at_all_is_an_error_not_a_zero():
    with pytest.raises(SystemExit):
        mcs.main([], stdin=io.StringIO("nothing useful here\n"))


def test_the_command_prints_a_row_for_the_performance_table(capsys):
    log = "\n".join([COLD, WARM, "START ignored"])
    assert mcs.main(["--markdown"], stdin=io.StringIO(log)) == 0
    out = capsys.readouterr().out
    assert out.count("|") >= 8 and "231.56" in out and "8.25" in out


def test_values_are_printed_in_full_never_in_exponent_or_six_digit_form(capsys):
    log = COLD.replace("231.56", "1234567.891")
    mcs.main(["--markdown"], stdin=io.StringIO(log))
    out = capsys.readouterr().out
    assert "1234567.891" in out and "e+" not in out


def test_input_mixing_memory_sizes_is_refused_not_blended():
    other = COLD.replace("128 MB", "256 MB")
    with pytest.raises(SystemExit, match="memory"):
        mcs.main([], stdin=io.StringIO(NL.join([COLD, other])))


def test_a_report_line_that_cannot_be_parsed_is_counted_not_dropped(capsys):
    odd = "REPORT RequestId: 3333 Duration: 5.00 ms Status: timeout"
    mcs.main([], stdin=io.StringIO(NL.join([COLD, odd])))
    assert "skipped_report_lines: 1" in capsys.readouterr().out


def test_a_utf16_log_file_from_powershell_is_read(tmp_path, capsys):
    path = tmp_path / "logs.txt"
    path.write_bytes((NL.join([COLD, WARM]) + NL).encode("utf-16"))
    assert mcs.main([str(path)]) == 0
    assert "invocations: 2" in capsys.readouterr().out
