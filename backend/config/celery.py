"""Celery application.

Two queues, not one: `crawl` is I/O-bound and chatty, `inference` is expensive and
budget-guarded. Sharing a pool means a slow source can starve inference of workers, and a
budget abort that purges inference work would take in-flight crawling down with it.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("newsintel")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Routed by task name prefix so adding a task to an app puts it on the right queue without
# a second registration step that can be forgotten.
app.conf.task_routes = {
    "sources.*": {"queue": "crawl"},
    "articles.tasks.download_image": {"queue": "crawl"},
    "market.*": {"queue": "crawl"},
    "inference.*": {"queue": "inference"},
    "articles.tasks.embed_article": {"queue": "inference"},
}
