"""Release notes from the conventional commit subjects in a range, grouped by type.

Every change lands as a failing-test commit followed by its fix, so test commits are left out:
the fix that made them pass is the change. Standard library only.

    python scripts/changelog.py v2.6..HEAD --version v2.7 > notes.md
"""

import argparse
import re
import subprocess
import sys

CONVENTIONAL = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?: (?P<text>.+)$"
)
SECTIONS = {"feat": "Features", "fix": "Fixes", "docs": "Documentation"}
OTHER = "Other changes"
LEFT_OUT = {"test"}


def _line(match: re.Match) -> str:
    scope = f"**{match['scope']}:** " if match["scope"] else ""
    breaking = "**BREAKING** " if match["breaking"] else ""
    return f"- {breaking}{scope}{match['text']}"


def render(version: str, subjects: list[str]) -> str:
    grouped: dict[str, list[str]] = {title: [] for title in [*SECTIONS.values(), OTHER]}
    for subject in subjects:
        if subject.startswith("Merge "):
            continue
        match = CONVENTIONAL.match(subject)
        if match is None:
            grouped[OTHER].append(f"- {subject}")
        elif match["type"] not in LEFT_OUT:
            grouped[SECTIONS.get(match["type"], OTHER)].append(_line(match))
    parts = [f"## {version}"]
    for title, lines in grouped.items():
        if lines:
            parts.append(f"### {title}\n\n" + "\n".join(lines))
    if len(parts) == 1:
        parts.append("No changes since the previous release.")
    return "\n\n".join(parts) + "\n"


def subjects(revision_range: str, repo: str = ".") -> list[str]:
    out = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        ["git", "log", "--no-merges", "--reverse", "--format=%s", revision_range],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("range", help="a git revision range, such as v2.6..HEAD, or one commit")
    parser.add_argument("--version", required=True)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    print(render(args.version, subjects(args.range, args.repo)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
