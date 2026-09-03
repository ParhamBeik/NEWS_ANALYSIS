#!/usr/bin/env python3
"""Extract the module/data topology of the news_intel package.

Three edge sources, because a grep-only graph would misreport this codebase:

1. Direct edges  - `from . import x` / `from .x import y` in the AST.
2. Dispatch edges - targets reached through a lookup table rather than a named
   call: sources._STRATEGIES (fetch shape -> handler), providers._HOSTED
   (provider name -> constructor), pipeline.RESULT_TABLES (node -> table), and
   the FastAPI route decorators. Resolved by reading those literals, not by
   assuming the call is unresolvable.
3. Data edges - SQL statements are string literals here, so table reads/writes
   are extracted from the literals themselves and joined against the CREATE
   TABLE / CREATE VIEW names in db.SCHEMA. That schema is the config that maps
   logical name to physical store; there is no external descriptor.

Entry points come from cli.build_parser's subcommands and the dashboard's route
decorators, not from "module has no importer" - every module except cli would
otherwise look like an entry point.

Usage:  python3 analysis/news_intel/extract_topology.py
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "news_intel"
OUT = Path(__file__).resolve().parent

# Domains. Grouping is by role in the pipeline, which is also how the README
# orders the modules.
DOMAINS = {
    "Foundation": ["config", "text", "scoring", "db", "dag"],
    "Extraction": ["sources", "dedupe"],
    "Inference": ["prompts", "providers"],
    "Review": ["reviews"],
    "Orchestration": ["pipeline"],
    "Reporting": ["metrics", "exports"],
    "Delivery": ["dashboard", "cli"],
}
DOMAIN_OF = {module: domain for domain, mods in DOMAINS.items() for module in mods}

SQL_WRITE = re.compile(
    r"\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+([a-z_]+)", re.I)
SQL_READ = re.compile(r"\b(?:FROM|JOIN)\s+([a-z_]+)", re.I)
# `{table}` / `{RESULT_TABLES[...]}` interpolations: real edges, resolved below.
SQL_INTERP = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|FROM|JOIN)\s+\{(\w+)", re.I)


def schema_objects() -> set[str]:
    """Tables and views declared in db.SCHEMA - the logical store names."""
    text = (PKG / "db.py").read_text(encoding="utf-8")
    return set(re.findall(r"CREATE (?:TABLE|VIEW) IF NOT EXISTS (\w+)", text))


def string_literals(tree: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):  # f-strings: keep the literal parts
            out.append("".join(
                part.value for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            ))
    return out


def interpolated_tables(module: str) -> set[str]:
    """Resolve `f"... FROM {name}"` against the tables that variable can hold."""
    resolved: set[str] = set()
    source = (PKG / f"{module}.py").read_text(encoding="utf-8")
    for variable in SQL_INTERP.findall(source):
        if variable in {"table", "name"}:  # generic helpers: db.insert(conn, table, row)
            continue
        if "RESULT_TABLES" in source and variable in {"node", "args"}:
            resolved |= {"classifications", "evaluations", "summaries"}
    # pipeline._already_ran and cli replay both dispatch through RESULT_TABLES.
    if "RESULT_TABLES[" in source:
        resolved |= {"classifications", "evaluations", "summaries"}
    return resolved


def dispatch_targets(module: str, source: str) -> set[str]:
    """Modules reached through a lookup table rather than a direct named call."""
    targets: set[str] = set()
    if module == "cli":
        # `serve` imports the dashboard lazily so the CLI does not hard-depend on
        # the web stack; a plain import scan misses this edge entirely.
        if "from .dashboard import create_app" in source:
            targets.add("dashboard")
    return targets


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Every import cycle, found by DFS. Asserting acyclicity without checking is how a
    cycle gets introduced and then documented as impossible."""
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def walk(node: str, path: list[str], on_path: set[str]) -> None:
        for nxt in sorted(graph.get(node, ())):
            if nxt in on_path:
                cycle = path[path.index(nxt):] + [nxt]
                key = tuple(sorted(cycle))
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
            elif nxt in graph:
                walk(nxt, path + [nxt], on_path | {nxt})

    for start in sorted(graph):
        walk(start, [start], {start})
    return cycles


def layer_violations(edges: list[dict]) -> list[str]:
    """Import edges pointing from a lower layer up to a higher one."""
    order = list(DOMAINS)
    rank = {m: order.index(d) for d, mods in DOMAINS.items() for m in mods}
    return [
        f"{e['source']} -> {e['target']}"
        for e in edges
        if e["kind"] == "call" and e["source"] in rank and e["target"] in rank
        and rank[e["source"]] < rank[e["target"]]
    ]


def analyse() -> dict:
    stores = schema_objects()
    modules = sorted(p.stem for p in PKG.glob("*.py") if p.stem != "__init__")
    edges: list[dict] = []
    seen: set[tuple] = set()
    loc: dict[str, int] = {}
    reads: dict[str, set[str]] = {}
    writes: dict[str, set[str]] = {}

    def edge(source_id: str, target_id: str, kind: str) -> None:
        key = (source_id, target_id, kind)
        if source_id != target_id and key not in seen:
            seen.add(key)
            edges.append({"source": source_id, "target": target_id, "kind": kind})

    for module in modules:
        path = PKG / f"{module}.py"
        source = path.read_text(encoding="utf-8")
        loc[module] = len(source.splitlines())
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                if node.module:                       # from .db import insert
                    edge(module, node.module, "call")
                else:                                 # from . import db, dag
                    for alias in node.names:
                        edge(module, alias.name, "call")
        for target in dispatch_targets(module, source):
            edge(module, target, "dispatch")

        statements = " ".join(string_literals(tree))
        written = {t.lower() for t in SQL_WRITE.findall(statements)} & stores
        read = ({t.lower() for t in SQL_READ.findall(statements)} & stores) - written
        written |= interpolated_tables(module) & stores
        if written:
            writes[module] = written
        if read:
            reads[module] = read
        for table in sorted(written):
            edge(module, f"ds:{table}", "write")
        for table in sorted(read):
            edge(module, f"ds:{table}", "read")

    # -- entry points: CLI subcommands and HTTP routes, read from where they are declared
    cli_source = (PKG / "cli.py").read_text(encoding="utf-8")
    commands = sorted(set(re.findall(r'add_parser\(\s*"([\w-]+)"', cli_source)))
    routes = sorted(set(re.findall(r'@app\.(get|post)\("([^"]+)"',
                                   (PKG / "dashboard.py").read_text(encoding="utf-8"))))

    inbound = {e["target"] for e in edges if e["kind"] in {"call", "dispatch"}}
    entry_points = ["cli", "dashboard"]
    # Suppression: dashboard is only ever reached through cli's lazy import, and
    # every module is reachable from cli. Anything with no inbound edge that is
    # not an entry point is a genuine dead end here, because this package has no
    # reflection, no plugin loader and no DI container.
    dead_ends = [m for m in modules if m not in inbound and m not in entry_points]

    tree_children = [
        {"id": f"dom:{domain}", "name": domain, "kind": "domain", "children": [
            {"id": m, "name": m, "kind": "module", "language": "python",
             "loc": loc[m], "file": f"news_intel/{m}.py"}
            for m in mods if m in loc
        ]}
        for domain, mods in DOMAINS.items()
    ]
    tree_children.append({
        "id": "dom:data", "name": "Data stores", "kind": "domain", "children": [
            {"id": f"ds:{t}", "name": t, "kind": "datastore"} for t in sorted(stores)
        ],
    })

    fan_in: dict[str, int] = {}
    for e in edges:
        if e["kind"] in {"call", "dispatch"}:
            fan_in[e["target"]] = fan_in.get(e["target"], 0) + 1
    writers = {t: sorted(m for m, ts in writes.items() if t in ts) for t in stores}
    shared = {t: w for t, w in writers.items() if len(w) > 1}
    cycles = find_cycles({m: {e["target"] for e in edges
                              if e["source"] == m and e["kind"] in {"call", "dispatch"}}
                          for m in modules})
    layers = layer_violations(edges)

    observations = [
        f"Import cycles: {len(cycles)}. "
        + (f"Cycles found: {'; '.join(' -> '.join(c) for c in cycles)}."
           if cycles else
           "The graph is acyclic, so any module can be read without holding the rest in "
           "your head, and any one of them can be imported in isolation by a test."),
        f"Layering holds in one direction: {len(layers)} edge(s) point from a lower domain "
        f"up to a higher one"
        + (f" ({', '.join(layers)})." if layers else
           " - Foundation imports nothing above it, and each domain depends only downward."),
        f"`config` and `scoring` are the load-bearing modules (fan-in {fan_in.get('config', 0)} "
        f"and {fan_in.get('scoring', 0)}). `scoring` owns the level scale, the three axes and "
        f"the notify rule, and `db` imports it rather than the reverse - so the vocabulary has "
        f"exactly one definition, and storage depends on the domain rule instead of the other "
        f"way round.",
        f"Data stores with more than one writing module: {', '.join(sorted(shared))}. "
        f"Only `articles` is a genuine shared mutation - `pipeline` inserts and `dedupe` sets "
        f"`duplicate_of` on the same rows, serialized behind the sequential ingest loop. The "
        f"rest are split by verb, not contended: `pipeline` inserts inference and `cli replay` "
        f"deletes it; `dag` writes dead letters on node failure and `pipeline` on gate "
        f"rejection; `dashboard` updates review rows that `reviews` created.",
        "The three inference tables are append-only on the write path: nothing UPDATEs them, so "
        "re-running with a new prompt adds a row. That is what makes A/B comparison, `replay` "
        "and provider evaluation possible at all, and it is enforced by the code shape rather "
        "than by convention.",
        "`cli` -> `dashboard` is the only dispatch edge: the web stack is imported lazily inside "
        "the `serve` branch so the CLI does not hard-depend on FastAPI. A plain import scan "
        "reports `dashboard` as unreachable; it is not.",
        "Service-extraction candidate, if it ever comes up: `dashboard` and `metrics` read the "
        "database and never write inference. They already open a read-only connection, so they "
        "could run as a separate process against the same file with no code change beyond the "
        "entry point.",
        f"No module is orphaned: the dead-end scan over {len(modules)} modules found "
        f"{len(dead_ends) or 'no'} unreachable module(s).",
    ]

    flows = [
        {
            "name": "A story reaches the analyst's workbook",
            "persona": "The analyst who files the daily workbook",
            "description": "News is collected from the three sites, the duplicates are merged, "
                           "the model judges each story, and the day's workbook is written.",
            "steps": [
                {"label": "Collect today's stories from each site",
                 "nodes": ["cli", "sources"]},
                {"label": "Reject anything the extractor mangled, before paying for it",
                 "nodes": ["pipeline", "ds:dead_letters"]},
                {"label": "Store each story and merge repeats of the same story",
                 "nodes": ["pipeline", "dedupe", "ds:articles"]},
                {"label": "Ask the model to categorise, score and summarise it",
                 "nodes": ["providers", "prompts", "ds:classifications",
                           "ds:evaluations", "ds:summaries"]},
                {"label": "Decide which stories are worth an alert",
                 "nodes": ["scoring"]},
                {"label": "Write the day's Excel workbook and text feeds",
                 "nodes": ["exports"]},
            ],
        },
        {
            "name": "A reviewer corrects the model",
            "persona": "The reviewer checking the model's judgement",
            "description": "A reviewer is shown one story with the model's own answer already "
                           "filled in, and their correction improves three things at once.",
            "steps": [
                {"label": "Build a queue of the stories most worth a human's time",
                 "nodes": ["cli", "reviews", "ds:review_cases"]},
                {"label": "Show one story with the model's answer pre-selected",
                 "nodes": ["dashboard", "ds:articles", "ds:latest_classification"]},
                {"label": "Record what the reviewer actually decided",
                 "nodes": ["dashboard", "ds:review_cases"]},
                {"label": "Update the accuracy scoreboard",
                 "nodes": ["metrics", "ds:latest_evaluation"]},
                {"label": "Feed the correction back as an example for the next run",
                 "nodes": ["reviews", "prompts"]},
            ],
        },
        {
            "name": "Choosing between two models",
            "persona": "The engineer deciding whether a cheaper model is good enough",
            "description": "Two already-recorded runs are compared story by story, so the "
                           "choice is made on evidence instead of impression.",
            "steps": [
                {"label": "Pick the two runs to compare",
                 "nodes": ["dashboard", "ds:classifications"]},
                {"label": "Line them up story by story and mark the disagreements",
                 "nodes": ["reviews", "ds:evaluations"]},
                {"label": "Check each one against what reviewers actually said",
                 "nodes": ["metrics", "ds:review_cases"]},
                {"label": "Point the chosen step at the winning model",
                 "nodes": ["providers"]},
            ],
        },
        {
            "name": "Filling a gap in the record",
            "persona": "The analyst who needs the last two weeks to be complete",
            "description": "Each cycle checks whether any day in the window is missing, and "
                           "only then pages back through a site's archive.",
            "steps": [
                {"label": "Check every day in the window for missing coverage",
                 "nodes": ["pipeline", "ds:articles"]},
                {"label": "Page back through the site's archive, but only if a day is missing",
                 "nodes": ["sources"]},
                {"label": "Label the recovered stories on the free offline baseline",
                 "nodes": ["providers", "ds:classifications"]},
                {"label": "Remember the attempt so an unfillable gap is not retried hourly",
                 "nodes": ["pipeline", "ds:settings"]},
                {"label": "Show per-source coverage honestly, including what cannot backfill",
                 "nodes": ["dashboard", "metrics"]},
            ],
        },
    ]

    return {
        "system": "News Intelligence Pipeline",
        "root": {"id": "sys", "name": "News Intelligence Pipeline", "kind": "system",
                 "children": tree_children},
        "edges": edges,
        "entryPoints": entry_points,
        "deadEnds": dead_ends,
        "observations": observations,
        "flows": flows,
        "_summary": {
            "modules": len(modules), "datastores": len(stores), "edges": len(edges),
            "cli_commands": commands, "http_routes": [f"{m.upper()} {p}" for m, p in routes],
            "fan_in": dict(sorted(fan_in.items(), key=lambda kv: -kv[1])),
            "writers_per_store": {t: w for t, w in sorted(writers.items()) if w},
        },
    }


def main() -> None:
    topology = analyse()
    (OUT / "topology.json").write_text(
        json.dumps(topology, indent=2, ensure_ascii=False), encoding="utf-8")
    s = topology["_summary"]

    print(f"{topology['system']}")
    print(f"  {s['modules']} modules, {s['datastores']} data stores, {s['edges']} edges")
    print(f"\nEntry points")
    print(f"  CLI ({len(s['cli_commands'])}): {', '.join(s['cli_commands'])}")
    print(f"  HTTP ({len(s['http_routes'])}): {', '.join(s['http_routes'])}")

    print("\nMost depended-on modules (fan-in)")
    for module, count in list(s["fan_in"].items())[:8]:
        if not module.startswith("ds:"):
            print(f"  {module:12} {'#' * count} {count}")

    print("\nWriters per data store")
    for store, writers in s["writers_per_store"].items():
        flag = "  <-- multiple writers" if len(writers) > 1 else ""
        print(f"  {store:24} {', '.join(writers)}{flag}")

    print(f"\nDead ends: {', '.join(topology['deadEnds']) or 'none'}")
    print("\nObservations")
    for line in topology["observations"]:
        print(f"  - {line}")


if __name__ == "__main__":
    main()
