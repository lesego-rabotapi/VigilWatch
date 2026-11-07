import pytest

from common import aws

pytestmark = pytest.mark.req("VW-020")


def test_clients_are_cached_per_process():
    aws.reset()
    assert aws.dynamodb_resource() is aws.dynamodb_resource()
    assert aws.sns_client() is aws.sns_client()


def test_reset_drops_the_cached_clients():
    first = aws.dynamodb_resource()
    aws.reset()
    assert aws.dynamodb_resource() is not first
