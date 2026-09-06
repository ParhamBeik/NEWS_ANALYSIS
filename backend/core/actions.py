"""Structured action log. One line per decision the pipeline actually made.

/ops already aggregates NodeEvents and crawl return dicts. This exists for the gaps
between those: a circuit opening, a URL marked gone, a cycle that dispatched nothing
because the wallet is empty. Grep `action=` in the worker log to reconstruct a cycle.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("pipeline.actions")


def log_action(action: str, status: str, **fields) -> None:
    extras = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    logger.info("action=%s status=%s %s", action, status, extras)
