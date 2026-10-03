"""Staff takedown endpoints: parse, authorize, delegate to core.takedown, serialize."""

from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from articles.models import Article, NewsEvent, TakedownLog
from core.events import reported_at
from core.takedown import set_hidden

ACTIONS = {"hide": True, "unhide": False}


def visibility(event: NewsEvent) -> dict:
    articles = sorted(
        event.articles.select_related("source"), key=lambda a: (reported_at(a), a.id)
    )
    log = TakedownLog.objects.filter(
        Q(kind=TakedownLog.Kind.EVENT, object_id=event.id)
        | Q(kind=TakedownLog.Kind.ARTICLE, object_id__in=[a.id for a in articles])
    )[:50]
    return {
        "event": {"id": event.id, "hidden": event.hidden, "reason": event.hidden_reason or None},
        "articles": [
            {"id": a.id, "title": a.original_title, "source": a.source.display_name or a.source_id,
             "url": a.url, "hidden": a.hidden, "reason": a.hidden_reason or None}
            for a in articles
        ],
        "log": [
            {"kind": row.kind, "id": row.object_id, "action": row.action, "reason": row.reason,
             "by": row.actor_name or None, "at": row.created_at}
            for row in log
        ],
    }


def _apply(request, kind: str, object_id: int) -> bool:
    action = request.data.get("action")
    if action not in ACTIONS:
        raise ValidationError({"action": "choose hide or unhide"})
    try:
        return set_hidden(kind, object_id, hidden=ACTIONS[action],
                          reason=request.data.get("reason", ""), user=request.user)
    except ValueError as exc:
        raise ValidationError({"reason": str(exc)}) from exc


class EventVisibilityView(APIView):
    """GET the takedown state of one event and its reports; POST hide/unhide the event."""

    permission_classes = [IsAdminUser]

    def get(self, request, event_id: int):
        return Response(visibility(get_object_or_404(NewsEvent, pk=event_id)))

    def post(self, request, event_id: int):
        event = get_object_or_404(NewsEvent, pk=event_id)
        changed = _apply(request, TakedownLog.Kind.EVENT, event.id)
        event.refresh_from_db()
        return Response({"changed": changed, **visibility(event)})


class ArticleVisibilityView(APIView):
    """POST hide/unhide one report (article)."""

    permission_classes = [IsAdminUser]

    def post(self, request, article_id: int):
        article = get_object_or_404(Article, pk=article_id)
        changed = _apply(request, TakedownLog.Kind.ARTICLE, article.id)
        article.refresh_from_db()
        return Response({"changed": changed, "id": article.id, "hidden": article.hidden})
