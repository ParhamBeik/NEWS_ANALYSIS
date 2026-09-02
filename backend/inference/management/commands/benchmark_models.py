"""Measure candidate models on the same real articles, and report what they cost.

GapGPT publishes no pricing endpoint, so "is this the right model?" cannot be answered
from documentation. It can be answered by running the candidates on identical inputs and
reading their own reported usage back.

What this measures, and why each one is here:

- cost per article, from the provider's reported usage (falling back to configured prices)
- p50 / p95 latency, because a 30-minute cycle can absorb a slow model and a live
  dashboard cannot
- SCHEMA COMPLIANCE - the share of calls that returned output matching the pydantic
  schema. This is the one that eliminates candidates. A cheap model that emits a level
  outside the five-value scale 8% of the time is not cheap; it is a dead-letter generator.
- pairwise category agreement, which says whether the expensive model is actually buying
  a different answer or just a more expensive identical one

Results are written to a JSON report and NOT into the inference tables. A bake-off is a
measurement of models, not a production run: persisting 360 classifications from six
candidates - five of which you are about to reject - would change what the live feed
shows and what `latest` means.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from articles.models import Article
from core.errors import BudgetExceeded, Fatal, Permanent, Transient
from core.vocabulary import AXES
from inference import budget
from inference.prompts import TASK_FOR_NODE, TASKS, messages
from inference.providers import GapGPTProvider

# Chosen from the 120 models the account can reach: the current default, its newer
# siblings, two cheap non-Google options, and one strong model as a quality ceiling.
DEFAULT_CANDIDATES = [
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gpt-5-nano",
    "gapgpt-qwen-3.6",
    "deepseek-v4-flash",
]


class Command(BaseCommand):
    help = "Benchmark candidate models on real articles and write a comparison report."

    def add_arguments(self, parser):
        parser.add_argument("--models", nargs="+", default=DEFAULT_CANDIDATES)
        parser.add_argument("--articles", type=int, default=60)
        parser.add_argument(
            "--nodes", nargs="+", default=["classify", "evaluate", "summarize"]
        )
        parser.add_argument(
            "--budget", type=float, default=5.0, help="Hard ceiling for the whole bake-off."
        )
        parser.add_argument("--out", default="")
        parser.add_argument(
            "--dry-run", action="store_true", help="Show the plan and estimated scale only."
        )

    # ------------------------------------------------------------------ article sample

    def _sample(self, count: int) -> list[Article]:
        """A spread across sources and extraction tiers, not the newest N.

        Taking the most recent articles would sample one news cycle and, worse, would
        over-represent whichever source published most in the last hour. Model choice has
        to hold on a thin IRNA feed item as well as on a 3,000-character Khabarfoori page.
        """
        pool = Article.objects.eligible_for_inference().order_by("-published_at")
        buckets: dict[tuple[str, str], list[Article]] = defaultdict(list)
        for article in pool[: count * 10]:
            buckets[(article.source_id, article.extraction_tier)].append(article)

        chosen: list[Article] = []
        while len(chosen) < count and any(buckets.values()):
            for key in list(buckets):
                if buckets[key]:
                    chosen.append(buckets[key].pop(0))
                    if len(chosen) == count:
                        break
                if not buckets[key]:
                    del buckets[key]
        return chosen

    # ------------------------------------------------------------------------ the run

    def handle(self, *args, **options):
        models = options["models"]
        nodes = options["nodes"]
        articles = self._sample(options["articles"])
        if not articles:
            self.stderr.write(self.style.ERROR("no eligible articles; crawl first"))
            return

        calls = len(articles) * len(models) * len(nodes)
        self.stdout.write(
            f"{len(articles)} articles x {len(models)} models x {len(nodes)} nodes "
            f"= {calls} calls, ceiling ${options['budget']:.2f}"
        )
        spread = Counter((a.source_id, a.extraction_tier) for a in articles)
        for (source, tier), n in spread.most_common():
            self.stdout.write(f"    {source:14} {tier:8} {n}")
        if options["dry_run"]:
            return

        # A management command legitimately sets its own ceiling; the pipeline's per-run
        # budget is sized for a 30-minute cycle, not for a deliberate experiment.
        settings.NEWS_RUN_BUDGET_USD = options["budget"]
        settings.NEWS_DAILY_BUDGET_USD = max(settings.NEWS_DAILY_BUDGET_USD, options["budget"])
        run_id = f"benchmark_{timezone.now():%Y%m%d_%H%M%S}"
        budget.reset(run_id)

        results: dict[str, dict] = {}
        answers: dict[str, dict[int, dict]] = defaultdict(dict)

        def measure_one(model_name: str):
            """One model, its calls issued SEQUENTIALLY.

            Models run in parallel with each other but never with themselves: p50/p95 are
            meant to describe what one article costs in wall-clock time, and firing a
            model's own calls concurrently would measure our thread pool instead. Six
            models in parallel turns a 4.5-hour sequential sweep into about 45 minutes.
            """
            provider = GapGPTProvider(model=model_name)
            return model_name, self._measure(
                provider, articles, nodes, run_id, answers[model_name]
            )

        with ThreadPoolExecutor(max_workers=len(models)) as pool:
            futures = {pool.submit(measure_one, name): name for name in models}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    model_name, summary = future.result()
                except Fatal as exc:
                    self.stderr.write(self.style.ERROR(f"{name}: {exc}"))
                    continue
                results[model_name] = summary
                self.stdout.write(
                    self.style.HTTP_INFO(f"== {model_name}: ")
                    + f"ok={summary['ok']} schema_fail={summary['schema_failures']} "
                    f"transient={summary['transient']} cost=${summary['cost_usd']:.4f} "
                    f"p50={summary['latency_p50_ms']}ms p95={summary['latency_p95_ms']}ms"
                )
                self.stdout.flush()

        report = {
            "generated_at": timezone.now().isoformat(),
            "run_id": run_id,
            "articles": [a.pk for a in articles],
            "nodes": nodes,
            "models": results,
            "agreement": self._agreement(answers),
            "total_cost_usd": round(budget.current(run_id).run_usd, 6),
        }
        path = Path(options["out"] or (settings.BASE_DIR / f"{run_id}.json"))
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        self._print_table(results, report["agreement"])
        self.stdout.write(
            self.style.SUCCESS(
                f"\ntotal ${report['total_cost_usd']:.4f}   report: {path}"
            )
        )

    def _measure(self, provider, articles, nodes, run_id, sink) -> dict:
        latencies: list[int] = []
        stats = {
            "model": provider.model, "ok": 0, "schema_failures": 0, "transient": 0,
            "fatal": 0, "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0,
        }
        for article in articles:
            record: dict = {}
            category = None
            for node in nodes:
                task_name = TASK_FOR_NODE[node]
                schema = TASKS[task_name][0]
                extra = {"category": category} if node == "evaluate" and category else {}
                if node == "evaluate" and not category:
                    # Evaluation is defined relative to a category; scoring an unclassified
                    # article would measure a different task than the pipeline performs.
                    continue
                payload = messages(
                    task_name,
                    title=article.original_title,
                    lead=article.lead,
                    content=article.content,
                    outlet=article.original_outlet or article.source_id,
                    examples=(),  # control conditions: the bake-off compares MODELS, not memory
                    **extra,
                )
                started = time.monotonic()
                try:
                    answer = provider.complete(payload, schema, run_id)
                except BudgetExceeded as exc:
                    # Includes provider quota exhaustion. Partial results are still worth
                    # reporting - schema compliance measured over 27 calls already
                    # eliminates candidates - so this finalises rather than discards.
                    self.stderr.write(self.style.WARNING(f"   {provider.model} stopping: {exc}"))
                    stats["stopped_early"] = str(exc)[:200]
                    return self._finalize(stats, latencies, articles)
                except Permanent as exc:
                    # Almost always a schema violation - the failure mode that eliminates
                    # a candidate, so it is counted rather than merely logged.
                    stats["schema_failures"] += 1
                    record[node] = {"error": str(exc)[:200]}
                    continue
                except Transient:
                    stats["transient"] += 1
                    continue
                except Fatal as exc:
                    stats["fatal"] += 1
                    stats["stopped_early"] = str(exc)[:200]
                    self.stderr.write(self.style.ERROR(f"   {provider.model} fatal: {exc}"))
                    return self._finalize(stats, latencies, articles)

                latencies.append(int((time.monotonic() - started) * 1000))
                stats["ok"] += 1
                stats["cost_usd"] += answer.usage.cost_usd
                stats["tokens_in"] += answer.usage.tokens_in
                stats["tokens_out"] += answer.usage.tokens_out
                record[node] = answer.data.model_dump()
                if node == "classify":
                    category = answer.data.category
            sink[article.pk] = record

        return self._finalize(stats, latencies, articles)

    @staticmethod
    def _finalize(stats: dict, latencies: list[int], articles: list) -> dict:
        """Complete the stats dict. Every exit path goes through here.

        A model that stopped early still produced measurements worth keeping, and an
        early-return that skipped this step is what turned a finished 1,080-call run into
        a KeyError in the report formatter.
        """
        stats = dict(stats)
        stats["cost_usd"] = round(stats["cost_usd"], 6)
        attempts = stats["ok"] + stats["schema_failures"]
        stats["schema_compliance"] = round(stats["ok"] / attempts, 4) if attempts else None
        # Per COMPLETED article, not per sampled article: a run that stopped a third of the
        # way through would otherwise report a third of the true per-article cost.
        completed = max(stats["ok"], 1)
        stats["cost_per_call"] = round(stats["cost_usd"] / completed, 8)
        stats["cost_per_article"] = (
            round(stats["cost_usd"] / len(articles), 6) if articles and stats["ok"] else None
        )
        stats.setdefault("stopped_early", "")
        return {**stats, **Command._latency(latencies)}

    @staticmethod
    def _latency(values: list[int]) -> dict:
        if not values:
            return {"latency_p50_ms": None, "latency_p95_ms": None}
        ordered = sorted(values)
        index = max(int(len(ordered) * 0.95) - 1, 0)
        return {
            "latency_p50_ms": int(statistics.median(ordered)),
            "latency_p95_ms": ordered[index],
        }

    @staticmethod
    def _agreement(answers: dict[str, dict[int, dict]]) -> dict:
        """Pairwise category agreement, and per-axis exact match on the ordinal scales.

        Without this a bake-off reports six prices for what might be one answer. Two models
        agreeing 98% of the time means the cheaper one is free money; agreeing 70% of the
        time means someone has to decide which is right, and that needs human labels.
        """
        models = sorted(answers)
        pairs: dict[str, dict] = {}
        for i, left in enumerate(models):
            for right in models[i + 1 :]:
                shared = set(answers[left]) & set(answers[right])
                category_hits = axis_hits = axis_total = 0
                category_total = 0
                for article_id in shared:
                    a, b = answers[left][article_id], answers[right][article_id]
                    if "classify" in a and "classify" in b and "error" not in a["classify"]:
                        if "error" not in b["classify"]:
                            category_total += 1
                            category_hits += a["classify"]["category"] == b["classify"]["category"]
                    if "evaluate" in a and "evaluate" in b:
                        for axis in AXES:
                            left_value = a["evaluate"].get(axis)
                            right_value = b["evaluate"].get(axis)
                            if left_value is None and right_value is None:
                                continue
                            axis_total += 1
                            axis_hits += left_value == right_value
                pairs[f"{left} vs {right}"] = {
                    "articles": len(shared),
                    "category_agreement": (
                        round(category_hits / category_total, 4) if category_total else None
                    ),
                    "axis_exact_agreement": (
                        round(axis_hits / axis_total, 4) if axis_total else None
                    ),
                }
        return pairs

    def _print_table(self, results: dict, agreement: dict) -> None:
        self.stdout.write("\n" + "=" * 104)
        self.stdout.write(
            f"{'model':24}{'ok':>5}{'schema':>9}{'$/call':>11}{'p50':>7}{'p95':>8}  note"
        )
        self.stdout.write("-" * 104)
        # Ranked by SCHEMA COMPLIANCE first, price second. A cheap model that fails the
        # schema is not cheap - it is a dead-letter generator - and sorting on price alone
        # puts it at the top of the table.
        ordered = sorted(
            results.items(),
            key=lambda kv: (
                -(kv[1].get("schema_compliance") or 0),
                kv[1].get("cost_per_call") or 9e9,
            ),
        )
        for name, row in ordered:
            compliance = row.get("schema_compliance")
            self.stdout.write(
                f"{name:24}{row['ok']:>5}"
                f"{('—' if compliance is None else f'{compliance:.1%}'):>9}"
                f"{(row.get('cost_per_call') or 0):>11.6f}"
                f"{row['latency_p50_ms'] or '—'!s:>7}"
                f"{row['latency_p95_ms'] or '—'!s:>8}"
                f"  {row.get('stopped_early', '')[:44]}"
            )
        self.stdout.write("\nagreement between models")
        for pair, row in agreement.items():
            category = row["category_agreement"]
            axis = row["axis_exact_agreement"]
            self.stdout.write(
                f"  {pair:52} category={'—' if category is None else f'{category:.1%}':>7}"
                f"  axes={'—' if axis is None else f'{axis:.1%}':>7}  (n={row['articles']})"
            )
