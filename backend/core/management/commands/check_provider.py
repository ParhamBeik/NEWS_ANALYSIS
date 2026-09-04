"""Answer "which key am I actually using, and does it have money?" in one command.

Written after losing time to a stale `GAPGPT_API_KEY` exported in a shell, which shadowed
the .env file and made a funded account report as empty. Settings resolve env-over-file by
design (Docker needs that precedence), so the only cheap defence is being able to see which
value won.

Prints a key FINGERPRINT, never the key. A diagnostic that leaks a credential into a
terminal, a CI log or a screenshot is worse than no diagnostic.
"""

from __future__ import annotations

import hashlib

import requests
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Report which provider credentials are in effect and whether they work."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live", action="store_true",
            help="Issue one tiny real completion (a fraction of a cent) to prove the key works.",
        )
        parser.add_argument("--model", default="")

    def handle(self, *args, **options):
        key = settings.GAPGPT_API_KEY
        model = options["model"] or settings.GAPGPT_MODEL

        self.stdout.write(self.style.HTTP_INFO("provider configuration"))
        if not key:
            self.stderr.write(self.style.ERROR("  GAPGPT_API_KEY is EMPTY"))
            return
        fingerprint = hashlib.sha256(key.encode()).hexdigest()[:12]
        self.stdout.write(f"  key fingerprint  sha256:{fingerprint}  (length {len(key)})")
        self.stdout.write(f"  base url         {settings.GAPGPT_BASE_URL}")
        self.stdout.write(f"  chat model       {model}")
        self.stdout.write(f"  embedding model  {settings.GAPGPT_EMBEDDING_MODEL}")
        self.stdout.write(
            f"  budgets          run ${settings.NEWS_RUN_BUDGET_USD:.2f} / "
            f"day ${settings.NEWS_DAILY_BUDGET_USD:.2f} / "
            f"{settings.NEWS_MAX_PROVIDER_CALLS_PER_RUN} calls per run"
        )

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            usage = requests.get(
                f"{settings.GAPGPT_BASE_URL}/dashboard/billing/usage", headers=headers, timeout=20
            )
            self.stdout.write(f"  reported usage   {usage.text.strip()[:120]}")
        except requests.RequestException as exc:
            self.stderr.write(self.style.WARNING(f"  usage endpoint unreachable: {exc}"))

        if not options["live"]:
            self.stdout.write("\n  (pass --live to prove the key can actually spend)")
            return

        # The real test. GapGPT reserves the FULL max_tokens cost up front, so a key can
        # pass a 16-token probe and still fail a 350-token pipeline call - the probe uses
        # the pipeline's own limit to avoid reporting a false all-clear.
        self.stdout.write(self.style.HTTP_INFO("\nlive probe"))
        try:
            response = requests.post(
                f"{settings.GAPGPT_BASE_URL}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": 'Return JSON {"ok":1}'}],
                    "temperature": 0,
                    "max_tokens": settings.NEWS_MAX_OUTPUT_TOKENS,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            self.stderr.write(self.style.ERROR(f"  request failed: {exc}"))
            return

        if response.status_code == 200:
            reported = (response.json().get("usage") or {})
            self.stdout.write(
                self.style.SUCCESS(
                    f"  OK  cost={reported.get('cost', 'not reported')} "
                    f"tokens={reported.get('total_tokens')}"
                )
            )
            return

        detail = response.text[:300]
        if "quota" in detail.lower():
            self.stderr.write(
                self.style.ERROR(
                    f"  QUOTA EXHAUSTED (HTTP {response.status_code}) - top up the account, "
                    f"the key itself is valid:\n  {detail}"
                )
            )
        else:
            self.stderr.write(self.style.ERROR(f"  HTTP {response.status_code}: {detail}"))
