"""Fixtures for the integration layer: a moto server, the real tables, and local HTTP front ends."""

import json
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import boto3
import pytest

import local_api
from tests.integration.backend import BackendUnavailable, require, running_in_ci, start_server


@pytest.fixture(scope="session")
def moto_endpoint():
    try:
        server, endpoint = start_server()
    except BackendUnavailable as exc:
        require(exc, ci=running_in_ci())
        raise  # unreachable: require() always skips or fails
    previous = os.environ.get("AWS_ENDPOINT_URL")
    os.environ["AWS_ENDPOINT_URL"] = endpoint  # botocore sends every client here
    yield endpoint
    if previous is None:
        os.environ.pop("AWS_ENDPOINT_URL", None)
    else:
        os.environ["AWS_ENDPOINT_URL"] = previous
    server.stop()


def _reset(endpoint: str) -> None:
    request = urllib.request.Request(f"{endpoint}/moto-api/reset", method="POST")  # noqa: S310
    urllib.request.urlopen(request, timeout=10).close()  # noqa: S310


class Stack:
    """The tables, topic and subscribed queue of one test, over the moto server."""

    def __init__(self, topic_arn: str, queue_url: str):
        self.topic_arn = topic_arn
        self._queue_url = queue_url

    def alerts(self) -> list[dict]:
        """Alert payloads published since the last call, read back through SQS."""
        sqs = boto3.client("sqs")
        found = []
        for _ in range(3):  # a message may need a moment to cross SNS
            messages = sqs.receive_message(
                QueueUrl=self._queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
            ).get("Messages", [])
            for message in messages:
                sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=message["ReceiptHandle"])
                envelope = json.loads(message["Body"])
                found.append(json.loads(envelope["Message"]))
            if found:
                break
        return found


@pytest.fixture
def stack(moto_endpoint, monkeypatch):
    from common import aws as aws_clients

    _reset(moto_endpoint)
    aws_clients.reset()
    dynamodb = boto3.client("dynamodb")
    capacity = {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
    dynamodb.create_table(
        TableName=os.environ["ENDPOINTS_TABLE"],
        KeySchema=[{"AttributeName": "endpoint_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "endpoint_id", "AttributeType": "S"}],
        ProvisionedThroughput=capacity,
    )
    dynamodb.create_table(
        TableName=os.environ["HISTORY_TABLE"],
        KeySchema=[
            {"AttributeName": "endpoint_id", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "endpoint_id", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        ProvisionedThroughput=capacity,
    )
    topic_arn = boto3.client("sns").create_topic(Name="vigilwatch-alerts")["TopicArn"]
    monkeypatch.setenv("SNS_TOPIC_ARN", topic_arn)
    sqs = boto3.client("sqs")
    queue_url = sqs.create_queue(QueueName="alerts")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]
    boto3.client("sns").subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)
    yield Stack(topic_arn, queue_url)
    aws_clients.reset()


class Target:
    """A local web server whose status code a test can change between checker runs."""

    def __init__(self):
        self.status = 200
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(owner.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/health"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def target():
    server = Target()
    yield server
    server.close()


@pytest.fixture
def local_targets(monkeypatch):
    """Let the handlers probe 127.0.0.1. The SSRF guard is unit-tested; here the target is ours."""
    import register_endpoint
    import uptime_check
    from common.probe import probe as real_probe
    from common.urlguard import normalize

    def allow(url, timeout=5):
        return real_probe(url, timeout=timeout, validator=normalize)

    monkeypatch.setattr(register_endpoint, "validate", lambda url, resolver=None: normalize(url))
    monkeypatch.setattr(register_endpoint, "probe", allow)
    monkeypatch.setattr(uptime_check, "probe", allow)


class _Api(local_api.Handler):
    def log_message(self, *args):
        pass


@pytest.fixture
def api(stack, local_targets):
    """The real handlers behind the local HTTP adapter (API Gateway's event shape, one user)."""
    import get_checks
    import register_endpoint

    _Api.routes = {
        ("POST", "/register"): register_endpoint.lambda_handler,
        ("GET", "/checks"): get_checks.lambda_handler,
    }
    server = HTTPServer(("127.0.0.1", 0), _Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
