"""Offline evaluation reports for human-reviewed cases.

The golden set is not written by hand. It is exported from the approved rows of the
review queue, so the truth a provider is measured against is the same truth a person
actually recorded in the dashboard - there is no second, drifting copy of "correct".
That also makes the set grow as review happens, which is the point of the review page.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import db
from .core.scoring import decide
from .providers import Provider
from .sources import RawArticle


@dataclass(frozen=True)
class EvaluationCase:
    article: RawArticle
    category: str
    scores: dict[str, str | None]


def load_cases(path: Path) -> list[EvaluationCase]:
    items = json.loads(path.read_text(encoding="utf-8"))
    return [
        EvaluationCase(
            article=RawArticle(**item["article"]),
            category=item["category"],
            scores=item.get("scores", {}),
        )
        for item in items
    ]


def build_golden(conn: sqlite3.Connection, path: Path) -> int:
    """Export every approved review as an evaluation case. Returns the case count.

    Only `status='approved'` rows are eligible: skipped and pending cases carry no human
    judgement, and a golden set seeded with the model's own answers would measure the
    model against itself and report perfect agreement.

    Axes the reviewer left as "ارزیابی نشد" are omitted from `scores` rather than written
    as a level. `evaluate()` skips absent axes, so an unjudged axis contributes nothing
    instead of contributing a fabricated one.
    """
    rows = conn.execute(
        """
        SELECT a.url, a.source, a.original_title, a.lead, a.content,
               a.original_outlet, a.published_at_gregorian,
               r.reviewed_category, r.confidence_occurrence,
               r.gold_price_impact, r.security_relevance
        FROM review_cases r JOIN articles a ON a.id = r.article_id
        WHERE r.status = 'approved' AND r.reviewed_category IS NOT NULL
        ORDER BY r.id
        """
    ).fetchall()
    cases = [
        {
            "article": {
                "source": row["source"],
                "url": row["url"],
                "title": row["original_title"],
                "lead": row["lead"] or "",
                "content": row["content"] or "",
                "original_outlet": row["original_outlet"] or "",
                "published_at": row["published_at_gregorian"],
            },
            "category": row["reviewed_category"],
            "scores": {
                axis: row[axis]
                for axis in ("confidence_occurrence", "gold_price_impact", "security_relevance")
                if row[axis]
            },
        }
        for row in rows
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(cases)


def weighted_kappa(expected: list[int], actual: list[int]) -> float | None:
    """Quadratic weighted kappa without a dependency; None when no comparable labels exist."""
    if len(expected) < 2:
        return None
    size = 5
    observed = [[0] * size for _ in range(size)]
    for left, right in zip(expected, actual):
        observed[left - 1][right - 1] += 1
    left_totals = [sum(row) for row in observed]
    right_totals = [sum(observed[row][col] for row in range(size)) for col in range(size)]
    weight = lambda i, j: ((i - j) / (size - 1)) ** 2
    total = len(expected)
    numerator = sum(weight(i, j) * observed[i][j] for i in range(size) for j in range(size)) / total
    denominator = sum(weight(i, j) * left_totals[i] * right_totals[j] for i in range(size) for j in range(size)) / (total * total)
    return 1.0 - numerator / denominator if denominator else 1.0


@dataclass(frozen=True)
class Variant:
    """One (provider, model, prompt_version) combination already run via `cli run`.

    `model=None` matches any model recorded for that provider - useful when a provider
    was pinned without an explicit model and the default was used.
    """

    provider: str
    model: str | None
    prompt_version: str


def _variant_rows(conn: sqlite3.Connection, variant: Variant) -> dict[int, dict[str, Any]]:
    model_clause = "AND c.model = ?" if variant.model else ""
    params: list[Any] = [variant.provider, variant.prompt_version]
    if variant.model:
        params.append(variant.model)
    rows = conn.execute(
        f"""
        SELECT a.id AS article_id, a.original_title AS title, a.url AS url,
               c.category, c.confidence, c.rationale AS classify_rationale,
               e.confidence_occurrence, e.gold_price_impact, e.security_relevance,
               e.gold_trend, e.rationale AS eval_rationale
        FROM articles a
        JOIN classifications c ON c.article_id = a.id
            AND c.provider = ? AND c.prompt_version = ? {model_clause}
        LEFT JOIN evaluations e ON e.article_id = a.id
            AND e.provider = c.provider AND e.model = c.model AND e.prompt_version = c.prompt_version
        WHERE a.duplicate_of IS NULL
        """,
        params,
    ).fetchall()
    return {row["article_id"]: dict(row) for row in rows}


def _verdict(row: dict[str, Any]) -> tuple[str, str]:
    decision = decide(row["confidence_occurrence"], row["gold_price_impact"], row["security_relevance"])
    return row["category"], decision.status


def _block(label: str, row: dict[str, Any]) -> str:
    return (
        f"[{label}] category={row['category']} confidence={row['confidence']}\n"
        f"  occurrence={row['confidence_occurrence']} gold_impact={row['gold_price_impact']}"
        f" security={row['security_relevance']} trend={row['gold_trend']}\n"
        f"  rationale: {row['eval_rationale'] or row['classify_rationale'] or ''}"
    )


def compare(conn: sqlite3.Connection, *, a: Variant, b: Variant, out_dir: Path) -> dict[str, Any]:
    """Diff two already-run prompt/provider variants over their shared articles.

    Reads from rows already stored by `cli run` - inference is append-only, so running
    the same articles under two prompt versions (or two providers) just means two prior
    `run` invocations, and this reads both instead of paying for a third call. Mirrors
    legacy's pipeline_comparison_{same,different,all}.txt so a human can judge which
    variant is better before either one becomes the default in config/routing.yaml.
    """
    a_rows, b_rows = _variant_rows(conn, a), _variant_rows(conn, b)
    if not a_rows:
        raise ValueError(f"no rows for variant A ({a.provider}/{a.prompt_version}); run it first")
    if not b_rows:
        raise ValueError(f"no rows for variant B ({b.provider}/{b.prompt_version}); run it first")
    shared = sorted(set(a_rows) & set(b_rows))

    same_lines, diff_lines, all_lines = [], [], []
    same_count = 0
    for article_id in shared:
        left, right = a_rows[article_id], b_rows[article_id]
        header = f"{left['title']}\n{left['url']}"
        agree = _verdict(left) == _verdict(right)
        block = f"{header}\n{_block('A', left)}\n{_block('B', right)}\n" + "-" * 50
        all_lines.append(("same" if agree else "different") + " | " + block)
        if agree:
            same_count += 1
            same_lines.append(block)
        else:
            diff_lines.append(block)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "comparison_same.txt").write_text("\n\n".join(same_lines), encoding="utf-8")
    (out_dir / "comparison_different.txt").write_text("\n\n".join(diff_lines), encoding="utf-8")
    (out_dir / "comparison_all.txt").write_text("\n\n".join(all_lines), encoding="utf-8")
    return {
        "shared_articles": len(shared),
        "same": same_count,
        "different": len(shared) - same_count,
        "out_dir": str(out_dir),
    }


def evaluate(cases: list[EvaluationCase], provider: Provider) -> dict[str, Any]:
    categories = [provider.classify(case.article).data.category for case in cases]
    report: dict[str, Any] = {"cases": len(cases), "category_accuracy": sum(actual == case.category for actual, case in zip(categories, cases)) / len(cases) if cases else None, "kappa": {}}
    for axis in ("confidence_occurrence", "gold_price_impact", "security_relevance"):
        expected, actual = [], []
        for case in cases:
            wanted = case.scores.get(axis)
            if wanted not in db.LEVELS:
                continue
            got = getattr(provider.evaluate(case.article, case.category).data, axis)
            if got in db.LEVELS:
                expected.append(db.level_score(wanted))
                actual.append(db.level_score(got))
        report["kappa"][axis] = weighted_kappa(expected, actual)
    return report
