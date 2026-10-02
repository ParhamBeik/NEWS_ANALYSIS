"""Takedown: hide an event or an article from every public surface, with an audit trail.

Hidden is not deleted. The row, its text and its analysis stay for the record; the public
API, radar, alerts and exports filter it out (`NewsEvent.objects.visible()`,
`Article.objects.canonical()`). Every change writes one append-only `TakedownLog` row.
"""

from __future__ import annotations

from django.db import transaction

from articles.models import Article, NewsEvent, TakedownLog
from core.actions import log_action

KINDS = {TakedownLog.Kind.EVENT: NewsEvent, TakedownLog.Kind.ARTICLE: Article}


@transaction.atomic
def set_hidden(kind: str, object_id: int, *, hidden: bool, reason: str, user=None) -> bool:
    """Hide or unhide one event or article. Returns False when it was already that way.

    A reason is required both ways: an unhide needs justifying as much as a hide does.
    """
    reason = (reason or "").strip()[:255]
    if not reason:
        raise ValueError("a reason is required")
    model = KINDS[kind]
    row = model.objects.select_for_update().get(pk=object_id)
    if row.hidden == hidden:
        return False
    model.objects.filter(pk=object_id).update(
        hidden=hidden, hidden_reason=reason if hidden else ""
    )
    action = TakedownLog.Action.HIDE if hidden else TakedownLog.Action.UNHIDE
    TakedownLog.objects.create(
        kind=kind, object_id=object_id, action=action, reason=reason,
        actor=user if getattr(user, "pk", None) else None,
        actor_name=user.get_username() if getattr(user, "pk", None) else "",
    )
    log_action("takedown", action, kind=kind, id=object_id)
    return True
