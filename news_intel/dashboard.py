"""Five pages: notify feed, A/B diff, pipeline ops, human review, model KPIs.

- Home is the notify feed, not system health - the question you open this for is "what
  needs my attention". Pipeline health lives on /ops.
- The review form is PRE-SELECTED with the model's own answer, so a reviewer corrects
  rather than fills. "Not assessed" is a real option on every axis: an axis nobody judged
  must stay NULL (see scoring.py).
- UI chrome is English. Article text stays Persian and renders RTL inline; ordinal levels
  and trend symbols keep their Persian values under the hood, because the team's Excel
  dropdown requires those exact strings - only the on-screen label is translated.
- Monitoring reads through a read-only connection. Review submission and the window
  setting are the only write paths, and each opens its own connection.
"""

# NOTE: deliberately no `from __future__ import annotations`. FastAPI resolves route
# annotations via typing.get_type_hints against module globals, and the fastapi imports
# below are function-local (so the CLI does not hard-depend on the web stack). With
# postponed evaluation `Request` becomes an unresolvable string and every route answers 422.
import sqlite3
from pathlib import Path
from urllib.parse import unquote

from . import config, dag, db, metrics, prompts, reviews, scoring

CATEGORY_LABELS = list(zip(prompts.CATEGORIES, (
    "Security", "Economics", "Security/Economics", "Other",
)))
# Keyed off scoring.AXES so the review form and the KPI table cannot drift out of sync
# with the axes the notify rule actually votes over.
_AXIS_HELP = {
    "confidence_occurrence": ("Event confidence",
                              "How confident are we that this event actually happened?"),
    "gold_price_impact": ("Gold price impact",
                          'If the article isn\'t gold-related, choose "Not assessed".'),
    "security_relevance": ("Security relevance",
                           'If the article has no security angle, choose "Not assessed".'),
}
AXES = [(name, *_AXIS_HELP[name]) for name in scoring.AXES]
AXIS_LABELS = {name: label for name, label, _ in AXES}
LEVEL_LABELS = dict(zip(scoring.LEVELS, (
    "Very low (خیلی کم)", "Low (کم)", "Medium (متوسط)", "High (زیاد)", "Very high (خیلی زیاد)",
)))
TREND_LABELS = {"↑": "↑ Up", "↓": "↓ Down", "خنثی": "Neutral (خنثی)", "نامطمئن": "Uncertain (نامطمئن)"}
CATEGORY_LABEL_MAP = dict(CATEGORY_LABELS)
HOME_PAGE_SIZE = 30  # ponytail: fixed; add a picker if users ever ask for one
RUNS_SHOWN = 10


def _percent(value):
    return "—" if value is None else f"{value * 100:.0f}%"


def _short_url(url, limit=72):
    """Readable link text - percent-encoded Persian slugs run past 200 characters."""
    text = unquote(url or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sequential(count, largest):
    """Single-hue light->dark ramp for the confusion matrix: one hue encoding a magnitude,
    never a rainbow."""
    if not count:
        return "transparent"
    steps = ["var(--seq-100)", "var(--seq-250)", "var(--seq-400)", "var(--seq-550)"]
    return steps[min(int(count / max(largest, 1) * len(steps)), len(steps) - 1)]


def create_app(path: Path = None):
    from fastapi import FastAPI, Form, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates

    app = FastAPI(title="News Intel", docs_url=None)
    database = path or config.DB_PATH
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    # /compare renders values straight from storage, which are the workbook's Persian
    # vocabulary; every other page maps them before display, so these do it in-template.
    templates.env.filters.update(
        short_url=_short_url,
        level_label=lambda v: LEVEL_LABELS.get(v, v) if v else "—",
        trend_label=lambda v: TREND_LABELS.get(v, v) if v else "—",
        category_label=lambda v: CATEGORY_LABEL_MAP.get(v, v) if v else "—",
    )

    def read() -> sqlite3.Connection:
        return db.connect(database, readonly=True)

    def render(request, template, **context):
        return templates.TemplateResponse(request, template, context)

    # ------------------------------------------------------------------------- home

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, page: int = 1):
        with read() as conn:
            days = db.window_days(conn)
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
                ORDER BY COALESCE(a.published_at_gregorian, a.fetched_at) DESC, a.id DESC
                """,
                (db.day_floor(days),),
            ).fetchall()
        notify = [
            row for row in rows
            if scoring.decide(row["confidence_occurrence"], row["gold_price_impact"],
                              row["security_relevance"]).notify
        ]
        total_pages = max(1, -(-len(notify) // HOME_PAGE_SIZE))
        page = min(max(1, page), total_pages)
        start = (page - 1) * HOME_PAGE_SIZE
        return render(
            request, "home.html", page="home", window_days=days,
            articles=notify[start : start + HOME_PAGE_SIZE],
            category_labels=CATEGORY_LABEL_MAP, total_count=len(notify),
            current_page=page, total_pages=total_pages,
        )

    @app.post("/settings/window")
    def set_window(days: int = Form(...)):
        conn = db.connect(database)
        try:
            db.set_setting(conn, "rolling_window_days", str(max(1, days)))
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/", status_code=303)

    # ---------------------------------------------------------------------- compare

    @app.get("/compare", response_class=HTMLResponse)
    def compare_page(request: Request, a: str = "", b: str = ""):
        def parse(encoded):
            if not encoded:
                return None
            provider, model, version = encoded.split("\x1f")
            return reviews.Variant(provider, model or None, version)

        with read() as conn:
            options = [
                {"key": f"{r['provider']}\x1f{r['model'] or ''}\x1f{r['prompt_version']}",
                 "label": f"{r['provider']} / {r['model'] or 'default'} / {r['prompt_version']}"}
                for r in conn.execute(
                    "SELECT DISTINCT provider, model, prompt_version FROM classifications"
                    " ORDER BY provider, model, prompt_version"
                )
            ]
            records, error = [], None
            try:
                variant_a, variant_b = parse(a), parse(b)
                if variant_a and variant_b:
                    records = reviews.diff_variants(conn, variant_a, variant_b)
            except ValueError as exc:
                error = str(exc)
        return render(
            request, "compare.html", page="compare", options=options, records=records,
            error=error, same_count=sum(1 for r in records if r["agree"]),
            selected={"a": a, "b": b},
        )

    # -------------------------------------------------------------------------- ops

    @app.get("/ops", response_class=HTMLResponse)
    def ops(request: Request):
        with read() as conn:
            days = db.window_days(conn)
            return render(
                request, "ops.html", page="ops", window_days=days,
                sources=conn.execute(
                    "SELECT name, health_status, last_success_at, last_error, priority"
                    " FROM sources ORDER BY priority, name"
                ).fetchall(),
                dead_reasons=conn.execute(
                    "SELECT node, error_class, COUNT(*) n FROM dead_letters"
                    " WHERE resolved_at IS NULL GROUP BY node, error_class ORDER BY n DESC"
                ).fetchall(),
                dead_total=conn.execute(
                    "SELECT COUNT(*) c FROM dead_letters WHERE resolved_at IS NULL"
                ).fetchone()["c"],
                coverage=metrics.source_coverage(conn, days),
                funnel=metrics.funnel(conn, days),
                runs=conn.execute(
                    "SELECT run_id,status,started_at,articles_fetched,articles_processed,cost_usd"
                    " FROM runs ORDER BY started_at DESC LIMIT ?", (RUNS_SHOWN,)
                ).fetchall(),
                first_fetch_date=(conn.execute(
                    "SELECT MIN(fetched_at) f FROM articles"
                ).fetchone()["f"] or "")[:10],
            )

    @app.get("/api/telemetry")
    def api_telemetry(days: int = 14):
        with read() as conn:
            return {
                "token_cost_by_day": metrics.token_cost_by_day(conn, days),
                "node_status_counts": metrics.node_status_counts(conn, days),
                "provider_breakdown": metrics.provider_breakdown(conn, days),
                "fetch_volume_by_source": metrics.fetch_volume_by_source(conn, days),
            }

    # ----------------------------------------------------------------------- review

    @app.get("/review", response_class=HTMLResponse)
    def review(request: Request):
        with read() as conn:
            case = conn.execute(
                """
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
                WHERE r.status = 'pending' ORDER BY r.id LIMIT 1
                """
            ).fetchone()
            done = conn.execute(
                "SELECT COUNT(*) c FROM review_cases WHERE status='approved'"
            ).fetchone()["c"]
            total = conn.execute("SELECT COUNT(*) c FROM review_cases").fetchone()["c"]
        return render(
            request, "review.html", page="review", case=case, done=done, total=total,
            percent=round(done / total * 100) if total else 0,
            categories=CATEGORY_LABELS, levels=list(scoring.LEVELS),
            level_labels=LEVEL_LABELS, trends=list(prompts.GOLD_TRENDS),
            trend_labels=TREND_LABELS,
            axes=[{"name": name, "label": label, "hint": hint, "value": case[name]}
                  for name, label, hint in AXES] if case else [],
        )

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
        conn = db.connect(database)
        try:
            if action == "skip":
                cursor = conn.execute(
                    "UPDATE review_cases SET status='skipped', reviewed_at=? WHERE id=?",
                    (dag.utc_now(), review_id),
                )
            else:
                if not reviewed_category:
                    raise HTTPException(400, "reviewed_category is required")
                # An empty field means "not assessed" and must land as NULL, never as a
                # substituted level.
                cursor = conn.execute(
                    "UPDATE review_cases SET status='approved', reviewed_category=?,"
                    " confidence_occurrence=?, gold_price_impact=?, security_relevance=?,"
                    " gold_trend=?, one_line=?, reviewer_notes=?, reviewed_at=? WHERE id=?",
                    (reviewed_category, confidence_occurrence or None, gold_price_impact or None,
                     security_relevance or None, gold_trend or None, one_line.strip() or None,
                     reviewer_notes.strip() or None, dag.utc_now(), review_id),
                )
            if cursor.rowcount == 0:
                raise HTTPException(404, f"review case {review_id} not found")
            conn.commit()
        finally:
            conn.close()
        return RedirectResponse("/review", status_code=303)

    # -------------------------------------------------------------------------- kpi

    @app.get("/kpi", response_class=HTMLResponse)
    def kpi(request: Request):
        with read() as conn:
            report = metrics.compute(conn)
        largest = max((n for row in report.confusion.values() for n in row.values()), default=0)
        return render(
            request, "kpi.html", page="kpi", report=report, categories=metrics.CATEGORIES,
            axis_labels=AXIS_LABELS, pct=_percent, ramp=lambda n: _sequential(n, largest),
        )

    return app
