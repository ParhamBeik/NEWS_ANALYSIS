"""Staff notices for conditions an operator must act on.

Checked every few minutes by `core.ops_alerts`. Each condition has a stable key; a notice
for a key goes out at most once per DEDUP window, claimed with an atomic cache `add`
(Redis SET NX), so two overlapping runs cannot both send it. A condition that is still
true after the window is sent again - a wallet that stays empty should keep being said.

Delivery is best effort and never raises:
- every condition is logged, sent or suppressed;
- email to active staff with an address, only when EMAIL_HOST is set;
- a JSON POST to OPS_ALERT_WEBHOOK_URL, only when set. The URL often carries a bot
  token, so it and the request exception text (which repeats it) are never logged.

Reader alerts (web push for events) are a different feature and live elsewhere.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone

from inference import budget, circuit

from .ops import OPEN_CIRCUIT_STATES, freshness_slo, priority_gaps

logger = logging.getLogger(__name__)

DEDUP = timedelta(hours=6)
BUDGET_WARN_SHARE = 0.8


def conditions(now=None) -> list[tuple[str, str]]:
    """(key, message) for every alert condition true right now."""
    now = now or timezone.now()
    found = []

    ceiling = settings.NEWS_MONTHLY_BUDGET_USD
    spent = budget.month_spend()
    if ceiling > 0 and spent >= BUDGET_WARN_SHARE * ceiling:
        found.append(("budget-month-80", f"AI spend this month is ${spent:.2f}, "
                      f"{spent / ceiling:.0%} of the ${ceiling:.2f} ceiling."))

    state = circuit.current()
    if state.state in OPEN_CIRCUIT_STATES:
        found.append((f"circuit-{state.state}",
                      f"AI provider circuit is {state.state}: {state.reason[:200]}"))

    for gap in priority_gaps(now):
        since = gap["since"].isoformat(timespec="minutes") if gap["since"] else "never covered"
        cause = f" ({gap['error_class']})" if gap["error_class"] else ""
        found.append((f"gap-{gap['source']}",
                      f"Priority source {gap['display_name']} has an open {gap['state']} "
                      f"gap{cause} since {since}."))

    # The window equals the dedup window, so each miss is reported about once.
    slo = freshness_slo(now, window=DEDUP)
    hours = slo["window_hours"]
    if slo["discovery"]["failed"]:
        found.append(("slo-discovery", f"{slo['discovery']['failed']} priority articles took "
                      f"over {slo['discovery']['target_minutes']} min to discover "
                      f"in the last {hours} h."))
    if slo["brief"]["failed"]:
        found.append(("slo-brief", f"{slo['brief']['failed']} high-tier events missed the "
                      f"{slo['brief']['target_minutes']} min brief target in the last {hours} h."))
    return found


def claim(key: str) -> bool:
    """True once per DEDUP window per key."""
    return cache.add(f"ops:alert:{key}", 1, int(DEDUP.total_seconds()))


def deliver(notices: list[tuple[str, str]]) -> list[str]:
    subject = f"[News Intelligence] {len(notices)} ops alert(s)"
    body = "\n".join(f"- {message}" for _, message in notices)
    channels = []
    if settings.EMAIL_HOST:
        recipients = list(
            get_user_model().objects.filter(is_staff=True, is_active=True)
            .exclude(email="").values_list("email", flat=True)
        )
        if recipients:
            try:
                send_mail(subject, body, None, recipients)
                channels.append("email")
            except Exception as exc:
                logger.warning("ops alert email failed: %s", type(exc).__name__)
    if settings.OPS_ALERT_WEBHOOK_URL:
        try:
            requests.post(
                settings.OPS_ALERT_WEBHOOK_URL,
                json={"text": f"{subject}\n{body}",
                      "alerts": [{"key": key, "message": message} for key, message in notices]},
                timeout=10,
            ).raise_for_status()
            channels.append("webhook")
        except requests.RequestException as exc:
            logger.warning("ops alert webhook failed: %s", type(exc).__name__)
    return channels


def notify_staff(now=None) -> dict:
    found = conditions(now)
    fresh = [(key, message) for key, message in found if claim(key)]
    sent = {key for key, _ in fresh}
    for key, message in found:
        logger.warning("ops alert %s%s: %s", key, "" if key in sent else " (suppressed)", message)
    channels = deliver(fresh) if fresh else []
    return {"conditions": [key for key, _ in found], "sent": sorted(sent), "channels": channels}
