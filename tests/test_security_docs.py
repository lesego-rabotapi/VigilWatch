"""docs/security.md: the threat model, each control tied to the test that proves it, and the risks
accepted on purpose. The runbook says how users and the smoke-test user are set up."""

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.req("VW-026"), pytest.mark.security]

ROOT = Path(__file__).resolve().parent.parent
SECURITY = ROOT / "docs" / "security.md"
RUNBOOK = ROOT / "docs" / "RUNBOOK.md"


def text(path):
    assert path.exists(), f"{path.name} is missing"
    return path.read_text(encoding="utf-8")


def section(doc, heading):
    match = re.search(rf"^#+ {re.escape(heading)}\n(.*?)(?=^#+ |\Z)", doc, re.S | re.M)
    assert match, f"no section {heading!r}"
    return match.group(1)


def test_the_threat_model_names_what_is_protected_and_from_whom():
    threats = section(text(SECURITY), "Threat model")
    for term in ("anonymous", "another user", "stolen token", "SSRF", "cost", "pipeline"):
        assert term in threats, term


def test_every_control_names_the_test_that_proves_it_and_that_test_exists():
    controls = section(text(SECURITY), "Controls")
    rows = [line for line in controls.splitlines() if line.startswith("| ") and "---" not in line]
    assert len(rows) > 10, "one row per control, and there are many"
    for row in rows[1:]:
        cited = re.findall(r"`((?:tests|frontend/tests|terraform)/[^`]+)`", row)
        assert cited, f"no test cited: {row[:80]}"
        for path in cited:
            assert (ROOT / path).exists(), f"{path} does not exist"
    for control in (
        "JWT authorizer",
        "404",
        "PKCE",
        "in memory",
        "per-user cap",
        "least privilege",
        "Content-Security-Policy",
        "throttl",
    ):
        assert control in controls, control


def test_accepted_risks_are_written_down_with_their_reason():
    risks = section(text(SECURITY), "Accepted risks")
    for risk in ("WAF", "prod state", "alert", "NEEDS-AWS"):
        assert risk in risks, risk


def test_the_runbook_says_how_to_invite_a_user_and_set_up_the_smoke_user():
    runbook = text(RUNBOOK)
    for command in ("admin-create-user", "admin-set-user-password", "--permanent"):
        assert command in runbook, command
    for setting in ("E2E_USERNAME", "E2E_PASSWORD"):
        assert setting in runbook, setting
    assert "secret" in section(runbook, "1. Bootstrap (once per AWS account)").lower()


def test_the_no_data_protocol_derives_the_id_from_the_owner_and_the_url():
    protocol = section(text(RUNBOOK), "9. Dashboard shows no data")
    assert re.search(r"endpoint_id\(\w+, normalize\(", protocol), "the id now includes the owner"
    assert "admin-get-user" in protocol, "the owner's subject comes from the user pool"
