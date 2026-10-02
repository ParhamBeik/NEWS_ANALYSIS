"""Reader alert rules. The one definition; accounts.tasks only applies them.

Who is told:
  An event alerts a user when it is tagged with a watch item on their watchlist AND its
  impact tier reaches their dial (low/medium/high = tier >= 2/3/4). The one universal alert
  is "breaking": global tier 5 reaches every account, watchlist or not.

When they are told again:
  Only when the evidence level flips (e.g. single -> multi) or the tier rises above what
  they were last told. A merge never re-alerts: when assessment merges two events, a user
  already told about either one has their ledger rebased to the merged state silently.

How:
  Every alert lands in the in-app inbox. It is also pushed unless held: at most
  DAILY_PUSH_CAP pushes per user per Tehran day, none inside the user's quiet hours
  (default 23:00-07:00 Tehran). Tier 5 and breaking alerts are exempt from both.
"""

from __future__ import annotations

from datetime import time

DIAL_MIN_TIER = {"low": 2, "medium": 3, "high": 4}
TOP_TIER = 5
DAILY_PUSH_CAP = 5


def reason(*, watched: bool, tier: int | None, global_tier: int | None, dial: str) -> str:
    """'breaking', 'watch', or '' (no alert)."""
    if global_tier == TOP_TIER:
        return "breaking"
    if watched and tier is not None and tier >= DIAL_MIN_TIER.get(dial, DIAL_MIN_TIER["medium"]):
        return "watch"
    return ""


def change(previous: tuple[int, str] | None, tier: int, evidence: str) -> str:
    """'new', 'update', or '' against the (tier, evidence) the user was last told."""
    if previous is None:
        return "new"
    last_tier, last_evidence = previous
    if evidence != last_evidence or tier > last_tier:
        return "update"
    return ""


def in_quiet_hours(now: time, start: time, end: time) -> bool:
    """Wall-clock window; wraps midnight when start > end. start == end means none."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def hold(*, exempt: bool, quiet: bool, pushed_today: int) -> str:
    """Why a push is held back to the inbox only: 'quiet', 'cap', or '' (push it)."""
    if exempt:
        return ""
    if quiet:
        return "quiet"
    if pushed_today >= DAILY_PUSH_CAP:
        return "cap"
    return ""
