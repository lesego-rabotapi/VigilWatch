import os
import sys
import types

os.environ.setdefault("AWS_REGION", "af-south-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "af-south-1")


if "boto3" not in sys.modules:
    fake_boto3 = types.ModuleType("boto3")

    def _fake_resource(*args, **kwargs):
        class FakeTable:
            def scan(self, *a, **k):
                return {"Items": []}

            def put_item(self, *a, **k):
                return {}

        class FakeDynamo:
            def Table(self, name):
                return FakeTable()

        return FakeDynamo()

    def _fake_client(*args, **kwargs):
        class FakeClient:
            def put_metric_data(self, *a, **k):
                return {}

            def publish(self, *a, **k):
                return {}

        return FakeClient()

    fake_boto3.resource = _fake_resource
    fake_boto3.client = _fake_client
    sys.modules["boto3"] = fake_boto3