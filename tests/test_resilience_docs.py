"""Resilience, service levels and triage are written down, match the code, and claim no result
that has not been measured."""

import re
from pathlib import Path

import pytest

import restore_drill

ROOT = Path(__file__).resolve().parent.parent
RESILIENCE = ROOT / "docs" / "resilience.md"
SLO = ROOT / "docs" / "slo.md"
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"
MONITORING = ROOT / "terraform" / "modules" / "monitoring" / "main.tf"


def text(path):
    assert path.exists(), f"{path.name} is missing"
    return path.read_text(encoding="utf-8")


def alarms_in_terraform():
    return set(re.findall(r'^\s{4}"([a-z0-9-]+)" = \{', text(MONITORING), re.M))


def section(doc: str, heading: str) -> str:
    match = re.search(rf"^#+ {re.escape(heading)}\n(.*?)(?=^#+ |\Z)", doc, re.S | re.M)
    assert match, f"no section {heading!r}"
    return match.group(1)


# ---- docs/resilience.md ---------------------------------------------------------------------


@pytest.mark.req("VW-024")
def test_the_failure_modes_say_how_each_is_detected_and_recovered():
    doc = text(RESILIENCE)
    table = section(doc, "Failure modes")
    header = next(line for line in table.splitlines() if line.startswith("|"))
    for column in ("Failure", "Detected by", "Recovery", "RTO target", "RPO target"):
        assert column in header, column
    for failure in (
        "endpoints table",
        "history",
        "checker stops",
        "checker cannot reach",
        "API",
        "bad deploy",
        "state",
        "region",
    ):
        assert failure in table, f"failure mode {failure!r} is missing"


@pytest.mark.req("VW-024")
def test_every_alarm_is_named_in_the_failure_modes_and_every_name_is_an_alarm():
    doc = text(RESILIENCE)
    alarms = alarms_in_terraform()
    assert alarms, "found no alarms in the monitoring module"
    named = set(re.findall(r"`vigilwatch-<env>-([a-z0-9-]+)`", doc))
    assert named == alarms


@pytest.mark.req("VW-024")
def test_recovery_targets_are_targets_and_point_in_time_recovery_is_explained():
    doc = text(RESILIENCE)
    assert "targets" in doc.lower() and "not measured" in doc
    assert "point-in-time" in doc and "D3" in doc
    for script in ("backup_tables.py", "restore_tables.py", "restore_drill.py"):
        assert script in doc
    assert "<table>-drill-<timestamp>-<random>" in doc, "the scratch table's real name pattern"


@pytest.mark.req("VW-024")
def test_the_drill_log_has_the_drills_columns_and_no_result_until_one_is_run():
    log = section(text(RESILIENCE), "Drill log")
    rows = [line for line in log.splitlines() if line.startswith("|")]
    assert rows[0] == restore_drill.LOG_HEADER, "paste the drill's row under its own header"
    assert re.fullmatch(r"\|( ?-+ ?\|)+", rows[1]), rows[1]
    assert rows[2:] == [], "no drill has run yet: a row here would be a result nobody measured"
    assert "NEEDS-AWS" in log


# ---- docs/slo.md -----------------------------------------------------------------------------


@pytest.mark.req("VW-025")
def test_each_objective_has_a_target_a_measure_and_a_guarding_alarm():
    doc = text(SLO)
    table = section(doc, "Objectives")
    for objective in ("Checker freshness", "API availability", "API latency"):
        assert objective in table, objective
    assert "99.5%" in table and "500 ms" in table
    named = set(re.findall(r"`vigilwatch-<env>-([a-z0-9-]+)`", table))
    assert named and named <= alarms_in_terraform(), named


@pytest.mark.req("VW-025")
def test_the_error_budget_is_the_arithmetic_of_the_objective():
    doc = text(SLO)
    budget = section(doc, "Error budget")
    minutes = round(30 * 24 * 60 * (1 - 0.995))
    assert f"{minutes} minutes" in budget, minutes  # 216 minutes in 30 days
    assert "freeze" in budget.lower()


@pytest.mark.req("VW-025")
def test_the_objectives_are_unmeasured_until_aws_day_and_say_where_they_are_read():
    doc = text(SLO)
    assert "NEEDS-AWS" in doc
    assert "golden-signals" in doc and "Logs Insights" in doc


# ---- docs/RUNBOOK.md ---------------------------------------------------------------------------


@pytest.mark.req("VW-025")
def test_the_runbook_traces_a_dashboard_with_no_data_through_three_paths():
    protocol = section(text(RUNBOOK), "9. Dashboard shows no data")
    for heading in ("Write path", "Read path", "Display path"):
        assert heading in protocol, heading
    for command in ("aws dynamodb get-item", "aws apigatewayv2 get-routes", "curl"):
        assert command in protocol, command
    assert '--data-urlencode "url=$URL"' in protocol, (
        "a URL with its own query string must be encoded"
    )


@pytest.mark.req("VW-016")
def test_the_runbook_keeps_an_iam_iteration_log():
    log = section(text(RUNBOOK), "10. IAM iteration log")
    assert "| Date | Error | Permission added | Reason |" in log


@pytest.mark.req("VW-024")
def test_the_runbook_says_how_to_back_up_restore_and_drill():
    runbook = text(RUNBOOK)
    for script in ("backup_tables.py", "restore_tables.py", "restore_drill.py"):
        assert script in runbook, script


@pytest.mark.req("VW-024")
def test_the_docs_say_to_pause_registrations_during_a_restore():
    """The counter is set after the items are written: a registration in between could pass
    the cap, so nobody registers while a restore runs."""
    for doc in (RESILIENCE, RUNBOOK):
        assert "pause registrations" in text(doc).lower(), doc.name
    assert "may continue during a restore" not in text(ROOT / "scripts" / "restore_tables.py")
