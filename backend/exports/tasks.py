"""Workbook generation as a scheduled task."""

from __future__ import annotations

import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings

from . import workbook

logger = logging.getLogger(__name__)


@shared_task(name="exports.build_daily_workbook")
def build_daily_workbook() -> dict:
    """Rebuild every daily workbook and the text feeds.

    Rebuilds rather than appends. Inference is append-only, so a re-run with a better
    prompt changes what a day's workbook should say, and a file that only ever grew would
    keep showing the first answer the pipeline ever gave.
    """
    files = workbook.export_all(Path(settings.EXPORT_DIR))
    workbooks = sorted(key for key in files if key.startswith("excel:"))
    logger.info("exported %s workbooks to %s", len(workbooks), settings.EXPORT_DIR)
    return {
        "workbooks": len(workbooks),
        "days": [key.split(":", 1)[1] for key in workbooks],
        "directory": str(settings.EXPORT_DIR),
    }
