"""The endpoints table can be dumped to a file and written back, losslessly and idempotently.

Point-in-time recovery is not used (it is billed, decision D3), so a logical backup is the way back
from a deleted or damaged table. History is not backed up: it is TTL data the checker rebuilds.
"""

import json
from decimal import Decimal

import boto3
import pytest

import backup_tables
import restore_tables

pytestmark = pytest.mark.req("VW-024")

TABLE = "vigilwatch-endpoints"
ITEMS = [
    {"endpoint_id": "https://a.example", "enabled": True, "expected_status": Decimal(200)},
    {
        "endpoint_id": "https://b.example/x?y=1",
        "enabled": False,
        "tags": {"team": "ops"},
        "failures": Decimal(3),
        "ratio": Decimal("0.25"),
        "codes": {Decimal(200), Decimal(301)},
        "note": None,
    },
    {"endpoint_id": "_system#count", "count": Decimal(2)},
]


@pytest.fixture
def table(tables):
    t = boto3.resource("dynamodb").Table(TABLE)
    for item in ITEMS:
        t.put_item(Item=item)
    return t


def everything(table):
    return sorted(table.scan()["Items"], key=lambda i: i["endpoint_id"])


def test_a_backup_holds_every_item_with_its_dynamodb_types(table, tmp_path):
    out = tmp_path / "endpoints.jsonl"
    assert backup_tables.backup(TABLE, out) == 3
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    items = [json.loads(line) for line in lines]
    assert [i["endpoint_id"]["S"] for i in items] == sorted(i["endpoint_id"] for i in ITEMS)
    b = next(i for i in items if i["endpoint_id"]["S"].startswith("https://b"))
    assert b["codes"] == {"NS": ["200", "301"]} and b["note"] == {"NULL": True}


def test_two_backups_of_the_same_table_are_identical(table, tmp_path):
    backup_tables.backup(TABLE, tmp_path / "1.jsonl")
    backup_tables.backup(TABLE, tmp_path / "2.jsonl")
    assert (tmp_path / "1.jsonl").read_bytes() == (tmp_path / "2.jsonl").read_bytes()


def test_a_wiped_table_is_restored_exactly(table, tmp_path):
    out = tmp_path / "endpoints.jsonl"
    backup_tables.backup(TABLE, out)
    before = everything(table)
    for item in before:
        table.delete_item(Key={"endpoint_id": item["endpoint_id"]})
    assert everything(table) == []
    assert restore_tables.restore(TABLE, out) == 3
    assert everything(table) == before


def test_restoring_twice_leaves_the_same_table(table, tmp_path):
    out = tmp_path / "endpoints.jsonl"
    backup_tables.backup(TABLE, out)
    restore_tables.restore(TABLE, out)
    once = everything(table)
    restore_tables.restore(TABLE, out)
    assert everything(table) == once


def test_a_large_table_is_read_and_written_in_pages(tables, tmp_path):
    t = boto3.resource("dynamodb").Table(TABLE)
    with t.batch_writer() as batch:
        for n in range(130):
            batch.put_item(Item={"endpoint_id": f"https://{n:03}.example", "pad": "x" * 9000})
    out = tmp_path / "endpoints.jsonl"
    assert backup_tables.backup(TABLE, out) == 130  # more than one 1 MB scan page
    for n in range(130):
        t.delete_item(Key={"endpoint_id": f"https://{n:03}.example"})
    assert restore_tables.restore(TABLE, out) == 130  # more than one 25-item batch
    assert t.scan(Select="COUNT")["Count"] == 130


@pytest.mark.negative
def test_restore_refuses_a_line_that_is_not_an_item(table, tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"endpoint_id": {"S": "ok"}}\nnot json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        restore_tables.restore(TABLE, bad)


@pytest.mark.negative
def test_restore_refuses_an_item_without_the_table_key(table, tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"url": {"S": "https://x.example"}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="endpoint_id"):
        restore_tables.restore(TABLE, bad)
    assert len(everything(table)) == 3, "nothing is written from a bad file"


def test_the_commands_print_what_they_did(table, tmp_path, capsys):
    out = tmp_path / "endpoints.jsonl"
    assert backup_tables.main(["--table", TABLE, "--out", str(out)]) == 0
    assert "3 items" in capsys.readouterr().out
    assert restore_tables.main(["--table", TABLE, "--from", str(out)]) == 0
    assert "3 items" in capsys.readouterr().out
