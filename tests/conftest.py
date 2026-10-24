import json
import os
import re

import boto3
import pytest
from moto import mock_aws

# Fake credentials so no test can ever reach a real AWS account.
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "af-south-1"
os.environ["AWS_REGION"] = "af-south-1"
os.environ["ENDPOINTS_TABLE"] = "vigilwatch-endpoints"
os.environ["HISTORY_TABLE"] = "vigilwatch-history"


@pytest.fixture
def aws():
    with mock_aws():
        yield


def _create_table(name, key_schema, attributes):
    boto3.client("dynamodb").create_table(
        TableName=name,
        KeySchema=key_schema,
        AttributeDefinitions=attributes,
        BillingMode="PROVISIONED",
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )


@pytest.fixture
def tables(aws):
    """Tables mirroring terraform/dynamo.tf."""
    _create_table(
        os.environ["ENDPOINTS_TABLE"],
        [{"AttributeName": "endpoint_id", "KeyType": "HASH"}],
        [{"AttributeName": "endpoint_id", "AttributeType": "S"}],
    )
    _create_table(
        os.environ["HISTORY_TABLE"],
        [
            {"AttributeName": "endpoint_id", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "endpoint_id", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
    )
    yield


@pytest.fixture
def sns_topic(aws, monkeypatch):
    arn = boto3.client("sns").create_topic(Name="vigilwatch-alerts")["TopicArn"]
    monkeypatch.setenv("SNS_TOPIC_ARN", arn)
    return arn


@pytest.fixture
def alerts(tables, sns_topic):
    """Subscribe an SQS queue to the alert topic so published alerts can be read back."""
    sqs = boto3.client("sqs")
    queue_url = sqs.create_queue(QueueName="alerts")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]
    boto3.client("sns").subscribe(TopicArn=sns_topic, Protocol="sqs", Endpoint=queue_arn)

    def read():
        msgs = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get("Messages", [])
        for m in msgs:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=m["ReceiptHandle"])
        return [json.loads(m["Body"]) for m in msgs]

    return read


def pytest_bdd_apply_tag(tag, function):
    """Gherkin tags like @VW-001 become the `req` marker; other tags behave as usual."""
    if re.fullmatch(r"VW-\d{3}", tag):
        pytest.mark.req(tag)(function)
        return True
    return None
