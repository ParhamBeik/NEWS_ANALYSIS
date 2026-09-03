"""Feed filtering.

The interesting decision here is `notify`. It is NOT a stored column - it is derived from
three nullable ordinal columns by `core.scoring.decide`, which is frozen invariant 2/4.

There are two ways to filter on it:

a) Re-express the rule as ORM `Case`/`When` annotations and let Postgres do it.
b) Ask `decide` for the answer and filter on the resulting primary keys.

(a) is faster and wrong-by-construction: it creates a SECOND implementation of the notify
rule, and the two would drift the first time a threshold moved. That drift is precisely the
bug this whole rebuild exists to remove - legacy suppressed every security alert because one
code path substituted a sentinel the other path did not expect.

So: (b). One rule, one implementation, one place to change it. The cost is materialising the
latest evaluation ids, which is a single indexed query over one row per article. At corpus
scale (thousands) it is milliseconds; if it ever stops being cheap, the fix is a stored
denormalised column written BY `decide`, never a second copy of the logic.
"""

from __future__ import annotations

import django_filters as filters
from django.db.models import Q, QuerySet

from articles.models import Article
from core.vocabulary import NotifyStatus
from inference.models import Classification, Evaluation


def articles_with_decision(status: str) -> set[int]:
    """Article ids whose LATEST evaluation reaches `status`, according to `decide` itself."""
    rows = (
        Evaluation.objects.latest_per_article()
        .only("article_id", "confidence_occurrence", "gold_price_impact", "security_relevance")
    )
    return {row.article_id for row in rows if row.decision.status == status}


class ArticleFilter(filters.FilterSet):
    source = filters.CharFilter(field_name="source_id")
    outlet = filters.CharFilter(field_name="original_outlet", lookup_expr="icontains")
    jalali_day = filters.CharFilter(field_name="published_at_jalali")
    since = filters.IsoDateTimeFilter(field_name="published_at", lookup_expr="gte")
    until = filters.IsoDateTimeFilter(field_name="published_at", lookup_expr="lte")
    tier = filters.CharFilter(field_name="extraction_tier")
    native_category = filters.CharFilter(field_name="native_category")

    category = filters.CharFilter(method="filter_category")
    notify = filters.ChoiceFilter(choices=NotifyStatus.choices, method="filter_notify")
    q = filters.CharFilter(method="filter_search")
    unanalysed = filters.BooleanFilter(method="filter_unanalysed")

    # NOTE: `include_duplicates` is deliberately NOT a filter here. django-filter only runs
    # a method when its parameter is present, so a "default on" filter cannot be expressed
    # as one - the absent case would silently widen instead of narrow. It lives in the
    # viewset's get_queryset, which is the only place that sees the request unconditionally.

    class Meta:
        model = Article
        fields: list[str] = []

    def filter_category(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        """Latest classification only. Filtering on ANY classification would surface an
        article under a category a superseded run assigned it."""
        latest = Classification.objects.latest_ids()
        return queryset.filter(
            classifications__pk__in=latest, classifications__category=value
        )

    def filter_notify(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        return queryset.filter(pk__in=articles_with_decision(value))

    def filter_search(self, queryset: QuerySet, name: str, value: str) -> QuerySet:
        """Substring, not full-text.

        Postgres full-text search has no Persian configuration, so `to_tsvector('persian')`
        does not exist and the 'simple' fallback would not stem or normalise anything a
        Persian reader expects. An icontains over folded text is honest about what it does;
        semantic search already exists on the embedding side for the cases that need it.
        """
        return queryset.filter(
            Q(original_title__icontains=value)
            | Q(lead__icontains=value)
            | Q(summaries__optimized_title__icontains=value)
        ).distinct()

    def filter_unanalysed(self, queryset: QuerySet, name: str, value: bool) -> QuerySet:
        """The backlog view: stored but never classified, including prefiltered rows."""
        if not value:
            return queryset
        return queryset.filter(classifications__isnull=True)
