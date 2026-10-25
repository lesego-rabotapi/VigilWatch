"""How long each kind of data is kept (enforced by the table TTL, see terraform/dynamo.tf)."""

from datetime import timedelta

RAW_TTL = timedelta(hours=48)
ROLLUP_TTL = timedelta(days=31)
UPTIME_WINDOW_DAYS = 30
