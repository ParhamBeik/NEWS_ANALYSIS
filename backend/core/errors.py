"""Error taxonomy. Errors are classified, not caught.

Legacy caught bare `Exception` and retried everything forever - 465 articles were still
being re-sent every 30 minutes. Three classes, each with a different disposition:

- `Transient`  retry with exponential backoff (timeout, 429, 5xx, connection reset)
- `Permanent`  do not retry; dead-letter immediately (schema violation, unparseable page)
- `Fatal`      abort the whole run (bad credentials, budget exhausted, corrupt config)

`classify_exception` deliberately maps the UNKNOWN case to Permanent. Retrying something
you do not understand is how a pipeline burns money on a bug it will never recover from.

Retry lives in exactly one layer - the Celery task. A second retry loop inside the provider
client compounds silently: three provider attempts nested inside three task attempts is
nine HTTP calls and nine budget charges for one logical inference.
"""

from __future__ import annotations

import re


class PipelineError(Exception):
    """Base for errors the runtime knows how to route."""


class Transient(PipelineError):
    """Worth retrying: timeout, 429, 5xx, connection reset."""


class Permanent(PipelineError):
    """Not worth retrying: unparseable article, schema violation after repair."""


class Fatal(PipelineError):
    """Abort the run: bad credentials, budget exhausted, corrupt config."""


class BudgetExceeded(Fatal):
    """A spend or request ceiling was reached. Never falls back to another provider -
    that would keep spending past the ceiling the error exists to enforce."""


class Gone(Permanent):
    """The URL is gone (404/410). Retrying will not bring the page back."""


def classify_exception(exc: BaseException) -> type[PipelineError]:
    """Route an arbitrary exception into the taxonomy. Unknown means Permanent."""
    if isinstance(exc, PipelineError):
        return type(exc)
    name = type(exc).__name__.lower()
    retryable = ("timeout", "connection", "ssl", "socket")
    return Transient if any(marker in name for marker in retryable) else Permanent


# Why a fetch failed, in the words an operator acts on. Stored on CrawlAttempt and
# CoverageInterval; the exception class name alone said "Transient" for both a 429 and a
# dropped connection, which need opposite responses (slow down vs. wait).
ERROR_CLASSES = ("network", "blocked", "parse", "rate_limit", "gone", "provider")
_STATUS_IN_MESSAGE = re.compile(r"\bHTTP (\d{3})\b")


def error_class(exc: BaseException) -> str:
    """Map a fetch failure onto ERROR_CLASSES. Unknown means `parse`: anything that is
    not the network, the remote refusing us, or our own provider is our code meeting a
    page it did not expect."""
    if isinstance(exc, Gone):
        return "gone"
    if isinstance(exc, Fatal):
        return "provider"
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None and (match := _STATUS_IN_MESSAGE.search(str(exc))):
        status = int(match.group(1))
    if status == 429:
        return "rate_limit"
    if status in {404, 410}:
        return "gone"
    if status in {401, 403, 451} or "blocked" in type(exc).__name__.lower():
        return "blocked"
    if (status and status >= 500) or classify_exception(exc) is Transient:
        return "network"
    return "parse"
