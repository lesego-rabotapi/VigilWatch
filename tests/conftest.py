import os

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
