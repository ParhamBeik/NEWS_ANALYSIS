"""Dashboard: notify feed, A/B diff, pipeline ops, human review, and model KPIs.

Design decisions worth stating:

- The home page is the notify feed, not system health - the question a human actually
  opens this for is "what needs my attention", not "is the pipeline alive". Pipeline
  health lives on /ops instead.
- The review page's model answer is PRE-SELECTED on the form. A reviewer corrects rather
  than fills, which is several times faster and is why the queue can realistically be
  finished. The model's own answer is also shown as text under each field, so agreeing is
  never accidental - you can see what you are agreeing with.
- "Not assessed" is a real option on every score axis, not an empty default. An axis
  nobody judged must stay NULL; substituting a value there is the exact bug that
  silently suppressed every security alert in the legacy pipeline.
- UI chrome is English throughout. Article title/lead/content stay Persian and render
  RTL inline (scoped `dir="rtl"` wrappers), since that's the actual content. Ordinal
  levels and gold-trend symbols keep their Persian values under the hood - the team's
  Excel workbook dropdown requires those exact strings - only their on-screen labels
  are translated.
- /compare is GET-only and never writes: two dropdowns select variants, the page renders
  the diff. Nothing here has a POST form.

Monitoring reads through a read-only connection. Review submission and the window-days
setting are the only write paths, and each opens its own connection deliberately rather
than widening the shared read connection.
"""

# NOTE: deliberately no `from __future__ import annotations` here. FastAPI resolves route
# annotations through typing.get_type_hints against module globals, and the fastapi
# imports below are function-local (so the CLI does not hard-depend on the web stack).
# With postponed evaluation, `Request` becomes an unresolvable string and every HTML
# route answers 422.
import sqlite3
from html import escape
from pathlib import Path

from . import evals, metrics, prompts, telemetry
from .core import config, dag, db, scoring

CATEGORY_LABELS = [
    ("security", "Security"),
    ("economics", "Economics"),
    ("security/economics", "Security/Economics"),
    ("other", "Other"),
]
AXIS_LABELS = {
    "confidence_occurrence": "Event confidence",
    "gold_price_impact": "Gold price impact",
    "security_relevance": "Security relevance",
}
AXIS_HINTS = {
    "confidence_occurrence": "How confident are we that this event actually happened?",
    "gold_price_impact": "If the article isn't gold-related, choose \"Not assessed\".",
    "security_relevance": "If the article has no security angle, choose \"Not assessed\".",
}
# Ordinal levels and trend symbols are the workbook's own Persian vocabulary and stay
# that way as the stored/posted value; only the on-screen label is translated.
LEVEL_LABELS = {
    "خیلی کم": "Very low (خیلی کم)",
    "کم": "Low (کم)",
    "متوسط": "Medium (متوسط)",
    "زیاد": "High (زیاد)",
    "خیلی زیاد": "Very high (خیلی زیاد)",
}
TREND_LABELS = {
    "↑": "↑ Up",
    "↓": "↓ Down",
    "خنثی": "Neutral (خنثی)",
    "نامطمئن": "Uncertain (نامطمئن)",
}
TRENDS = list(prompts.GOLD_TRENDS)


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


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

    def window_days(conn: sqlite3.Connection) -> int:
        return int(db.get_setting(conn, "rolling_window_days", config.DEFAULT_WINDOW_DAYS))

    # --------------------------------------------------------------- home

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        with read() as conn:
            days = window_days(conn)
            rows = conn.execute(
                """
                SELECT a.id, a.original_title AS title, a.url, a.source,
                       a.original_outlet AS outlet, a.published_at_persian AS published,
                       a.published_time, c.category,
                       e.confidence_occurrence, e.gold_price_impact, e.security_relevance,
                       e.gold_trend, s.one_line
                FROM articles a
                JOIN latest_classification c ON c.article_id = a.id
                JOIN latest_evaluation e ON e.article_id = a.id
                LEFT JOIN latest_summary s ON s.article_id = a.id
                WHERE a.duplicate_of IS NULL AND a.fetched_at >= date('now', ?)
                ORDER BY COALESCE(a.published_at_gregorian, a.fetched_at) DESC
                """,
                (f"-{max(days, 1) - 1} days",),
            ).fetchall()
        notify = [
            row for row in rows
            if scoring.decide(
                row["confidence_occurrence"], row["gold_price_impact"], row["security_relevance"]
            ).notify
        ]
        return templates.TemplateResponse(request, "home.html", {
            "page": "home",
            "window_days": days,
            "articles": notify,
            "category_labels": dict(CATEGORY_LABELS),
        })

    @app.post("/settings/window")
    def set_window(days: int = Form(...)):
        conn = write()
        try:
            db.set_setting(conn, "rolling_window_days", str(max(1, days)))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/", status_code=303)

    # ------------------------------------------------------------ compare

    def _parse_variant(encoded: str) -> "evals.Variant | None":
        if not encoded:
            return None
        provider, model, version = encoded.split("\x1f")
        return evals.Variant(provider, model or None, version)

    @app.get("/compare", response_class=HTMLResponse)
    def compare_page(request: Request, a: str = "", b: str = ""):
        with read() as conn:
            variant_rows = conn.execute(
                "SELECT DISTINCT provider, model, prompt_version FROM classifications"
                " ORDER BY provider, model, prompt_version"
            ).fetchall()
            options = [
                {"key": f"{r['provider']}\x1f{r['model'] or ''}\x1f{r['prompt_version']}",
                 "label": f"{r['provider']} / {r['model'] or 'default'} / {r['prompt_version']}"}
                for r in variant_rows
            ]
            records: list[dict] = []
            error: str | None = None
            variant_a, variant_b = _parse_variant(a), _parse_variant(b)
            if variant_a and variant_b:
                try:
                    records = evals.diff_variants(conn, variant_a, variant_b)
                except ValueError as exc:
                    error = str(exc)
        return templates.TemplateResponse(request, "compare.html", {
            "page": "compare",
            "options": options,
            "records": records,
            "error": error,
            "same_count": sum(1 for r in records if r["agree"]),
            "selected": {"a": a, "b": b},
        })

    # ---------------------------------------------------------------- ops

    def runs_html() -> str:
        with read() as conn:
            rows = conn.execute(
                "SELECT run_id,status,started_at,articles_fetched,articles_processed,cost_usd"
                " FROM runs ORDER BY started_at DESC LIMIT 10"
            ).fetchall()
        if not rows:
            return "<p class='empty' style='padding:20px'>No runs recorded yet.</p>"
        body = "".join(
            f"<tr><td>{escape(r['run_id'])}</td><td>{escape(r['status'])}</td>"
            f"<td class='num'>{r['articles_fetched']}</td>"
            f"<td class='num'>{r['articles_processed']}</td>"
            f"<td class='num'>${r['cost_usd']:.4f}</td></tr>"
            for r in rows
        )
        return (
            "<table><thead><tr><th>Run ID</th><th>Status</th><th class='num'>Fetched</th>"
            "<th class='num'>Processed</th><th class='num'>Cost</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    @app.get("/ops", response_class=HTMLResponse)
    def ops(request: Request):
        with read() as conn:
            days = window_days(conn)
            source_rows = conn.execute(
                "SELECT name, health_status, last_success_at, last_error, priority"
                " FROM sources ORDER BY priority, name"
            ).fetchall()
            dead_reasons = conn.execute(
                "SELECT node, error_class, COUNT(*) n FROM dead_letters"
                " WHERE resolved_at IS NULL GROUP BY node, error_class ORDER BY n DESC"
            ).fetchall()
            coverage = telemetry.source_coverage(conn, days)
            funnel = telemetry.funnel(conn, days)
            dead_total = conn.execute(
                "SELECT COUNT(*) c FROM dead_letters WHERE resolved_at IS NULL"
            ).fetchone()["c"]
        return templates.TemplateResponse(request, "ops.html", {
            "page": "ops",
            "window_days": days,
            "sources": source_rows,
            "dead_reasons": dead_reasons,
            "dead_total": dead_total,
            "coverage": coverage,
            "funnel": funnel,
            "runs_html": runs_html(),
        })

    @app.get("/partials/runs", response_class=HTMLResponse)
    def partial_runs():
        return runs_html()

    @app.get("/api/telemetry")
    def api_telemetry(days: int = 14):
        with read() as conn:
            return {
                "token_cost_by_day": telemetry.token_cost_by_day(conn, days),
                "node_status_counts": telemetry.node_status_counts(conn, days),
                "provider_breakdown": telemetry.provider_breakdown(conn, days),
                "fetch_volume_by_source": telemetry.fetch_volume_by_source(conn, days),
            }

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
            "level_labels": LEVEL_LABELS,
            "trends": TRENDS,
            "trend_labels": TREND_LABELS,
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
