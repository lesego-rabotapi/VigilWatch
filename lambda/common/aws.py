"""Process-wide boto3 clients.

Creating a boto3 client or resource costs tens of milliseconds, so it happens once per
execution environment (cold start) and is reused by every later invocation. Clients are
created lazily, on first use rather than at import, so modules import cheaply and tests can
mock AWS before anything is built.
"""

from functools import cache

import boto3


@cache
def dynamodb_resource():
    return boto3.resource("dynamodb")


@cache
def sns_client():
    return boto3.client("sns")


def reset() -> None:
    """Drop cached clients (tests only: a client must not outlive the mock it was built in)."""
    dynamodb_resource.cache_clear()
    sns_client.cache_clear()
