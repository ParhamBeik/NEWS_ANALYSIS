"""Workbook generation as a scheduled task."""

from __future__ import annotations

import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings

from . import workbook

logger = logging.getLogger(__name__)


@shared_task(name="exports.build_daily_workbook")
def build_daily_workbook(window_days: int | None = None, rebuild_all: bool = False) -> dict:
    """Rebuild the workbooks that could have changed, and the text feeds.

    Rebuilds rather than appends. Inference is append-only, so a re-run with a better prompt
    changes what a day's workbook should say, and a file that only ever grew would keep
    showing the first answer the pipeline ever gave.

    BOUNDED, though. This used to rebuild one workbook per Jalali day in the entire corpus,
    every night: a template copy, an openpyxl parse, a save and a zip rewrite each. That is
    work that grows without limit for the life of the deployment - six months in it is ~180
    files a night, almost all of them rewritten byte-for-byte - inside a worker with a
    640 MB ceiling. A day can only change if one of its events changed inside the rolling
    window, so that is the set rebuilt here. Files stay downloadable until they fall out of
    the newest EXPORT_KEEP_DAYS (storage policy); they are simply not rewritten to say what
    they already said.

    `rebuild_all=True` is the escape for a fresh deployment: every day in the kept span.
    """
    window = None if rebuild_all else (
        window_days if window_days is not None else settings.NEWS_ROLLING_WINDOW_DAYS
    )
    files = workbook.export_all(Path(settings.EXPORT_DIR), window_days=window)
    workbooks = sorted(key for key in files if key.startswith("excel:"))
    logger.info("exported %s workbooks to %s", len(workbooks), settings.EXPORT_DIR)
    return {
        "workbooks": len(workbooks),
        "days": [key.split(":", 1)[1] for key in workbooks],
        "rebuilt_all": rebuild_all,
        "directory": str(settings.EXPORT_DIR),
    }
