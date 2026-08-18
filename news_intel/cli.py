"""Command-line entry point for local and scheduled runs."""

from __future__ import annotations

import argparse
import json
import time

from . import backfill, dashboard, dedupe, evals, exports, pipeline, reviews, routing, sources
from .core import config, dag, db
from .providers import Provider, make_provider

PROVIDER_CHOICES = ["routed", "rule", "gapgpt", "ollama"]
REPLAY_TABLES = {"classify": "classifications", "evaluate": "evaluations", "summarize": "summaries"}


def resolve_providers(choice: str) -> dict[str, Provider]:
    """`routed` reads config/routing.yaml; anything else pins every node to one provider."""
    routes = routing.load(override=None if choice == "routed" else choice)
    return routing.build(routes)


def run_once(args: argparse.Namespace) -> dict[str, int]:
    config.ensure_dirs()
    conn = db.init_db()
    specs = sources.load_specs(config.SOURCES_DIR)
    with conn:
        sources.register(conn, specs)
    selected = args.sources or list(specs)
    providers = resolve_providers(args.provider)
    collected = []
    for name in selected:
        spec = specs[name]
        if not spec.enabled:
            continue
        try:
            articles = sources.fetch(spec, limit=args.limit)
            pipeline.set_source_health(conn, name, ok=True)
            collected.extend(articles)
        except Exception as exc:  # one source cannot fail the cycle
            pipeline.set_source_health(conn, name, ok=False, error=str(exc)[:2000])
    with conn:
        stats = pipeline.process(conn, collected, providers)
    window_days = db.window_days(conn)
    # Backfill always classifies on the free offline baseline, never the run's real
    # provider - a coverage gap can mean hundreds of articles, and paying to label all of
    # them as a silent side effect of a routine `run --provider gapgpt` is not something
    # a budget ceiling catching it after the fact makes acceptable. Re-run classification
    # at a real provider later (`cli replay --node classify`) if current-quality labels
    # matter for the backfilled window.
    backfill_providers = resolve_providers("rule")
    stats["backfilled"] = sum(
        backfill.ensure_window(conn, specs, backfill_providers, days=window_days).values()
    )
    if args.export:
        exports.export_all(conn, config.OUTPUT_DIR)
    conn.close()
    return stats


def run_loop(args: argparse.Namespace, *, cycles: int | None = None) -> int:
    """Run cycles forever, surviving individual failures.

    The previous version was a bare `while True: run_once()`, so the first unhandled
    exception - one API timeout, one malformed page - killed the daemon permanently and
    silently. A monitoring pipeline that stops monitoring is the failure this whole
    rebuild is about, so a failed cycle is logged, backed off, and retried.

    Fatal errors (rejected credentials, exhausted budget) still stop the loop: retrying
    those just burns the clock, or the money, until someone intervenes.
    """
    interval = max(1, args.interval_minutes) * 60
    failures = 0
    completed = 0
    while cycles is None or completed < cycles:
        try:
            print(json.dumps(run_once(args), ensure_ascii=False), flush=True)
            failures = 0
        except dag.Fatal as exc:
            print(json.dumps({"error": "fatal", "detail": str(exc)}), flush=True)
            return 1
        except KeyboardInterrupt:
            return 0
        except Exception as exc:  # noqa: BLE001 - a bad cycle must not end the daemon
            failures += 1
            print(json.dumps({"error": type(exc).__name__, "detail": str(exc)[:500],
                              "consecutive_failures": failures}), flush=True)
        completed += 1
        if cycles is not None and completed >= cycles:
            break
        # Back off on repeated failure so a source outage does not hammer it every cycle.
        time.sleep(interval * min(2 ** failures, 8) if failures else interval)
    return 0


def main() -> int:
    config.load_dotenv()
    # Read from config/sources/*.yaml rather than hardcoding names, so adding a source
    # is a new yaml file only - no cli.py edit required.
    source_names = sorted(sources.load_specs(config.SOURCES_DIR))
    parser = argparse.ArgumentParser(prog="news-intel")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    run = commands.add_parser("run")
    run.add_argument("--sources", nargs="+", choices=source_names)
    run.add_argument("--limit", type=int, default=25)
    run.add_argument("--provider", default="rule", choices=PROVIDER_CHOICES,
                     help="`routed` uses config/routing.yaml; anything else pins all nodes")
    run.add_argument("--export", action="store_true")
    loop = commands.add_parser("run-loop")
    loop.add_argument("--interval-minutes", type=int, default=30)
    loop.add_argument("--limit", type=int, default=25)
    loop.add_argument("--provider", default="rule", choices=PROVIDER_CHOICES,
                      help="`routed` uses config/routing.yaml; anything else pins all nodes")
    loop.add_argument("--export", action="store_true")
    replay = commands.add_parser("replay")
    replay.add_argument("--node", required=True)
    replay.add_argument("--version")
    commands.add_parser("export")
    dedupe_parser = commands.add_parser("dedupe")
    dedupe_parser.add_argument("--apply", action="store_true",
                               help="link the matches; without it, only report them")
    review_queue = commands.add_parser("review-queue")
    review_queue.add_argument("--size", type=int, default=100)
    review_queue.add_argument("--out", default="var/outputs/review_queue.xlsx")
    review_import = commands.add_parser("review-import")
    review_import.add_argument("path")
    canary = commands.add_parser("canary")
    canary.add_argument("--sources", nargs="+", choices=source_names)
    evaluate_parser = commands.add_parser("evaluate")
    evaluate_parser.add_argument("cases")
    evaluate_parser.add_argument(
        "--provider", default="rule", choices=[c for c in PROVIDER_CHOICES if c != "routed"]
    )
    golden = commands.add_parser("golden", help="export approved reviews as the eval set")
    golden.add_argument("--out", default="config/golden.json")
    commands.add_parser("routes", help="show which provider answers which node")
    compare = commands.add_parser("compare", help="diff two prompt/provider variants already run")
    compare.add_argument("--a-provider", required=True)
    compare.add_argument("--a-version", required=True, help="prompt_version for variant A")
    compare.add_argument("--a-model", default=None)
    compare.add_argument("--b-provider", required=True)
    compare.add_argument("--b-version", required=True, help="prompt_version for variant B")
    compare.add_argument("--b-model", default=None)
    compare.add_argument("--out", default="var/outputs/compare")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "init":
        config.ensure_dirs()
        db.init_db().close()
    elif args.command == "run":
        print(json.dumps(run_once(args), ensure_ascii=False))
    elif args.command == "run-loop":
        run_loop(args)
    elif args.command == "replay":
        with db.init_db() as conn:
            cache_cleared = dag.invalidate(conn, args.node, version=args.version)
            # classify/evaluate/summarize run with cacheable=False (pipeline.py); the real
            # "already done" gate `_exists()` checks these tables directly, not node_events,
            # so invalidating the cache alone would not cause a re-run.
            table = REPLAY_TABLES.get(args.node)
            results_cleared = 0
            if table:
                query = f"DELETE FROM {table}" + (" WHERE prompt_version=?" if args.version else "")
                params = (args.version,) if args.version else ()
                results_cleared = conn.execute(query, params).rowcount
            print(json.dumps({"cache_cleared": cache_cleared, "results_cleared": results_cleared}))
    elif args.command == "export":
        with db.connect() as conn:
            print({name: str(path) for name, path in exports.export_all(conn, config.OUTPUT_DIR).items()})
    elif args.command == "dedupe":
        with db.init_db() as conn:
            merged = dedupe.backfill(conn, dry_run=not args.apply)
        for left, right, score in sorted(merged, key=lambda row: row[2]):
            print(f"{score:.3f}  {left}\n       {right}")
        print(json.dumps({"pairs": len(merged), "applied": args.apply}))
    elif args.command == "review-queue":
        with db.init_db() as conn:
            count = reviews.create_queue(conn, size=args.size)
            output = reviews.export_queue(conn, config.ROOT / args.out)
            print(json.dumps({"queued": count, "path": str(output)}))
    elif args.command == "review-import":
        with db.init_db() as conn:
            print(reviews.import_queue(conn, config.ROOT / args.path))
    elif args.command == "canary":
        conn = db.init_db()
        specs = sources.load_specs(config.SOURCES_DIR)
        report = {}
        for name in args.sources or list(specs):
            try:
                report[name] = len(sources.fetch(specs[name], limit=1))
                pipeline.set_source_health(conn, name, ok=True)
            except Exception as exc:
                report[name] = f"error: {exc}"
                pipeline.set_source_health(conn, name, ok=False, error=str(exc)[:2000])
        conn.commit()
        conn.close()
        print(json.dumps(report, ensure_ascii=False))
    elif args.command == "evaluate":
        cases = evals.load_cases(config.ROOT / args.cases)
        print(json.dumps(evals.evaluate(cases, make_provider(args.provider)), ensure_ascii=False))
    elif args.command == "golden":
        with db.init_db() as conn:
            path = config.ROOT / args.out
            count = evals.build_golden(conn, path)
        print(json.dumps({"cases": count, "path": str(path)}, ensure_ascii=False))
    elif args.command == "routes":
        print(json.dumps(routing.describe(resolve_providers("routed")), ensure_ascii=False))
    elif args.command == "compare":
        with db.connect(readonly=True) as conn:
            summary = evals.compare(
                conn,
                a=evals.Variant(args.a_provider, args.a_model, args.a_version),
                b=evals.Variant(args.b_provider, args.b_model, args.b_version),
                out_dir=config.ROOT / args.out,
            )
        print(json.dumps(summary, ensure_ascii=False))
    else:
        import uvicorn
        uvicorn.run(dashboard.create_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
