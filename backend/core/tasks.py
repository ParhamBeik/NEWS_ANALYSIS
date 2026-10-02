"""Operator tasks. Task names are persisted routing contracts (django-celery-beat rows)."""

from __future__ import annotations

from celery import shared_task

from .ops_alerts import notify_staff


@shared_task(name="core.ops_alerts")
def ops_alerts() -> dict:
    """Tell staff about budget, circuit, priority-gap and freshness-SLO problems."""
    return notify_staff()
