"""Dashboard: human review, model KPIs, and system monitoring.

The primary job is the review page, not monitoring. Labelling is the bottleneck on
knowing whether the model works, so the interface optimises for one thing: how fast a
person can confirm or correct one article.

Two design decisions worth stating:

- The model's answer is PRE-SELECTED on the form. A reviewer corrects rather than fills,
  which is several times faster and is why the queue can realistically be finished.
  The model's own answer is also shown as text under each field, so agreeing is never
  accidental - you can see what you are agreeing with.
- "ارزیابی نشد" (not assessed) is a real option on every score axis, not an empty
  default. An axis nobody judged must stay NULL; substituting a value there is the exact
  bug that silently suppressed every security alert in the legacy pipeline.

Monitoring reads through a read-only connection. Review submission is the one write
path, and it opens its own connection deliberately rather than widening the other.
"""

# NOTE: deliberately no `from __future__ import annotations` here. FastAPI resolves route
# annotations through typing.get_type_hints against module globals, and the fastapi
# imports below are function-local (so the CLI does not hard-depend on the web stack).
# With postponed evaluation, `Request` becomes an unresolvable string and every HTML
# route answers 422.
import sqlite3
from html import escape
from pathlib import Path

from . import metrics, prompts
from .core import config, dag, db

CATEGORY_LABELS = [
    ("security", "امنیتی"),
    ("economics", "اقتصادی"),
    ("security/economics", "امنیتی/اقتصادی"),
    ("other", "سایر"),
]
AXIS_LABELS = {
    "confidence_occurrence": "اطمینان از وقوع خبر",
    "gold_price_impact": "اثر بر قیمت طلا",
    "security_relevance": "ارتباط با امنیت",
}
AXIS_HINTS = {
    "confidence_occurrence": "چقدر مطمئنیم این رویداد واقعاً رخ داده است؟",
    "gold_price_impact": "اگر خبر به طلا مربوط نیست، «ارزیابی نشد» را انتخاب کنید.",
    "security_relevance": "اگر خبر بار امنیتی ندارد، «ارزیابی نشد» را انتخاب کنید.",
}
TRENDS = list(prompts.GOLD_TRENDS)


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}٪"


def _short_url(url: str, limit: int = 72) -> str:
    """Readable link text. Percent-encoded Persian slugs run past 200 characters."""
    from urllib.parse import unquote

    text = unquote(url or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sequential(count: int, largest: int) -> str:
    """Single-hue light->dark ramp for the confusion matrix.

    Sequential encoding of a magnitude, so one hue with the lightest step meaning
    "near zero" - never a rainbow, never a hue at a midpoint.
    """
    if not count:
        return "transparent"
    steps = ["var(--seq-100)", "var(--seq-250)", "var(--seq-400)", "var(--seq-550)"]
    index = min(int(count / max(largest, 1) * len(steps)), len(steps) - 1)
    return steps[index]


def create_app(path: Path | None = None):
    from fastapi import FastAPI, Form, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates

    app = FastAPI(title="News Intel", docs_url=None)
    database = path or config.DB_PATH
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    templates.env.filters["short_url"] = _short_url

    def read() -> sqlite3.Connection:
        return db.connect(database, readonly=True)

    def write() -> sqlite3.Connection:
        return db.connect(database)

    # ---------------------------------------------------------------- review

    def next_case(conn: sqlite3.Connection, review_id: int | None = None):
        where = "r.id = ?" if review_id else "r.status = 'pending'"
        args = (review_id,) if review_id else ()
        return conn.execute(
            f"""
            SELECT r.id AS review_id, r.stratum, a.url, a.original_title AS title,
                   a.lead, a.content, a.source, a.original_outlet AS outlet,
                   a.published_at_persian AS published,
                   c.category AS model_category, c.rationale AS model_rationale,
                   e.confidence_occurrence, e.gold_price_impact, e.security_relevance,
                   e.gold_trend, s.one_line
            FROM review_cases r
            JOIN articles a ON a.id = r.article_id
            LEFT JOIN latest_classification c ON c.article_id = r.article_id
            LEFT JOIN latest_evaluation e ON e.article_id = r.article_id
            LEFT JOIN latest_summary s ON s.article_id = r.article_id
            WHERE {where}
            ORDER BY r.id LIMIT 1
            """,
            args,
        ).fetchone()

    @app.get("/review", response_class=HTMLResponse)
    def review(request: Request):
        with read() as conn:
            case = next_case(conn)
            done = conn.execute(
                "SELECT COUNT(*) c FROM review_cases WHERE status='approved'"
            ).fetchone()["c"]
            total = conn.execute("SELECT COUNT(*) c FROM review_cases").fetchone()["c"]

        context = {
            "page": "review",
            "case": case,
            "done": done,
            "total": total,
            "percent": round(done / total * 100) if total else 0,
            "categories": CATEGORY_LABELS,
            "levels": metrics.level_options(),
            "trends": TRENDS,
            "axes": [
                {
                    "name": axis,
                    "label": AXIS_LABELS[axis],
                    "hint": AXIS_HINTS[axis],
                    "value": case[axis] if case else None,
                }
                for axis in metrics.AXES
            ]
            if case
            else [],
        }
        return templates.TemplateResponse(request, "review.html", context)

    @app.post("/review/{review_id}")
    def submit(
        review_id: int,
        action: str = Form("approve"),
        reviewed_category: str = Form(""),
        confidence_occurrence: str = Form(""),
        gold_price_impact: str = Form(""),
        security_relevance: str = Form(""),
        gold_trend: str = Form(""),
        one_line: str = Form(""),
        reviewer_notes: str = Form(""),
    ):
        conn = write()
        try:
            if action == "skip":
                conn.execute(
                    "UPDATE review_cases SET status='skipped', reviewed_at=? WHERE id=?",
                    (dag.utc_now(), review_id),
                )
            else:
                if not reviewed_category:
                    raise HTTPException(400, "reviewed_category is required")
                # Empty string means "not assessed" and must land as NULL, never as a
                # substituted level.
                conn.execute(
                    "UPDATE review_cases SET status='approved', reviewed_category=?,"
                    " confidence_occurrence=?, gold_price_impact=?, security_relevance=?,"
                    " gold_trend=?, one_line=?, reviewer_notes=?, reviewed_at=?"
                    " WHERE id=?",
                    (
                        reviewed_category,
                        confidence_occurrence or None,
                        gold_price_impact or None,
                        security_relevance or None,
                        gold_trend or None,
                        one_line.strip() or None,
                        reviewer_notes.strip() or None,
                        dag.utc_now(),
                        review_id,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/review", status_code=303)

    # ------------------------------------------------------------------- kpi

    @app.get("/kpi", response_class=HTMLResponse)
    def kpi(request: Request):
        with read() as conn:
            report = metrics.compute(conn)
        largest = max(
            (n for row in report.confusion.values() for n in row.values()), default=0
        )
        return templates.TemplateResponse(
            request,
            "kpi.html",
            {
                "page": "kpi",
                "report": report,
                "categories": metrics.CATEGORIES,
                "axis_labels": AXIS_LABELS,
                "pct": _percent,
                "ramp": lambda n: _sequential(n, largest),
            },
        )

    # -------------------------------------------------------------- overview

    def runs_html() -> str:
        with read() as conn:
            rows = conn.execute(
                "SELECT run_id,status,started_at,articles_fetched,articles_processed,cost_usd"
                " FROM runs ORDER BY started_at DESC LIMIT 10"
            ).fetchall()
        if not rows:
            return "<p class='empty' style='padding:20px'>اجرایی ثبت نشده است.</p>"
        body = "".join(
            f"<tr><td>{escape(r['run_id'])}</td><td>{escape(r['status'])}</td>"
            f"<td class='num'>{r['articles_fetched']}</td>"
            f"<td class='num'>{r['articles_processed']}</td>"
            f"<td class='num'>${r['cost_usd']:.4f}</td></tr>"
            for r in rows
        )
        return (
            "<table><thead><tr><th>شناسه اجرا</th><th>وضعیت</th><th class='num'>دریافت</th>"
            "<th class='num'>پردازش</th><th class='num'>هزینه</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request):
        with read() as conn:
            sources = conn.execute(
                "SELECT name, health_status, last_success_at, last_error, priority"
                " FROM sources ORDER BY priority, name"
            ).fetchall()
            totals = {
                "articles": conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"],
                "canonical": conn.execute(
                    "SELECT COUNT(*) c FROM articles WHERE duplicate_of IS NULL"
                ).fetchone()["c"],
                "classifications": conn.execute(
                    "SELECT COUNT(*) c FROM classifications"
                ).fetchone()["c"],
                "dead": conn.execute(
                    "SELECT COUNT(*) c FROM dead_letters WHERE resolved_at IS NULL"
                ).fetchone()["c"],
            }
            dead_reasons = conn.execute(
                "SELECT node, error_class, COUNT(*) n FROM dead_letters"
                " WHERE resolved_at IS NULL GROUP BY node, error_class ORDER BY n DESC"
            ).fetchall()
        return templates.TemplateResponse(
            request,
            "overview.html",
            {
                "page": "overview",
                "sources": sources,
                "totals": totals,
                "dead_reasons": dead_reasons,
                "runs_html": runs_html(),
            },
        )

    @app.get("/partials/runs", response_class=HTMLResponse)
    def partial_runs():
        return runs_html()

    # -------------------------------------------------------------- json api

    @app.get("/api/kpi")
    def api_kpi():
        with read() as conn:
            report = metrics.compute(conn)
        return {
            "labelled": report.labelled,
            "pending": report.pending,
            "category_accuracy": report.category_accuracy,
            "macro_f1": report.macro_f1,
            "notify_precision": report.notify_precision,
            "notify_recall": report.notify_recall,
            "confusion": report.confusion,
            "axes": [
                {
                    "axis": a.axis, "compared": a.compared, "exact_rate": a.exact_rate,
                    "within_one_rate": a.within_one_rate, "mae": a.mae,
                    "disagreed_on_presence": a.disagreed_on_presence,
                }
                for a in report.axes
            ],
        }

    @app.get("/api/health")
    def api_health():
        with read() as conn:
            return {
                "sources": [
                    dict(row)
                    for row in conn.execute(
                        "SELECT name,health_status,last_success_at,last_error FROM sources"
                    )
                ]
            }

    return app
