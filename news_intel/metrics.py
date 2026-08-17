"""Model-versus-human agreement, computed from the review queue.

This is the measurement the legacy system never had. Every number here compares what
the model produced against what a human approved for the same article, so "is it working"
stops being a feeling.

Two deliberate choices about which statistic to use:

- Category is nominal, so it gets per-class precision/recall/F1 and a confusion matrix.
  Plain accuracy hides the failure that matters: `other` is ~42% of volume, so a model
  that never predicts security/economics still scores well while being useless.
- The three score axes are ORDINAL (خیلی کم → خیلی زیاد). Predicting «زیاد» when the
  truth is «خیلی زیاد» is a near miss, not an equal-weight error, so they get exact
  match, within-one, and mean absolute error rather than accuracy alone.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .core.db import LEVELS, level_score
from .core.scoring import NOTIFY, decide

CATEGORIES = ["security", "economics", "security/economics", "other"]
AXES = ["confidence_occurrence", "gold_price_impact", "security_relevance"]


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
    # Human said "not assessed" but the model produced a value, or the reverse.
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
        denom = self.notify_tp + self.notify_fp
        return self.notify_tp / denom if denom else None

    @property
    def notify_recall(self) -> float | None:
        denom = self.notify_tp + self.notify_fn
        return self.notify_tp / denom if denom else None

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
        SELECT r.reviewed_category, r.confidence_occurrence AS h_conf,
               r.gold_price_impact AS h_gold, r.security_relevance AS h_sec,
               c.category AS m_category,
               e.confidence_occurrence AS m_conf, e.gold_price_impact AS m_gold,
               e.security_relevance AS m_sec
        FROM review_cases r
        LEFT JOIN latest_classification c ON c.article_id = r.article_id
        LEFT JOIN latest_evaluation e ON e.article_id = r.article_id
        WHERE r.status = 'approved' AND r.reviewed_category IS NOT NULL
        """
    ).fetchall()
    report.labelled = len(rows)

    report.confusion = {truth: {pred: 0 for pred in CATEGORIES} for truth in CATEGORIES}
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
        if truth == predicted:
            report.category_correct += 1
            if truth in per_class:
                per_class[truth].correct += 1
        if predicted is not None:
            report.category_compared += 1

        for axis, human_key, model_key in (
            ("confidence_occurrence", "h_conf", "m_conf"),
            ("gold_price_impact", "h_gold", "m_gold"),
            ("security_relevance", "h_sec", "m_sec"),
        ):
            human, model = level_score(row[human_key]), level_score(row[model_key])
            metric = axes[axis]
            if human is None and model is None:
                continue
            if human is None or model is None:
                # One side judged the axis unassessable and the other did not. Counted
                # separately: it is a different kind of error from being off by a level.
                metric.disagreed_on_presence += 1
                continue
            metric.compared += 1
            gap = abs(human - model)
            metric.abs_error += gap
            metric.exact += gap == 0
            metric.within_one += gap <= 1

        human_decision = decide(row["h_conf"], row["h_gold"], row["h_sec"]).status
        model_decision = decide(row["m_conf"], row["m_gold"], row["m_sec"]).status
        if model_decision == NOTIFY and human_decision == NOTIFY:
            report.notify_tp += 1
        elif model_decision == NOTIFY:
            report.notify_fp += 1
        elif human_decision == NOTIFY:
            report.notify_fn += 1

    report.per_class = [per_class[label] for label in CATEGORIES]
    report.axes = [axes[axis] for axis in AXES]
    return report


def level_options() -> list[str]:
    return list(LEVELS)
