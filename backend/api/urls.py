"""API routes.

Auth is token-based for the Next.js server components (a header travels through a fetch
from a server runtime; a session cookie does not) and session-based for the browsable API
during development. Both are configured in REST_FRAMEWORK; this module only names paths.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .public import (
    AlertConfigView,
    AlertSubscriptionView,
    PublicAssetsView,
    PublicEventDetailView,
    PublicEventsView,
    PublicSourcesView,
    PublicTimelineView,
)
from .views import (
    ABPairViewSet,
    AnalysisSummaryView,
    ArticleViewSet,
    CollectionView,
    EventReviewDecisionView,
    EventReviewQueueView,
    EventReviewStatsView,
    EventSplitView,
    ExportDownloadView,
    ExportListView,
    FeedStatsView,
    HealthView,
    KPIView,
    LoginView,
    LogoutView,
    MarketView,
    MeView,
    OpsView,
    ReviewViewSet,
    RunViewSet,
    SignupView,
    SourceViewSet,
    VariantViewSet,
)

router = DefaultRouter()
router.register("articles", ArticleViewSet, basename="article")
router.register("sources", SourceViewSet, basename="source")
router.register("runs", RunViewSet, basename="run")
router.register("variants", VariantViewSet, basename="variant")
router.register("reviews", ReviewViewSet, basename="review")
router.register("ab/pairs", ABPairViewSet, basename="ab-pair")

urlpatterns = [
    path("public/alert-config/", AlertConfigView.as_view(), name="public-alert-config"),
    path("alerts/subscriptions/", AlertSubscriptionView.as_view(), name="alert-subscription"),
    path("public/events/", PublicEventsView.as_view(), name="public-events"),
    path("public/events/<int:event_id>/", PublicEventDetailView.as_view(), name="public-event"),
    path("public/sources/", PublicSourcesView.as_view(), name="public-sources"),
    path("public/assets/", PublicAssetsView.as_view(), name="public-assets"),
    path(
        "public/assets/<str:symbol>/timeline/",
        PublicTimelineView.as_view(),
        name="public-timeline",
    ),
    path("review/queue/", EventReviewQueueView.as_view(), name="event-review-queue"),
    path("review/stats/", EventReviewStatsView.as_view(), name="event-review-stats"),
    path(
        "review/events/<int:event_id>/",
        EventReviewDecisionView.as_view(),
        name="event-review-decision",
    ),
    path("review/events/<int:event_id>/split/", EventSplitView.as_view(), name="event-split"),
    path("collection/", CollectionView.as_view(), name="collection"),
    path("analysis-summary/", AnalysisSummaryView.as_view(), name="analysis-summary"),
    path("health/", HealthView.as_view(), name="health"),
    path("auth/token/", LoginView.as_view(), name="auth-token"),
    path("auth/signup/", SignupView.as_view(), name="auth-signup"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", MeView.as_view(), name="auth-me"),
    path("feed-stats/", FeedStatsView.as_view(), name="feed-stats"),
    path("ops/", OpsView.as_view(), name="ops"),
    path("kpi/", KPIView.as_view(), name="kpi"),
    path("market/", MarketView.as_view(), name="market"),
    path("exports/", ExportListView.as_view(), name="export-list"),
    # Unrestricted filename pattern on purpose: the view resolves and confirms containment
    # rather than trusting a regex to be an adequate path-traversal defence.
    path("exports/<path:name>/", ExportDownloadView.as_view(), name="export-download"),
    path("", include(router.urls)),
]
