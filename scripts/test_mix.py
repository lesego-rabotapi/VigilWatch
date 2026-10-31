"""Report how many tests each layer has and how many target failure paths.

    python scripts/test_mix.py                          # print a markdown table
    python scripts/test_mix.py >> "$GITHUB_STEP_SUMMARY"  # in CI

Counts come from collecting the suite (no tests run). The e2e layer is excluded, as in the
default run.
"""

import contextlib
import io
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from tests.taxonomy import LAYERS  # noqa: E402

KINDS = ("negative", "boundary", "security")


def summarize(items) -> dict[str, dict[str, int]]:
    rows: dict[str, Counter] = {}
    for test in items:
        names = {marker.name for marker in test.iter_markers()}
        layers = names & set(LAYERS)
        if not layers:
            continue
        row = rows.setdefault(next(iter(layers)), Counter())
        row["tests"] += 1
        for kind in KINDS:
            if kind in names:
                row[kind] += 1
    return {
        layer: {"tests": row["tests"], **{kind: row[kind] for kind in KINDS}}
        for layer, row in sorted(rows.items(), key=lambda pair: LAYERS.index(pair[0]))
    }


def render(rows: dict[str, dict[str, int]]) -> str:
    lines = [
        "### Test mix",
        "",
        "| Layer | Tests | negative | boundary | security |",
        "|---|---|---|---|---|",
    ]
    totals = Counter()
    for layer, row in rows.items():
        cells = " | ".join(str(row[key]) for key in ("tests", *KINDS))
        lines.append(f"| {layer} | {cells} |")
        totals.update(row)
    lines.append(
        f"| **Total** | {totals['tests']} | {totals['negative']} | {totals['boundary']} "
        f"| {totals['security']} |"
    )
    share = 100 * totals["negative"] / totals["tests"] if totals["tests"] else 0
    lines += [
        "",
        f"{totals['negative']} of {totals['tests']} tests are negative-marked ({share:.0f}%). "
        "Many parametrised rejection cases sit inside tests that are not individually marked, "
        "so this understates failure-path coverage.",
    ]
    return "\n".join(lines) + "\n"


class _Collector:
    items: list = []

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        self.items = list(items)


def main() -> int:
    collector = _Collector()
    with contextlib.redirect_stdout(io.StringIO()):  # collect-only lists every test name
        code = pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider"], plugins=[collector])
    if code not in (0, pytest.ExitCode.OK):
        print("collection failed", file=sys.stderr)
        return int(code)
    print(render(summarize(collector.items)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
