"""The dashboard payload, shared by POST /register and GET /checks.

Shape is pinned by tests/contract/checks_response.schema.json, which the
frontend tests also load.
"""

from datetime import datetime

from common.repo import Repo

RECENT_POINTS = 20


def human_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def build_view(repo: Repo, endpoint: dict, now: datetime) -> dict:
    endpoint_id = endpoint["endpoint_id"]
    recent = repo.recent_checks(endpoint_id, limit=RECENT_POINTS)
    return {
        "endpoint_id": endpoint_id,
        "url": endpoint["url"],
        "status": endpoint.get("status", "UNKNOWN"),
        "uptime_30d": repo.uptime_30d(endpoint_id, now),
        "latest_latency_ms": endpoint.get("last_latency_ms"),
        "last_check": endpoint.get("last_check"),
        "last_alert_sent": endpoint.get("last_alert_sent"),
        # Oldest first, so the chart reads left to right.
        "recent_latencies": [
            {"ms": c["latency_ms"], "status": c["status"], "checked_at": c["checked_at"]}
            for c in reversed(recent)
        ],
        "incidents": [
            {
                "start_time": i["start_time"],
                "end_time": i["end_time"],
                "duration": human_duration(i["duration_s"]),
                "duration_s": i["duration_s"],
                "resolved": i["resolved"],
            }
            for i in repo.incidents(endpoint_id)
        ],
    }
