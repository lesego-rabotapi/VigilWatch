"""Build the Lambda bundle once, deterministically, and print what Terraform needs to deploy it.

The same bytes must reach every environment: development runs the bundle, production deploys
that very file. That only works if building is reproducible, so entries are sorted, timestamps
and permissions are fixed, and nothing about the build machine ends up in the archive. Entries are
stored, not deflated: deflate output depends on the zlib build, so a laptop and a CI runner could
otherwise produce different bytes from the same source. The bundle is small, so size is no concern.
Files are read from the commit (HEAD by default), not from disk, so a CRLF checkout or an untracked
file cannot change the bytes: commit first.

    python scripts/build_bundle.py --out terraform/.build/vigilwatch.zip
    python scripts/build_bundle.py --describe stored.zip     # variables for a bundle built earlier
"""

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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


def _packaged(name: str) -> bool:
    path = PurePosixPath(name)
    return not SKIPPED_DIRS & set(path.parts) and path.suffix not in SKIPPED_SUFFIXES


def _from_worktree(source: Path) -> dict[str, bytes]:
    return {
        name: p.read_bytes()
        for p in source.rglob("*")
        if p.is_file() and _packaged(name := p.relative_to(source).as_posix())
    }


def _git(*args: str, cwd: Path) -> bytes:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)  # noqa: S603, S607
    if result.returncode != 0:
        raise ValueError(f"git {args[0]} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def _from_commit(source: Path, rev: str) -> dict[str, bytes]:
    """The files under source as committed in rev: line endings and untracked files on disk
    cannot leak in."""
    top = Path(_git("rev-parse", "--show-toplevel", cwd=source).decode().strip()).resolve()
    prefix = PurePosixPath(source.resolve().relative_to(top).as_posix())  # "." at the top
    listed = _git("ls-tree", "-r", "-z", "--name-only", rev, "--", str(prefix), cwd=top)
    names = [n for n in listed.decode().split("\0") if n]
    return {
        name: _git("cat-file", "blob", f"{rev}:{path}", cwd=top)
        for path in names
        if _packaged(name := PurePosixPath(path).relative_to(prefix).as_posix())
    }


def _require_dir(source: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"source directory not found: {source}")


def _uncommitted(source: Path) -> list[str]:
    """Modified, staged or untracked files under source: what a build of HEAD would leave out."""
    _require_dir(source)
    status = _git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".", cwd=source)
    records, paths = iter(status.decode().split("\0")), []
    for record in records:
        if not record:
            continue
        paths.append(record[3:])  # "XY path"
        if record[0] in "RC":  # a rename or copy: the next record is the bare original path
            paths.append(next(records))
    return sorted(paths)


def build(source: Path, out: Path, rev: str | None = None) -> Manifest:
    """Bundle source as committed in rev, or as it is on disk when rev is None."""
    source, out = Path(source), Path(out).resolve()
    _require_dir(source)
    files = _from_commit(source, rev) if rev else _from_worktree(source)
    if not files:
        raise ValueError(f"nothing to package in {source}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as bundle:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = FILE_MODE
            info.create_system = 3  # Unix, whatever machine builds it
            bundle.writestr(info, files[name])
    return describe(out)


def describe(bundle: Path) -> Manifest:
    """The manifest of an existing bundle, such as the one dev stored and prod now deploys."""
    bundle = Path(bundle).resolve()
    if not bundle.is_file():
        raise FileNotFoundError(f"bundle not found: {bundle}")
    digest = hashlib.sha256(bundle.read_bytes()).digest()
    return Manifest(bundle, digest.hex(), base64.b64encode(digest).decode())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=ROOT / "lambda")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "terraform" / ".build" / "vigilwatch.zip"
    )
    parser.add_argument("--rev", default="HEAD", help="commit to bundle (default: HEAD)")
    parser.add_argument(
        "--from-worktree",
        action="store_true",
        help="bundle the files on disk instead, uncommitted changes included (not reproducible)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="build HEAD even though the source has uncommitted changes (they are left out)",
    )
    parser.add_argument(
        "--describe",
        type=Path,
        metavar="ZIP",
        help="do not build: write the Terraform variables for this existing bundle",
    )
    args = parser.parse_args(argv)
    if args.describe:
        _print_vars(describe(args.describe))
        return 0
    if not args.from_worktree and args.rev == "HEAD":
        left_out = _uncommitted(args.source)
        if left_out:
            what = f"uncommitted changes in {args.source} are not in HEAD: {', '.join(left_out)}"
            if not args.allow_dirty:
                hint = "commit them, or pass --allow-dirty to build HEAD without them"
                print(f"{what}\n{hint}", file=sys.stderr)
                return 1
            print(f"warning: {what}; building HEAD without them", file=sys.stderr)
    _print_vars(build(args.source, args.out, rev=None if args.from_worktree else args.rev))
    return 0


def _print_vars(manifest: Manifest) -> None:
    """Print the variables and write them next to the bundle; the keys are Terraform variable
    names, so the file is passed with -var-file."""
    printed = {"bundle_path": str(manifest.path), "bundle_sha256": manifest.base64sha256}
    manifest.path.with_name(manifest.path.stem + ".tfvars.json").write_text(
        json.dumps(printed, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(printed))


if __name__ == "__main__":
    sys.exit(main())
