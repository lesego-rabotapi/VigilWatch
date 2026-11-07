"""Summarise Lambda cold starts from the REPORT lines in a function's logs.

Lambda writes one REPORT line per invocation; a cold start carries an "Init Duration". This script
only reads text, so the numbers are exactly what the platform logged. Percentiles are nearest-rank
(the smallest value with at least that share of samples at or below it), with no interpolation.
Standard library only.

    aws logs tail /aws/lambda/<function> --since 1d | python scripts/measure_cold_start.py
    python scripts/measure_cold_start.py logs.txt --markdown --region af-south-1 --runtime py312
"""

import argparse
import math
import re
import sys
from datetime import date

_REPORT = re.compile(
    r"REPORT RequestId:\s*\S+\s+Duration:\s*(?P<duration>[\d.]+) ms"
    r"\s+Billed Duration:\s*(?P<billed>[\d.]+) ms"
    r"\s+Memory Size:\s*(?P<memory>\d+) MB"
    r"\s+Max Memory Used:\s*(?P<max_memory>\d+) MB"
    r"(?:\s+Init Duration:\s*(?P<init>[\d.]+) ms)?"
)


def parse_report(line: str) -> dict | None:
    """The fields of one REPORT line, or None if the line is anything else."""
    match = _REPORT.search(line)
    if not match:
        return None
    return {
        "duration_ms": float(match["duration"]),
        "init_ms": float(match["init"]) if match["init"] else None,
        "billed_ms": round(float(match["billed"])),
        "memory_mb": int(match["memory"]),
        "max_memory_mb": int(match["max_memory"]),
    }


def percentile(values, p: int):
    """Nearest-rank percentile, or None for no samples."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p * len(ordered) / 100)) - 1]


def summarise(records: list[dict]) -> dict:
    cold = [r for r in records if r["init_ms"] is not None]
    warm = [r for r in records if r["init_ms"] is None]
    inits = [r["init_ms"] for r in cold]
    return {
        "invocations": len(records),
        "cold_starts": len(cold),
        "memory_mb": records[0]["memory_mb"] if records else None,
        "init_p50_ms": percentile(inits, 50),
        "init_p95_ms": percentile(inits, 95),
        "cold_duration_p50_ms": percentile([r["duration_ms"] for r in cold], 50),
        "cold_duration_p95_ms": percentile([r["duration_ms"] for r in cold], 95),
        "warm_duration_p50_ms": percentile([r["duration_ms"] for r in warm], 50),
        "warm_duration_p95_ms": percentile([r["duration_ms"] for r in warm], 95),
    }


def _cell(value) -> str:
    """The value exactly as parsed: no significant-digit cut-off, no exponent form."""
    return "n/a" if value is None else str(value)


def _read(path: str | None, stdin) -> str:
    """Log text from a file or standard input; Windows PowerShell redirects write UTF-16."""
    if not path:
        return (stdin or sys.stdin).read()
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def markdown_row(summary: dict, label: str, when: str, region: str, runtime: str) -> str:
    cells = [
        label,
        when,
        region,
        f"{summary['memory_mb']} MB",
        runtime,
        summary["invocations"],
        summary["cold_starts"],
        _cell(summary["init_p50_ms"]),
        _cell(summary["init_p95_ms"]),
        _cell(summary["warm_duration_p50_ms"]),
        _cell(summary["warm_duration_p95_ms"]),
    ]
    return "| " + " | ".join(str(c) for c in cells) + " |"


def main(argv=None, stdin=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", nargs="?", help="a log file; standard input if omitted")
    parser.add_argument("--markdown", action="store_true", help="print a docs/performance.md row")
    parser.add_argument("--label", default="")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--region", default="")
    parser.add_argument("--runtime", default="")
    args = parser.parse_args(argv)

    lines = _read(args.logs, stdin).splitlines()
    records = [r for r in map(parse_report, lines) if r]
    if not records:
        raise SystemExit("no Lambda REPORT lines found in the input; nothing to summarise")
    sizes = sorted({r["memory_mb"] for r in records})
    if len(sizes) > 1:
        raise SystemExit(
            f"the input mixes memory sizes {sizes} MB; summarise one configuration at a time"
        )
    skipped = sum("REPORT RequestId:" in line for line in lines) - len(records)
    summary = summarise(records)
    if args.markdown:
        print(markdown_row(summary, args.label, args.date, args.region, args.runtime))
        if skipped:
            print(
                f"warning: {skipped} REPORT line(s) could not be parsed and were left out",
                file=sys.stderr,
            )
    else:
        for key, value in {**summary, "skipped_report_lines": skipped}.items():
            print(f"{key}: {_cell(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
