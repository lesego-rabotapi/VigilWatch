"""Fail a test run that skipped anything or ran fewer tests than expected.

pytest exits 0 when every selected test skipped, so a smoke job whose address was missing, or
whose marker selected nothing, would look green. This reads pytest's JUnit report and holds the
run to a minimum: a fixed number, or every test the commit collects. Standard library only.

    pytest --collect-only -q ... > collected.txt
    pytest ... --junitxml=e2e.xml
    python scripts/check_junit.py e2e.xml --collected collected.txt    # or --min-tests 4
"""

import argparse
import sys
import xml.etree.ElementTree as ET  # noqa: S405 - our own pytest report, not untrusted input
from pathlib import Path

FIELDS = ("tests", "skipped", "failures", "errors")


def counts(report: Path) -> dict[str, int]:
    root = ET.parse(report).getroot()  # noqa: S314
    suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
    totals = dict.fromkeys(FIELDS, 0)
    for suite in suites:
        for field in FIELDS:
            totals[field] += int(suite.get(field, 0))
    return totals


def collected(listing: Path) -> int:
    """Tests in `pytest --collect-only -q` output: one node id ("path::name") per line."""
    return sum("::" in line for line in listing.read_text(encoding="utf-8").splitlines())


def problems(totals: dict[str, int], min_tests: int) -> list[str]:
    found = []
    if min_tests < 1:
        found.append("nothing was collected, so nothing was checked")
    if totals["skipped"]:
        found.append(f"{totals['skipped']} skipped: a skipped check proves nothing")
    if totals["tests"] < min_tests:
        found.append(f"{totals['tests']} ran, at least {min_tests} expected")
    if totals["failures"] or totals["errors"]:
        found.append(f"{totals['failures']} failed and {totals['errors']} errored")
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path)
    minimum = parser.add_mutually_exclusive_group(required=True)
    minimum.add_argument("--min-tests", type=int)
    minimum.add_argument(
        "--collected", type=Path, help="pytest --collect-only -q output: every test must run"
    )
    args = parser.parse_args(argv)
    for path, what in ((args.report, "test report"), (args.collected, "collection listing")):
        if path and not path.is_file():
            print(f"gate failed: no {what} at {path}")
            return 1
    min_tests = collected(args.collected) if args.collected else args.min_tests
    totals = counts(args.report)
    found = problems(totals, min_tests)
    for problem in found:
        print(f"gate failed: {problem}")
    if not found:
        print(f"gate passed: {totals['tests']} ran, none skipped")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
