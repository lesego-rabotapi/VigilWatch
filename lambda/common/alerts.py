"""Publish alerts to the SNS topic."""

import json
import os

from common import aws, logs
from common.ports import Publisher

logger = logs.get_logger(__name__)


def make_publisher(topic_arn: str | None = None) -> Publisher:
    topic_arn = topic_arn or os.environ.get("SNS_TOPIC_ARN")
    if not topic_arn:
        return lambda subject, payload: False

    sns = aws.sns_client()

    def publish(subject: str, payload: dict) -> bool:
        # SNS subjects: ASCII, no newlines, at most 100 characters.
        safe_subject = subject.encode("ascii", "replace").decode().replace("\n", " ")[:100]
        try:
            sns.publish(
                TopicArn=topic_arn,
                Subject=safe_subject,
                Message=json.dumps(payload, indent=2),
            )
        except Exception:
            logger.exception("failed to publish alert")
            return False
        return True

    return publish
