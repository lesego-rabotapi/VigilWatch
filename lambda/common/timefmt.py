"""Timestamp formatting shared by storage and alerting."""

from datetime import datetime


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def epoch(moment: datetime) -> int:
    return int(moment.timestamp())
