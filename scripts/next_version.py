"""Print the next release tag, v2.<n>, from the tags that already exist.

The workflow run number is not used: it restarts when a workflow file is renamed, and the old
pipeline already tagged v1.<run number>. Standard library only.

    git tag --list | python scripts/next_version.py
"""

import argparse
import re
import sys

MAJOR = 2


def next_tag(tags, major: int = MAJOR) -> str:
    pattern = re.compile(rf"v{major}\.(\d+)")
    numbers = [int(m.group(1)) for tag in tags if (m := pattern.fullmatch(tag.strip()))]
    return f"v{major}.{max(numbers, default=0) + 1}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    print(next_tag(sys.stdin.read().split()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
