"""The Lambda bundle is built once and must be byte-identical wherever and whenever it is built.

Promotion relies on this: production deploys the exact bytes development ran, and the hash
Terraform checks is the hash of those bytes.
"""

import base64
import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest

import build_bundle

pytestmark = pytest.mark.req("VW-017")

ROOT = Path(__file__).resolve().parent.parent.parent


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
    assert build_bundle.main(["--source", str(src), "--out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["bundle_path"] == str(out)
    assert printed["bundle_sha256"] == build_bundle.build(src, tmp_path / "c.zip").base64sha256
    assert json.loads(out.with_name("b.tfvars.json").read_text()) == printed
