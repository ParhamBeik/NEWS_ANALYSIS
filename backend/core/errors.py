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


def classify_exception(exc: BaseException) -> type[PipelineError]:
    """Route an arbitrary exception into the taxonomy. Unknown means Permanent."""
    if isinstance(exc, PipelineError):
        return type(exc)
    name = type(exc).__name__.lower()
    retryable = ("timeout", "connection", "ssl", "socket")
    return Transient if any(marker in name for marker in retryable) else Permanent
