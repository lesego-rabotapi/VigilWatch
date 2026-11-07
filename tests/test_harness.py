"""The test harness must exercise the real AWS SDK against moto, never a hand-rolled fake."""

import os

import boto3


def test_boto3_is_the_real_sdk():
    assert hasattr(boto3, "Session"), "conftest must not replace boto3 with a stub"
    assert boto3.__file__.endswith("__init__.py")


def test_tables_fixture_creates_moto_tables(tables):
    client = boto3.client("dynamodb")
    names = client.list_tables()["TableNames"]
    assert os.environ["ENDPOINTS_TABLE"] in names
    assert os.environ["HISTORY_TABLE"] in names


def test_sns_topic_fixture(sns_topic):
    arns = [t["TopicArn"] for t in boto3.client("sns").list_topics()["Topics"]]
    assert sns_topic in arns
    assert os.environ["SNS_TOPIC_ARN"] == sns_topic


def test_no_real_credentials_leak_into_tests():
    assert os.environ["AWS_ACCESS_KEY_ID"] == "testing"
