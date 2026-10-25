"""Warm invocations must reuse boto3 clients instead of rebuilding them (cold-start rule)."""

import boto3
import pytest

import get_checks
from common.checker import make_publisher

pytestmark = pytest.mark.req("VW-020")


def _counting(monkeypatch, name):
    calls = []
    real = getattr(boto3, name)

    def counted(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(boto3, name, counted)
    return calls


def test_the_dynamodb_resource_is_created_at_most_once_across_invocations(tables, monkeypatch):
    calls = _counting(monkeypatch, "resource")
    event = {"queryStringParameters": {"url": "https://nothing.example.com/"}}
    for _ in range(3):
        assert get_checks.lambda_handler(event, None)["statusCode"] == 404
    assert len(calls) <= 1, f"boto3.resource called {len(calls)} times for 3 invocations"


def test_the_sns_client_is_created_at_most_once_across_publishers(sns_topic, monkeypatch):
    calls = _counting(monkeypatch, "client")
    for _ in range(3):
        assert make_publisher() is not None
    sns_calls = [c for c in calls if c and c[0] == "sns"]
    assert len(sns_calls) <= 1, f"boto3.client('sns') called {len(sns_calls)} times"
