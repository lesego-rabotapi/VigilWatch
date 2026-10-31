"""Print one section of docs/RELEASE_CHECKLIST.md, for a deploy's GitHub job summary.

python scripts/checklist.py pre  >> "$GITHUB_STEP_SUMMARY"
python scripts/checklist.py post >> "$GITHUB_STEP_SUMMARY"
"""

import argparse
import sys
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "RELEASE_CHECKLIST.md"
HEADINGS = {"pre": "Pre-deployment", "post": "Post-deployment"}


def section(phase: str) -> str:
    if phase not in HEADINGS:
        raise ValueError(f"unknown phase {phase!r}; choose one of: {', '.join(HEADINGS)}")
    text = DOC.read_text(encoding="utf-8")
    start = text.index(f"## {HEADINGS[phase]}")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else None].rstrip() + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=sorted(HEADINGS))
    print(section(parser.parse_args(argv).phase), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
