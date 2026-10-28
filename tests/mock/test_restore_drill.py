"""A restore drill proves a backup can be restored, and how long that takes, without touching the
live table: it restores into a scratch table, compares, and always deletes the scratch table."""

import json
from decimal import Decimal

import boto3
import pytest

import backup_tables
import restore_drill
import restore_tables

pytestmark = pytest.mark.req("VW-024")

TABLE = "vigilwatch-endpoints"


@pytest.fixture
def backup(tables, tmp_path):
    t = boto3.resource("dynamodb").Table(TABLE)
    for n in range(12):
        t.put_item(Item={"endpoint_id": f"https://{n}.example", "failures": Decimal(n)})
    path = tmp_path / "endpoints.jsonl"
    backup_tables.backup(TABLE, path)
    return path


def table_names():
    return boto3.client("dynamodb").list_tables()["TableNames"]


def test_a_good_backup_passes_the_drill_and_leaves_no_scratch_table(backup):
    result = restore_drill.drill(TABLE, backup, sample=5)
    assert result.problems == []
    assert result.items == 12 and result.sampled == 5
    assert result.scratch.startswith(f"{TABLE}-drill-")
    assert result.scratch not in table_names()
    assert set(table_names()) == {TABLE, "vigilwatch-history"}, "the live tables are untouched"
    assert result.seconds >= 0


def test_the_drill_restores_into_a_table_with_the_sources_key(backup, monkeypatch):
    seen = {}
    real_write = restore_tables.write

    def spy(client, table, items, pause=0.5):
        seen["schema"] = client.describe_table(TableName=table)["Table"]["KeySchema"]
        return real_write(client, table, items, pause)

    monkeypatch.setattr(restore_tables, "write", spy)
    restore_drill.drill(TABLE, backup)
    assert seen["schema"] == [{"AttributeName": "endpoint_id", "KeyType": "HASH"}]


@pytest.mark.negative
def test_the_scratch_table_is_deleted_even_when_the_restore_fails(backup, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("throttled for good")

    monkeypatch.setattr(restore_tables, "write", broken)
    with pytest.raises(RuntimeError):
        restore_drill.drill(TABLE, backup)
    assert set(table_names()) == {TABLE, "vigilwatch-history"}


@pytest.mark.negative
def test_a_missing_item_is_reported():
    backup = [{"endpoint_id": {"S": "a"}}, {"endpoint_id": {"S": "b"}}]
    problems = restore_drill.compare(backup, backup[:1], ["endpoint_id"], sample=2)
    assert any("2 items in the backup, 1 restored" in p for p in problems)


@pytest.mark.negative
def test_a_changed_item_is_reported():
    backup = [{"endpoint_id": {"S": "a"}, "failures": {"N": "1"}}]
    restored = [{"endpoint_id": {"S": "a"}, "failures": {"N": "2"}}]
    problems = restore_drill.compare(backup, restored, ["endpoint_id"], sample=1)
    assert problems and "a" in problems[0]


def test_the_sample_is_the_same_on_every_run():
    backup = [{"endpoint_id": {"S": str(n)}} for n in range(40)]
    first = restore_drill.choose(backup, 7)
    assert first == restore_drill.choose(backup, 7) and len(first) == 7
    assert restore_drill.choose(backup, 99) == backup, "a small table is compared whole"


def test_the_command_prints_a_row_for_the_drill_log(backup, capsys):
    assert restore_drill.main(["--table", TABLE, "--from", str(backup)]) == 0
    row = capsys.readouterr().out.strip().splitlines()[-1]
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert len(cells) == 7, row
    assert cells[1] == TABLE and cells[3] == "12" and cells[6] == "pass"


@pytest.mark.negative
def test_the_command_fails_when_the_restore_does_not_match(backup, capsys, monkeypatch):
    lines = backup.read_text(encoding="utf-8").splitlines()
    item = json.loads(lines[0])
    item["failures"] = {"N": "999"}

    def tampered(client, table, items, pause=0.5):
        restore_tables.real_write(client, table, [item, *items[1:]], pause)

    monkeypatch.setattr(restore_tables, "real_write", restore_tables.write, raising=False)
    monkeypatch.setattr(restore_tables, "write", tampered)
    assert restore_drill.main(["--table", TABLE, "--from", str(backup)]) == 1
    assert "fail" in capsys.readouterr().out


@pytest.mark.negative
def test_the_scratch_table_is_deleted_even_when_waiting_for_it_fails(backup):
    client = boto3.client("dynamodb")

    class Stuck:
        def wait(self, **_kwargs):
            raise RuntimeError("waiter gave up")

    client.get_waiter = lambda _name: Stuck()
    with pytest.raises(RuntimeError, match="waiter gave up"):
        restore_drill.drill(TABLE, backup, client=client)
    assert set(table_names()) == {TABLE, "vigilwatch-history"}


@pytest.mark.negative
@pytest.mark.parametrize("sample", [0, -1])
def test_a_sample_below_one_is_refused_before_anything_is_created(backup, sample):
    with pytest.raises(ValueError, match="sample"):
        restore_drill.drill(TABLE, backup, sample=sample)
    assert set(table_names()) == {TABLE, "vigilwatch-history"}
    with pytest.raises(SystemExit):
        restore_drill.main(["--table", TABLE, "--from", str(backup), "--sample", str(sample)])


def test_a_backup_with_the_cap_counter_passes_the_drill(tables, tmp_path):
    t = boto3.resource("dynamodb").Table(TABLE)
    t.put_item(Item={"endpoint_id": "https://a.example"})
    t.put_item(Item={"endpoint_id": "_system#count", "n": Decimal(1)})
    path = tmp_path / "endpoints.jsonl"
    backup_tables.backup(TABLE, path)
    result = restore_drill.drill(TABLE, path)
    assert result.problems == [] and result.items == 1
