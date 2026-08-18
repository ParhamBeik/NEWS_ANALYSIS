"""Shared date parsing/formatting used across ingest and reporting."""

from __future__ import annotations

from datetime import datetime

import jdatetime


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, tolerating a trailing 'Z'. None on empty/invalid input."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def jalali_str(value: jdatetime.date) -> str:
    return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
