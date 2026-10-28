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
from common.endpoints_repo import COUNTER_ID, EndpointRepository

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
    {"endpoint_id": "_system#count", "n": Decimal(2)},
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


def test_a_wiped_table_is_restored_exactly_but_for_the_counter(table, tmp_path):
    """The backup's counter is not written; the live one is set to the real count (see below)."""
    out = tmp_path / "endpoints.jsonl"
    backup_tables.backup(TABLE, out)
    before = everything(table)
    for item in before:
        table.delete_item(Key={"endpoint_id": item["endpoint_id"]})
    assert everything(table) == []
    assert restore_tables.restore(TABLE, out) == 2
    assert everything(table) == before, "the counter is set to the real count, which was 2"


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
    assert EndpointRepository(t).count() == 130


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
    assert "restored 2 items" in capsys.readouterr().out


def test_the_cap_counter_is_rebuilt_from_the_real_count_not_restored_stale(table, tmp_path):
    """A restored counter lower than the real count would let registrations pass the cap. The
    restore leaves the backup's counter out and sets the live one to the real count. It never
    deletes it: a registration racing a missing counter would start it again from zero."""
    out = tmp_path / "endpoints.jsonl"
    backup_tables.backup(TABLE, out)  # the counter says 2
    for n in range(3):
        table.put_item(Item={"endpoint_id": f"https://new{n}.example", "enabled": True})
    table.put_item(Item={"endpoint_id": COUNTER_ID, "n": Decimal(1)})  # stale and too low
    assert restore_tables.restore(TABLE, out) == 2, "the endpoints, not the counter"
    counter = table.get_item(Key={"endpoint_id": COUNTER_ID})["Item"]
    assert counter["n"] == EndpointRepository(table).count() == 5


def test_the_counter_repair_stands_down_and_retries_when_a_registration_lands(table, monkeypatch):
    """The counter is only rewritten if it still holds the value read before counting."""
    repo = EndpointRepository(table)
    real_count = EndpointRepository.count
    raced = []

    def count_while_someone_registers(self):
        if not raced:
            raced.append(True)
            table.put_item(Item={"endpoint_id": "https://racer.example"})
            table.update_item(
                Key={"endpoint_id": COUNTER_ID},
                UpdateExpression="SET n = n + :one",
                ExpressionAttributeValues={":one": 1},
            )
        return real_count(self)

    monkeypatch.setattr(EndpointRepository, "count", count_while_someone_registers)
    assert repo.repair_counter() == 3
    assert table.get_item(Key={"endpoint_id": COUNTER_ID})["Item"]["n"] == 3


def test_every_reserved_item_is_left_to_the_application(tables, tmp_path):
    """The application treats any id starting with '_' as its own bookkeeping."""
    t = boto3.resource("dynamodb").Table(TABLE)
    t.put_item(Item={"endpoint_id": "https://a.example"})
    t.put_item(Item={"endpoint_id": "_meta#schema", "v": Decimal(2)})
    out = tmp_path / "endpoints.jsonl"
    backup_tables.backup(TABLE, out)
    t.delete_item(Key={"endpoint_id": "_meta#schema"})
    assert restore_tables.restore(TABLE, out) == 1
    assert "Item" not in t.get_item(Key={"endpoint_id": "_meta#schema"})


def test_binary_values_and_nested_sets_round_trip_and_stay_byte_stable(tables, tmp_path):
    t = boto3.resource("dynamodb").Table(TABLE)
    item = {
        "endpoint_id": "https://bin.example",
        "blob": b"\x00\xffraw",
        "blobs": {b"a", b"b"},
        "nested": {
            "codes": {Decimal(500), Decimal(200), Decimal(301)},
            "list": [{"tags": {"z", "a"}}],
        },
    }
    t.put_item(Item=item)
    first, second = tmp_path / "1.jsonl", tmp_path / "2.jsonl"
    backup_tables.backup(TABLE, first)
    backup_tables.backup(TABLE, second)
    assert first.read_bytes() == second.read_bytes()
    t.delete_item(Key={"endpoint_id": item["endpoint_id"]})
    restore_tables.restore(TABLE, first)
    restored = t.get_item(Key={"endpoint_id": item["endpoint_id"]})["Item"]
    assert restored["blob"].value == b"\x00\xffraw"
    assert {b.value for b in restored["blobs"]} == {b"a", b"b"}
    assert restored["nested"]["codes"] == {Decimal(200), Decimal(301), Decimal(500)}


def test_a_backup_has_unix_line_endings_on_every_platform(table, tmp_path):
    out = tmp_path / "endpoints.jsonl"
    backup_tables.backup(TABLE, out)
    assert b"\r\n" not in out.read_bytes()


@pytest.mark.negative
@pytest.mark.parametrize(
    "lines, reason",
    [
        (['{"endpoint_id": "untyped"}'], "typed"),
        (['{"endpoint_id": {"S": "a"}, "x": {"Q": "1"}}'], "typed"),
        (['{"endpoint_id": {"N": "1"}}'], "endpoint_id"),
        (['{"endpoint_id": {"S": "a"}}', '{"endpoint_id": {"S": "a"}}'], "twice"),
        (['{"endpoint_id": {"S": "a"}, "n": {"N": 5}}'], "typed"),
        (['{"endpoint_id": {"S": "a"}, "n": {"N": "five"}}'], "typed"),
        (['{"endpoint_id": {"S": "a"}, "tags": {"SS": []}}'], "typed"),
        (['{"endpoint_id": {"S": "a"}, "m": {"M": []}}'], "typed"),
        (['{"endpoint_id": {"S": "a"}, "b": {"BOOL": "yes"}}'], "typed"),
        (['{"endpoint_id": {"S": ""}}'], "empty"),
        (['{"endpoint_id": {"S": "a"}, "s": {"SS": ["x", "x"]}}'], "typed"),
        (['{"endpoint_id": {"S": "a"}, "s": {"NS": ["1", "1.0"]}}'], "typed"),
        (['{"endpoint_id": {"S": "a"}, "n": {"N": "1e200"}}'], "typed"),
        (['{"endpoint_id": {"S": "a"}, "n": {"N": "1_000"}}'], "typed"),
        (
            ['{"endpoint_id": {"S": "a"}, "n": {"N": "1234567890123456789012345678901234567890"}}'],
            "typed",
        ),
        (['{"endpoint_id": {"S": "a"}, "z": {"NULL": 1}}'], "typed"),
    ],
    ids=[
        "untyped-key",
        "unknown-type",
        "wrong-key-type",
        "duplicate",
        "number-not-text",
        "not-a-number",
        "empty-set",
        "map-not-object",
        "bool-not-bool",
        "empty-key",
        "repeated-string",
        "repeated-number",
        "number-too-large",
        "underscore-number",
        "too-many-digits",
        "null-not-true",
    ],
)
def test_a_damaged_backup_writes_nothing(table, tmp_path, lines, reason):
    """Checked whole before the first write, so a bad line late in the file cannot leave the
    table half restored."""
    good = [
        backup_tables.canonical({"endpoint_id": {"S": f"https://ok{n}.example"}}) for n in range(30)
    ]
    bad = tmp_path / "bad.jsonl"
    bad.write_text("\n".join(good + lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=reason):
        restore_tables.restore(TABLE, bad)
    assert not any(i["endpoint_id"].startswith("https://ok") for i in everything(table))


@pytest.mark.negative
def test_a_table_that_stays_throttled_fails_the_restore_instead_of_hanging():
    class Throttled:
        calls = 0

        def batch_write_item(self, RequestItems):  # noqa: N803 - boto3's own argument name
            Throttled.calls += 1
            return {"UnprocessedItems": RequestItems}

    items = [{"endpoint_id": {"S": "a"}}]
    with pytest.raises(RuntimeError, match="still throttled"):
        restore_tables.write(Throttled(), TABLE, items, pause=0)
    assert Throttled.calls == restore_tables.MAX_ATTEMPTS


@pytest.mark.negative
def test_the_same_key_written_two_ways_is_still_a_duplicate(tmp_path):
    keys = {"n": "N"}
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"n": {"N": "1"}}\n{"n": {"N": "1.0"}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="twice"):
        restore_tables.read_backup(bad, keys)


def test_a_history_backup_keeps_the_checkers_heartbeat(tables, tmp_path):
    """Leaving out '_' items is the endpoints table's rule; the history table's '_system'
    heartbeat is data like any other there."""
    history = boto3.resource("dynamodb").Table("vigilwatch-history")
    history.put_item(Item={"endpoint_id": "_system", "sk": "H#checker", "at": "2026-10-28"})
    history.put_item(Item={"endpoint_id": "abc", "sk": "C#2026-10-28T00:00:00Z"})
    out = tmp_path / "history.jsonl"
    backup_tables.backup("vigilwatch-history", out)
    history.delete_item(Key={"endpoint_id": "_system", "sk": "H#checker"})
    assert restore_tables.restore("vigilwatch-history", out) == 2
    assert "Item" in history.get_item(Key={"endpoint_id": "_system", "sk": "H#checker"})


def test_the_counter_is_repaired_through_the_client_the_restore_was_given(aws, tmp_path):
    """Not the default region: a restore into another region must repair that region's counter."""
    client = boto3.client("dynamodb", region_name="eu-west-1")
    client.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "endpoint_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "endpoint_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    out = tmp_path / "endpoints.jsonl"
    out.write_text('{"endpoint_id":{"S":"https://a.example"}}\n', encoding="utf-8")
    assert restore_tables.restore(TABLE, out, client=client) == 1
    counter = client.get_item(TableName=TABLE, Key={"endpoint_id": {"S": COUNTER_ID}})
    assert counter["Item"]["n"] == {"N": "1"}


def test_a_counter_without_its_number_is_repaired_not_a_crash(table):
    """A counter item edited by hand to lose `n` used to raise KeyError on the cap path."""
    table.put_item(Item={"endpoint_id": COUNTER_ID})
    repo = EndpointRepository(table)
    assert repo._reconcile(10) is True
    assert table.get_item(Key={"endpoint_id": COUNTER_ID})["Item"]["n"] == repo.count() == 2
