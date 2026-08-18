"""Quality gates applied between extraction and inference.

Every article that reaches the classifier costs a paid API call, so anything the
extractor mangled should be stopped here rather than paid for and then acted on. Just as
important, a gate that fires often is a broken parser announcing itself - measured on
live fetches, 2 of 10 khabarfoori and 3 of 15 shahrekhabar articles arrive with no body
at all.

A gate returns a reason string, never a bare bool, so the dashboard can group failures by
cause and show which source is degrading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .core import dates, normalize

MIN_TITLE_CHARS = 10
# Title plus lead is enough to classify a photo post; body alone is not required.
MIN_EVIDENCE_CHARS = 40
FUTURE_TOLERANCE = timedelta(hours=6)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


ACCEPTED = Verdict(True)


def _parse(value: str | None) -> datetime | None:
    moment = dates.parse_iso(value)
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def check(article, *, now: datetime | None = None) -> Verdict:
    """Decide whether an article is worth spending an inference call on."""
    title = normalize.clean(article.title)
    lead = normalize.clean(article.lead)
    content = normalize.clean(article.content)

    if not title:
        return Verdict(False, "missing_title")
    if len(title) < MIN_TITLE_CHARS:
        return Verdict(False, "title_too_short")

    # The model reads title + lead + body. Any one of them can be thin; all three being
    # thin means the extractor produced nothing worth judging.
    evidence = len(title) + len(lead) + len(content)
    if evidence < MIN_EVIDENCE_CHARS:
        return Verdict(False, "insufficient_text")

    published = _parse(article.published_at)
    if published is not None:
        reference = now or datetime.now(timezone.utc)
        if published > reference + FUTURE_TOLERANCE:
            # A future timestamp means a misparsed date, and a wrong date silently
            # breaks dedup's time window and the workbook's daily grouping.
            return Verdict(False, "published_in_future")

    if not article.url or not article.url.startswith(("http://", "https://")):
        return Verdict(False, "invalid_url")

    return ACCEPTED


def partition(articles) -> tuple[list, list[tuple[object, str]]]:
    """Split articles into (accepted, [(article, reason), ...])."""
    accepted, rejected = [], []
    for article in articles:
        verdict = check(article)
        (accepted if verdict.ok else rejected).append(
            article if verdict.ok else (article, verdict.reason)
        )
    return accepted, rejected
