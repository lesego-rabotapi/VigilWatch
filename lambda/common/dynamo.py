"""Helpers for values read back from DynamoDB."""

from decimal import Decimal


def plain(value):
    """Convert DynamoDB Decimals (recursively) into int/float."""
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value
