"""Build the Lambda bundle once, deterministically, and print what Terraform needs to deploy it.

The same bytes must reach every environment: development runs the bundle, production deploys
that very file. That only works if building is reproducible, so entries are sorted, timestamps
and permissions are fixed, and nothing about the build machine ends up in the archive. Entries are
stored, not deflated: deflate output depends on the zlib build, so a laptop and a CI runner could
otherwise produce different bytes from the same source. The bundle is small, so size is no concern.

    python scripts/build_bundle.py --out terraform/.build/vigilwatch.zip
"""

import argparse
import base64
import hashlib
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # the earliest time a zip can hold
FILE_MODE = 0o100644 << 16
SKIPPED_DIRS = {"__pycache__"}
SKIPPED_SUFFIXES = {".pyc", ".pyo", ".zip"}


@dataclass(frozen=True)
class Manifest:
    path: Path
    sha256_hex: str
    base64sha256: str  # the form Terraform's source_code_hash expects


def _sources(source: Path) -> list[Path]:
    files = [
        p
        for p in source.rglob("*")
        if p.is_file()
        and not SKIPPED_DIRS & set(p.relative_to(source).parts)
        and p.suffix not in SKIPPED_SUFFIXES
    ]
    return sorted(files, key=lambda p: p.relative_to(source).as_posix())


def build(source: Path, out: Path) -> Manifest:
    source, out = Path(source), Path(out).resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"source directory not found: {source}")
    files = _sources(source)
    if not files:
        raise ValueError(f"nothing to package in {source}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as bundle:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = FILE_MODE
            info.create_system = 3  # Unix, whatever machine builds it
            bundle.writestr(info, path.read_bytes())
    digest = hashlib.sha256(out.read_bytes()).digest()
    return Manifest(out, digest.hex(), base64.b64encode(digest).decode())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=ROOT / "lambda")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "terraform" / ".build" / "vigilwatch.zip"
    )
    args = parser.parse_args(argv)
    manifest = build(args.source, args.out)
    # The keys are Terraform variable names: pass the file with -var-file.
    printed = {"bundle_path": str(manifest.path), "bundle_sha256": manifest.base64sha256}
    args.out.with_name(args.out.stem + ".tfvars.json").write_text(
        json.dumps(printed, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(printed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
