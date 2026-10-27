"""The Lambda bundle is built once and must be byte-identical wherever and whenever it is built.

Promotion relies on this: production deploys the exact bytes development ran, and the hash
Terraform checks is the hash of those bytes.
"""

import base64
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

import build_bundle

pytestmark = pytest.mark.req("VW-017")

ROOT = Path(__file__).resolve().parent.parent.parent
# SHA-256 of the bundle of one file, handler.py containing "X = 1" and a newline. CI checks the same
# value on Linux, so a platform-dependent byte would fail there.
PINNED_DIGEST = "b38c26f7d55003c096a0b54b7647a867e6768946c4e4d4876ae25a1ddf6fcdd5"


def make_tree(base: Path) -> Path:
    src = base / "lambda"
    (src / "common").mkdir(parents=True)
    (src / "uptime_check.py").write_text("def lambda_handler(e, c):\n    return 1\n")
    (src / "common" / "__init__.py").write_text("")
    (src / "common" / "util.py").write_text("X = 1\n")
    return src


def entries(path: Path):
    with zipfile.ZipFile(path) as z:
        return z.infolist()


def test_two_builds_of_one_tree_are_byte_identical(tmp_path):
    src = make_tree(tmp_path)
    one = build_bundle.build(src, tmp_path / "one.zip")
    two = build_bundle.build(src, tmp_path / "two.zip")
    assert (tmp_path / "one.zip").read_bytes() == (tmp_path / "two.zip").read_bytes()
    assert one.sha256_hex == two.sha256_hex


def test_file_modification_times_do_not_change_the_bytes(tmp_path):
    src = make_tree(tmp_path)
    before = build_bundle.build(src, tmp_path / "before.zip")
    for path in src.rglob("*.py"):
        os.utime(path, (1_900_000_000, 1_900_000_000))
    after = build_bundle.build(src, tmp_path / "after.zip")
    assert before.sha256_hex == after.sha256_hex


def test_the_directory_it_is_built_from_does_not_change_the_bytes(tmp_path):
    first = build_bundle.build(make_tree(tmp_path / "a"), tmp_path / "a.zip")
    second = build_bundle.build(make_tree(tmp_path / "b"), tmp_path / "b.zip")
    assert first.sha256_hex == second.sha256_hex


def test_changing_a_source_file_changes_the_hash(tmp_path):
    src = make_tree(tmp_path)
    before = build_bundle.build(src, tmp_path / "before.zip")
    (src / "common" / "util.py").write_text("X = 2\n")
    after = build_bundle.build(src, tmp_path / "after.zip")
    assert before.sha256_hex != after.sha256_hex


def test_entries_are_sorted_with_a_fixed_timestamp_and_portable_names(tmp_path):
    src = make_tree(tmp_path)
    build_bundle.build(src, tmp_path / "b.zip")
    infos = entries(tmp_path / "b.zip")
    names = [i.filename for i in infos]
    assert names == sorted(names)
    assert all("\\" not in n and not n.startswith("/") for n in names)
    assert {i.date_time for i in infos} == {(1980, 1, 1, 0, 0, 0)}
    assert {i.external_attr >> 16 for i in infos} == {0o100644}


def test_caches_and_stale_archives_are_left_out(tmp_path):
    src = make_tree(tmp_path)
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\x00")
    (src / "common" / "stale.pyc").write_bytes(b"\x00")
    (src / "old.zip").write_bytes(b"PK")
    build_bundle.build(src, tmp_path / "b.zip")
    names = {i.filename for i in entries(tmp_path / "b.zip")}
    assert names == {"uptime_check.py", "common/__init__.py", "common/util.py"}


def test_the_manifest_hashes_match_the_bytes_on_disk(tmp_path):
    manifest = build_bundle.build(make_tree(tmp_path), tmp_path / "b.zip")
    digest = hashlib.sha256((tmp_path / "b.zip").read_bytes()).digest()
    assert manifest.sha256_hex == digest.hex()
    assert manifest.base64sha256 == base64.b64encode(digest).decode()
    assert manifest.path == tmp_path / "b.zip"


def test_a_missing_source_directory_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_bundle.build(tmp_path / "nope", tmp_path / "b.zip")


def test_an_empty_source_directory_is_an_error(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="nothing to package"):
        build_bundle.build(tmp_path / "empty", tmp_path / "b.zip")


def test_the_real_lambda_tree_bundles_every_handler_and_no_secrets(tmp_path):
    build_bundle.build(ROOT / "lambda", tmp_path / "real.zip")
    names = {i.filename for i in entries(tmp_path / "real.zip")}
    assert {"uptime_check.py", "register_endpoint.py", "get_checks.py", "common/state.py"} <= names
    assert not [n for n in names if n.endswith((".pyc", ".zip", ".env"))]


def test_the_command_line_prints_a_manifest_terraform_can_read(tmp_path, capsys):
    src = make_tree(tmp_path)
    out = tmp_path / "out" / "b.zip"
    assert build_bundle.main(["--source", str(src), "--out", str(out), "--from-worktree"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["bundle_path"] == str(out)
    assert printed["bundle_sha256"] == build_bundle.build(src, tmp_path / "c.zip").base64sha256
    assert json.loads(out.with_name("b.tfvars.json").read_text()) == printed


def test_a_stored_bundle_is_described_without_rebuilding_it(tmp_path, capsys):
    """Prod deploys the bytes dev stored: it only needs their path and hash for Terraform."""
    src = make_tree(tmp_path)
    stored = tmp_path / "fetched" / "vigilwatch.zip"
    manifest = build_bundle.build(src, stored)
    assert build_bundle.main(["--describe", str(stored)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"bundle_path": str(stored), "bundle_sha256": manifest.base64sha256}
    assert json.loads(stored.with_name("vigilwatch.tfvars.json").read_text()) == printed


@pytest.mark.negative
def test_describing_a_missing_bundle_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="bundle not found"):
        build_bundle.main(["--describe", str(tmp_path / "nope.zip")])


def test_entries_are_stored_uncompressed_so_no_zlib_version_can_change_the_bytes(tmp_path):
    """Deflate output differs between zlib builds; a dev laptop and a CI runner must agree."""
    build_bundle.build(make_tree(tmp_path), tmp_path / "b.zip")
    assert {i.compress_type for i in entries(tmp_path / "b.zip")} == {zipfile.ZIP_STORED}


def test_the_bytes_match_a_known_digest_on_every_machine(tmp_path):
    """Pinned: if this changes, the archive format changed and promoted builds would differ."""
    src = tmp_path / "lambda"
    src.mkdir()
    (src / "handler.py").write_bytes(b"X = 1\n")
    manifest = build_bundle.build(src, tmp_path / "pinned.zip")
    assert manifest.sha256_hex == PINNED_DIGEST


def test_a_relative_output_path_is_written_as_an_absolute_one(tmp_path, monkeypatch, capsys):
    """Terraform resolves bundle_path from terraform/envs/<env>, not from where the script ran."""
    src = make_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert build_bundle.main(["--source", str(src), "--out", "out/b.zip", "--from-worktree"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert Path(printed["bundle_path"]).is_absolute()
    assert Path(printed["bundle_path"]) == (tmp_path / "out" / "b.zip").resolve()


# ---- Built from the commit, not from whatever is on disk ---------------------------------------


def git(repo: Path, *args: str) -> str:
    config = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.autocrlf=false"]
    return subprocess.run(
        ["git", *config, *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def committed_tree(base: Path, *, dirty: bool = True) -> Path:
    """A repository whose lambda/ holds one committed file, then (dirty) a CRLF working copy of it
    and an untracked file."""
    repo = base / "repo"
    (repo / "lambda").mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "lambda" / "handler.py").write_bytes(b"X = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    if not dirty:
        return repo / "lambda"
    (repo / "lambda" / "handler.py").write_bytes(b"X = 1\r\n")  # a Windows checkout
    (repo / "lambda" / "scratch.py").write_bytes(b"secret = 1\n")  # never committed
    return repo / "lambda"


def test_a_build_from_a_commit_ignores_line_endings_and_untracked_files_on_disk(tmp_path):
    """A CRLF checkout or a stray file must not change what is deployed."""
    src = committed_tree(tmp_path)
    manifest = build_bundle.build(src, tmp_path / "b.zip", rev="HEAD")
    with zipfile.ZipFile(tmp_path / "b.zip") as z:
        assert z.namelist() == ["handler.py"]
        assert z.read("handler.py") == b"X = 1\n"
    assert manifest.sha256_hex == PINNED_DIGEST, "same bytes as the same file built anywhere else"


def test_the_command_line_builds_the_checked_out_commit_by_default(tmp_path, capsys):
    src = committed_tree(tmp_path, dirty=False)
    assert build_bundle.main(["--source", str(src), "--out", str(tmp_path / "b.zip")]) == 0
    printed = json.loads(capsys.readouterr().out)
    expected = build_bundle.build(src, tmp_path / "c.zip", rev="HEAD").base64sha256
    assert printed["bundle_sha256"] == expected


@pytest.mark.negative
def test_a_source_outside_a_repository_cannot_be_built_from_a_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))  # whatever encloses tmp_path
    with pytest.raises(ValueError, match="git"):
        build_bundle.build(make_tree(tmp_path), tmp_path / "b.zip", rev="HEAD")


def test_the_real_bundle_has_lf_line_endings_whatever_the_checkout(tmp_path):
    build_bundle.build(ROOT / "lambda", tmp_path / "real.zip", rev="HEAD")
    with zipfile.ZipFile(tmp_path / "real.zip") as z:
        assert [n for n in z.namelist() if b"\r\n" in z.read(n)] == []


def test_a_source_at_the_repository_root_keeps_whole_entry_names(tmp_path):
    """The root is prefix '.', which must not cost every name its first two characters."""
    repo = committed_tree(tmp_path).parent
    build_bundle.build(repo, tmp_path / "b.zip", rev="HEAD")
    with zipfile.ZipFile(tmp_path / "b.zip") as z:
        assert z.namelist() == ["lambda/handler.py"]


@pytest.mark.negative
@pytest.mark.parametrize("path", ["handler.py", "new_module.py"], ids=["modified", "untracked"])
def test_the_command_line_refuses_to_silently_drop_uncommitted_work(tmp_path, capsys, path):
    """Building HEAD over local edits would deploy old code while the developer tests the new."""
    src = committed_tree(tmp_path, dirty=False)
    (src / path).write_bytes(b"X = 2\n")
    assert build_bundle.main(["--source", str(src), "--out", str(tmp_path / "b.zip")]) == 1
    err = capsys.readouterr().err
    assert path in err and "commit" in err
    assert not (tmp_path / "b.zip").exists()


def test_allow_dirty_builds_the_commit_anyway_and_says_what_was_left_out(tmp_path, capsys):
    src = committed_tree(tmp_path)
    argv = ["--source", str(src), "--out", str(tmp_path / "b.zip"), "--allow-dirty"]
    assert build_bundle.main(argv) == 0
    assert "scratch.py" in capsys.readouterr().err
    with zipfile.ZipFile(tmp_path / "b.zip") as z:
        assert z.read("handler.py") == b"X = 1\n"


@pytest.mark.negative
def test_a_renamed_file_is_listed_by_its_real_paths(tmp_path, capsys):
    """A rename is two -z records: the second is a bare path with no status in front of it."""
    src = committed_tree(tmp_path, dirty=False)
    git(src.parent, "mv", "lambda/handler.py", "lambda/renamed.py")
    assert build_bundle.main(["--source", str(src), "--out", str(tmp_path / "b.zip")]) == 1
    listed = capsys.readouterr().err.splitlines()[0].split(": ", 1)[1]
    assert set(listed.split(", ")) == {"lambda/handler.py", "lambda/renamed.py"}


@pytest.mark.negative
def test_a_missing_source_is_reported_as_such_by_the_command(tmp_path):
    with pytest.raises(FileNotFoundError, match="source directory not found"):
        build_bundle.main(["--source", str(tmp_path / "nope"), "--out", str(tmp_path / "b.zip")])
