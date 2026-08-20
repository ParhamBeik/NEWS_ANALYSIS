"""Command-line entry point for local and scheduled runs."""

from __future__ import annotations

import argparse
import json
import time

from . import config, dag, db, dedupe, exports, pipeline, providers, reviews, sources

PROVIDER_CHOICES = ["routed", "rule", "gapgpt", "ollama"]


def run_once(args: argparse.Namespace) -> dict[str, int]:
    config.ensure_dirs()
    conn = db.init_db()
    specs = sources.load_specs()
    with conn:
        sources.register(conn, specs)
    collected = []
    for name in getattr(args, "sources", None) or list(specs):
        if not specs[name].enabled:
            continue
        try:
            collected.extend(sources.fetch(specs[name], limit=args.limit))
            pipeline.set_source_health(conn, name, ok=True)
        except Exception as exc:  # one source cannot fail the cycle
            pipeline.set_source_health(conn, name, ok=False, error=str(exc)[:2000])
    with conn:
        stats = pipeline.process(conn, collected, providers.resolve(args.provider))

    # Backfill always classifies on the free offline baseline, never the run's real
    # provider: a coverage gap can mean hundreds of articles, and paying to label all of
    # them as a silent side effect of a routine `run --provider gapgpt` is not something a
    # budget ceiling catching it afterwards makes acceptable. Re-run with `replay --node
    # classify` if current-quality labels matter for the backfilled window.
    stats["backfilled"] = sum(pipeline.ensure_window(
        conn, specs, providers.resolve("rule"), days=db.window_days(conn)
    ).values())
    if args.export:
        exports.export_all(conn, config.OUTPUT_DIR)
    conn.close()
    return stats


def run_loop(args: argparse.Namespace, *, cycles: int | None = None) -> int:
    """Run cycles forever, surviving individual failures.

    A bare `while True: run_once()` let the first unhandled exception kill the daemon
    permanently and silently - a monitoring pipeline that stops monitoring is the failure
    this rebuild is about. Fatal errors (rejected credentials, exhausted budget) still stop
    the loop: retrying those just burns the clock, or the money, until someone intervenes.
    """
    interval = max(1, args.interval_minutes) * 60
    failures = completed = 0
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
        # Back off on repeated failure, so a source outage is not hammered every cycle.
        time.sleep(interval * min(2**failures, 8) if failures else interval)
    return 0


def _emit(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str))


def build_parser(source_names: list[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news-intel")
    commands = parser.add_subparsers(dest="command", required=True)
    provider_help = "`routed` uses config/routing.yaml; anything else pins all nodes"

    commands.add_parser("init")
    for name in ("run", "run-loop"):
        command = commands.add_parser(name)
        command.add_argument("--limit", type=int, default=25)
        command.add_argument("--provider", default="rule", choices=PROVIDER_CHOICES, help=provider_help)
        command.add_argument("--export", action="store_true")
        if name == "run":
            command.add_argument("--sources", nargs="+", choices=source_names)
        else:
            command.add_argument("--interval-minutes", type=int, default=30)

    replay = commands.add_parser("replay", help="invalidate a node and recompute it next run")
    replay.add_argument("--node", required=True, choices=list(pipeline.RESULT_TABLES))
    replay.add_argument("--version")

    commands.add_parser("export")
    commands.add_parser("routes", help="show which provider answers which node")

    dedupe_command = commands.add_parser("dedupe")
    dedupe_command.add_argument("--apply", action="store_true", help="link the matches, not just report")

    queue = commands.add_parser("review-queue")
    queue.add_argument("--size", type=int, default=100)
    queue.add_argument("--out", default="var/outputs/review_queue.xlsx")
    commands.add_parser("review-import").add_argument("path")

    canary = commands.add_parser("canary", help="is each source still alive?")
    canary.add_argument("--sources", nargs="+", choices=source_names)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("cases")
    evaluate.add_argument("--provider", default="rule",
                          choices=[c for c in PROVIDER_CHOICES if c != "routed"])

    golden = commands.add_parser("golden", help="export approved reviews as the eval set")
    golden.add_argument("--out", default="config/golden.json")

    compare = commands.add_parser("compare", help="diff two prompt/provider variants already run")
    for side in "ab":
        compare.add_argument(f"--{side}-provider", required=True)
        compare.add_argument(f"--{side}-version", required=True, help=f"prompt_version for variant {side.upper()}")
        compare.add_argument(f"--{side}-model", default=None)
    compare.add_argument("--out", default="var/outputs/compare")

    serve = commands.add_parser("serve", help="dashboard on :8000")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main() -> int:
    config.load_dotenv()
    # Read the source names from config so adding a source is a config edit only.
    args = build_parser(sorted(sources.load_specs())).parse_args()

    if args.command == "init":
        config.ensure_dirs()
        db.init_db().close()

    elif args.command == "run":
        _emit(run_once(args))

    elif args.command == "run-loop":
        return run_loop(args)

    elif args.command == "replay":
        with db.init_db() as conn:
            # classify/evaluate/summarize run with cacheable=False, so the real "already
            # done" gate reads the result tables directly, not node_events - invalidating
            # the cache alone would not cause a re-run.
            cleared = dag.invalidate(conn, args.node, version=args.version)
            query = f"DELETE FROM {pipeline.RESULT_TABLES[args.node]}" + (
                " WHERE prompt_version=?" if args.version else ""
            )
            rows = conn.execute(query, (args.version,) if args.version else ()).rowcount
            _emit({"cache_cleared": cleared, "results_cleared": rows})

    elif args.command == "export":
        with db.connect() as conn:
            _emit({name: str(path) for name, path in exports.export_all(conn, config.OUTPUT_DIR).items()})

    elif args.command == "dedupe":
        with db.init_db() as conn:
            merged = dedupe.backfill(conn, dry_run=not args.apply)
        for left, right, score in sorted(merged, key=lambda row: row[2]):
            print(f"{score:.3f}  {left}\n       {right}")
        _emit({"pairs": len(merged), "applied": args.apply})

    elif args.command == "review-queue":
        with db.init_db() as conn:
            count = reviews.create_queue(conn, size=args.size)
            path = reviews.export_queue(conn, config.ROOT / args.out)
        _emit({"queued": count, "path": str(path)})

    elif args.command == "review-import":
        with db.init_db() as conn:
            _emit(reviews.import_queue(conn, config.ROOT / args.path))

    elif args.command == "canary":
        conn = db.init_db()
        specs = sources.load_specs()
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
        _emit(report)

    elif args.command == "evaluate":
        cases = reviews.load_cases(config.ROOT / args.cases)
        _emit(reviews.evaluate(cases, providers.make_provider(args.provider)))

    elif args.command == "golden":
        path = config.ROOT / args.out
        with db.init_db() as conn:
            count = reviews.build_golden(conn, path)
        _emit({"cases": count, "path": str(path)})

    elif args.command == "routes":
        _emit(providers.describe(providers.resolve("routed")))

    elif args.command == "compare":
        with db.connect(readonly=True) as conn:
            _emit(reviews.compare(
                conn,
                a=reviews.Variant(args.a_provider, args.a_model, args.a_version),
                b=reviews.Variant(args.b_provider, args.b_model, args.b_version),
                out_dir=config.ROOT / args.out,
            ))

    else:
        import uvicorn

        from .dashboard import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
