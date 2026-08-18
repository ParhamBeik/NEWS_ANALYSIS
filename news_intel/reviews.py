"""Human-review queue and approved-example retrieval."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict, deque
from pathlib import Path

from openpyxl import Workbook, load_workbook

from .core import dag, normalize
from .prompts import ReviewedExample
from .sources import RawArticle


def _candidates(conn: sqlite3.Connection) -> dict[str, deque[sqlite3.Row]]:
    rows = conn.execute("""
        SELECT a.id, a.url, a.original_title, a.lead, a.content, a.source, a.original_outlet,
               c.category, counts.category_count,
               e.confidence_occurrence, e.gold_price_impact, e.security_relevance
        FROM articles a
        JOIN classifications c ON c.article_id=a.id
        JOIN (
            SELECT article_id, COUNT(DISTINCT category) AS category_count
            FROM classifications GROUP BY article_id
        ) counts ON counts.article_id=a.id
        LEFT JOIN latest_evaluation e ON e.article_id=a.id
        WHERE a.duplicate_of IS NULL
        ORDER BY a.id
    """).fetchall()
    groups: dict[str, deque[sqlite3.Row]] = defaultdict(deque)
    seen: set[int] = set()
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        if row["category_count"] > 1:
            groups["prompt_disagreement"].append(row)
        elif row["category"] == "other":
            groups["other"].append(row)
        elif row["confidence_occurrence"] is None:
            groups["unevaluated"].append(row)
        else:
            groups[row["category"]].append(row)
    return groups


def create_queue(conn: sqlite3.Connection, *, size: int = 100) -> int:
    """Create a deterministic, stratified queue without overwriting completed review."""
    groups = _candidates(conn)
    labels = sorted(groups)
    chosen: list[tuple[sqlite3.Row, str]] = []
    while len(chosen) < size and labels:
        for label in list(labels):
            if groups[label]:
                chosen.append((groups[label].popleft(), label))
                if len(chosen) == size:
                    break
            if not groups[label]:
                labels.remove(label)
    for row, stratum in chosen:
        conn.execute(
            "INSERT OR IGNORE INTO review_cases(article_id,stratum,created_at) VALUES(?,?,?)",
            (row["id"], stratum, dag.utc_now()),
        )
    return len(chosen)


def export_queue(conn: sqlite3.Connection, path: Path) -> Path:
    rows = conn.execute("""
        SELECT r.id AS review_id, r.stratum, r.status, a.url, a.original_title AS title, a.lead, a.content,
               a.source, a.original_outlet AS outlet, r.reviewed_category, r.confidence_occurrence,
               r.gold_price_impact, r.security_relevance, r.gold_trend, r.one_line, r.reviewer_notes
        FROM review_cases r JOIN articles a ON a.id=r.article_id
        ORDER BY r.stratum, r.id
    """).fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps([{key: row[key] for key in row.keys()} for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Review Queue"
    headers = [
        "review_id", "stratum", "status", "url", "title", "lead", "content", "source",
        "outlet", "reviewed_category", "confidence_occurrence", "gold_price_impact",
        "security_relevance", "gold_trend", "one_line", "reviewer_notes",
    ]
    sheet.append(headers)
    for row in rows:
        sheet.append([row[key] for key in headers])
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["E"].width = 50
    sheet.column_dimensions["G"].width = 80
    sheet.column_dimensions["P"].width = 50
    workbook.save(path)
    return path


def import_queue(conn: sqlite3.Connection, path: Path) -> int:
    """Apply only rows explicitly marked approved; blank or pending rows remain untouched."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    updated = 0
    for values in sheet.iter_rows(min_row=2, values_only=True):
        row = dict(zip(headers, values))
        if str(row.get("status", "")).strip().lower() != "approved":
            continue
        cur = conn.execute(
            "UPDATE review_cases SET status='approved', reviewed_category=?, confidence_occurrence=?,"
            " gold_price_impact=?, security_relevance=?, gold_trend=?, one_line=?, reviewer_notes=?,"
            " reviewed_at=? WHERE id=? AND status='pending'",
            (
                row.get("reviewed_category"), row.get("confidence_occurrence"), row.get("gold_price_impact"),
                row.get("security_relevance"), row.get("gold_trend"), row.get("one_line"),
                row.get("reviewer_notes"), dag.utc_now(), row.get("review_id"),
            ),
        )
        updated += cur.rowcount
    return updated


def reviewed_examples(conn: sqlite3.Connection, article: RawArticle, *, task: str, category: str | None = None, limit: int = 3) -> list[ReviewedExample]:
    rows = conn.execute("""
        SELECT a.original_title, r.reviewed_category, r.confidence_occurrence, r.gold_price_impact,
               r.security_relevance, r.gold_trend, r.one_line
        FROM review_cases r JOIN articles a ON a.id=r.article_id
        WHERE r.status='approved' AND r.reviewed_category IS NOT NULL
    """).fetchall()
    candidates = []
    article_terms = normalize.trigrams(article.title)
    for row in rows:
        if category and row["reviewed_category"] not in {category, "security/economics"}:
            continue
        if task == "classify":
            output = {"category": row["reviewed_category"]}
        elif task == "evaluate":
            output = {
                "confidence_occurrence": row["confidence_occurrence"],
                "gold_price_impact": row["gold_price_impact"],
                "security_relevance": row["security_relevance"],
                "gold_trend": row["gold_trend"],
            }
        else:
            output = {"one_line": row["one_line"]}
        candidates.append((normalize.jaccard(article_terms, normalize.trigrams(row["original_title"])), ReviewedExample(row["reviewed_category"], row["original_title"], json.dumps(output, ensure_ascii=False))))
    return [item for _, item in sorted(candidates, key=lambda pair: pair[0], reverse=True)[:limit]]
