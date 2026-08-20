"""Two kinds of number, both read-only aggregations over what is already stored.

`compute()` is model-versus-human agreement, drawn from approved review rows - the
measurement the legacy system never had. Category is nominal, so it gets per-class
precision/recall/F1 and a confusion matrix; plain accuracy would hide the failure that
matters, since `other` is ~42% of volume. The three score axes are ORDINAL, so predicting
«زیاد» when the truth is «خیلی زیاد» is a near miss, not an equal-weight error - hence
exact match, within-one and mean absolute error rather than accuracy alone.

The rest is operational telemetry over `node_events`/`articles`: tokens, cost, node
outcomes, fetch volume, funnel, coverage.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from . import db, pipeline, sources
from .prompts import CATEGORIES
from .scoring import AXES, NOTIFY, decide, level_score


# ---------------------------------------------------------------- model vs human labels


@dataclass
class ClassMetric:
    label: str
    support: int = 0
    predicted: int = 0
    correct: int = 0

    @property
    def precision(self) -> float | None:
        return self.correct / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.correct / self.support if self.support else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p and r else None


@dataclass
class AxisMetric:
    axis: str
    compared: int = 0
    exact: int = 0
    within_one: int = 0
    abs_error: float = 0.0
    # Human said "not assessed" but the model produced a value, or the reverse. A
    # different kind of error from being off by a level, so counted separately.
    disagreed_on_presence: int = 0

    @property
    def exact_rate(self) -> float | None:
        return self.exact / self.compared if self.compared else None

    @property
    def within_one_rate(self) -> float | None:
        return self.within_one / self.compared if self.compared else None

    @property
    def mae(self) -> float | None:
        return self.abs_error / self.compared if self.compared else None


@dataclass
class Report:
    labelled: int = 0
    pending: int = 0
    category_correct: int = 0
    category_compared: int = 0
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    per_class: list[ClassMetric] = field(default_factory=list)
    axes: list[AxisMetric] = field(default_factory=list)
    notify_tp: int = 0
    notify_fp: int = 0
    notify_fn: int = 0

    @property
    def category_accuracy(self) -> float | None:
        return self.category_correct / self.category_compared if self.category_compared else None

    @property
    def macro_f1(self) -> float | None:
        scores = [m.f1 for m in self.per_class if m.f1 is not None]
        return sum(scores) / len(scores) if scores else None

    @property
    def notify_precision(self) -> float | None:
        denominator = self.notify_tp + self.notify_fp
        return self.notify_tp / denominator if denominator else None

    @property
    def notify_recall(self) -> float | None:
        denominator = self.notify_tp + self.notify_fn
        return self.notify_tp / denominator if denominator else None

    @property
    def progress(self) -> float:
        total = self.labelled + self.pending
        return self.labelled / total if total else 0.0


def compute(conn: sqlite3.Connection) -> Report:
    report = Report()
    report.pending = conn.execute(
        "SELECT COUNT(*) c FROM review_cases WHERE status != 'approved'"
    ).fetchone()["c"]
    rows = conn.execute(
        """
        SELECT r.reviewed_category, r.confidence_occurrence AS h_confidence_occurrence,
               r.gold_price_impact AS h_gold_price_impact,
               r.security_relevance AS h_security_relevance,
               c.category AS m_category,
               e.confidence_occurrence AS m_confidence_occurrence,
               e.gold_price_impact AS m_gold_price_impact,
               e.security_relevance AS m_security_relevance
        FROM review_cases r
        LEFT JOIN latest_classification c ON c.article_id = r.article_id
        LEFT JOIN latest_evaluation e ON e.article_id = r.article_id
        WHERE r.status = 'approved' AND r.reviewed_category IS NOT NULL
        """
    ).fetchall()
    report.labelled = len(rows)
    report.confusion = {truth: dict.fromkeys(CATEGORIES, 0) for truth in CATEGORIES}
    per_class = {label: ClassMetric(label) for label in CATEGORIES}
    axes = {axis: AxisMetric(axis) for axis in AXES}

    for row in rows:
        truth, predicted = row["reviewed_category"], row["m_category"]
        if truth in report.confusion and predicted in report.confusion[truth]:
            report.confusion[truth][predicted] += 1
        if truth in per_class:
            per_class[truth].support += 1
        if predicted in per_class:
            per_class[predicted].predicted += 1
        if predicted is not None:
            report.category_compared += 1
        if truth == predicted:
            report.category_correct += 1
            if truth in per_class:
                per_class[truth].correct += 1

        for axis in AXES:
            human, model = level_score(row[f"h_{axis}"]), level_score(row[f"m_{axis}"])
            metric = axes[axis]
            if human is None and model is None:
                continue
            if human is None or model is None:
                metric.disagreed_on_presence += 1
                continue
            metric.compared += 1
            gap = abs(human - model)
            metric.abs_error += gap
            metric.exact += gap == 0
            metric.within_one += gap <= 1

        human_notify = decide(*(row[f"h_{axis}"] for axis in AXES)).status == NOTIFY
        model_notify = decide(*(row[f"m_{axis}"] for axis in AXES)).status == NOTIFY
        report.notify_tp += human_notify and model_notify
        report.notify_fp += model_notify and not human_notify
        report.notify_fn += human_notify and not model_notify

    report.per_class = [per_class[label] for label in CATEGORIES]
    report.axes = [axes[axis] for axis in AXES]
    return report


# ------------------------------------------------------------------------- operational


def _rows(conn: sqlite3.Connection, query: str, days: int) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, (db.day_floor(days),))]


def token_cost_by_day(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    return _rows(conn,
        "SELECT date(created_at) AS day, SUM(tokens_in) AS tokens_in,"
        " SUM(tokens_out) AS tokens_out, SUM(cost_usd) AS cost_usd"
        " FROM node_events WHERE created_at >= date('now', ?) GROUP BY day ORDER BY day", days)


def node_status_counts(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    return _rows(conn,
        "SELECT node, status, COUNT(*) AS n FROM node_events"
        " WHERE created_at >= date('now', ?) GROUP BY node, status ORDER BY node, status", days)


def provider_breakdown(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    return _rows(conn,
        "SELECT provider, model, COUNT(*) AS calls, SUM(tokens_in) AS tokens_in,"
        " SUM(tokens_out) AS tokens_out, SUM(cost_usd) AS cost_usd FROM node_events"
        " WHERE created_at >= date('now', ?) AND provider IS NOT NULL"
        " GROUP BY provider, model ORDER BY cost_usd DESC", days)


def fetch_volume_by_source(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    return _rows(conn,
        "SELECT source, date(fetched_at) AS day, COUNT(*) AS n FROM articles"
        " WHERE fetched_at >= date('now', ?) GROUP BY source, day ORDER BY day, source", days)


def funnel(conn: sqlite3.Connection, days: int) -> dict[str, int]:
    """fetched -> unique -> classified -> evaluated, over the rolling window."""
    recent = "a.fetched_at >= date('now', ?)"
    stages = {
        "fetched": f"SELECT COUNT(*) c FROM articles a WHERE {recent}",
        "unique": f"SELECT COUNT(*) c FROM articles a WHERE {recent} AND a.duplicate_of IS NULL",
        "classified": "SELECT COUNT(DISTINCT a.id) c FROM articles a"
                      f" JOIN classifications x ON x.article_id = a.id"
                      f" WHERE {recent} AND a.duplicate_of IS NULL",
        "evaluated": "SELECT COUNT(DISTINCT a.id) c FROM articles a"
                     f" JOIN evaluations x ON x.article_id = a.id"
                     f" WHERE {recent} AND a.duplicate_of IS NULL",
    }
    floor = db.day_floor(days)
    return {name: conn.execute(query, (floor,)).fetchone()["c"] for name, query in stages.items()}


def source_coverage(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    """Per-source window completeness, honest about which sources cannot backfill."""
    return [
        {
            "source": row["name"],
            "missing_days": len(pipeline.missing_days(conn, row["name"], days)),
            "total_days": days,
            "backfill_supported": row["name"] in sources.BACKFILLABLE,
        }
        for row in conn.execute("SELECT name FROM sources WHERE enabled=1")
    ]
