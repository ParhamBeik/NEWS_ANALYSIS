"""API routes.

Auth is token-based for the Next.js server components (a header travels through a fetch
from a server runtime; a session cookie does not) and session-based for the browsable API
during development. Both are configured in REST_FRAMEWORK; this module only names paths.
"""

from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from .views import (
    ABPairViewSet,
    ArticleViewSet,
    ExportDownloadView,
    ExportListView,
    HealthView,
    KPIView,
    MarketView,
    MeView,
    OpsView,
    ReviewViewSet,
    RunViewSet,
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
    path("health/", HealthView.as_view(), name="health"),
    path("auth/token/", obtain_auth_token, name="auth-token"),
    path("auth/me/", MeView.as_view(), name="auth-me"),
    path("ops/", OpsView.as_view(), name="ops"),
    path("kpi/", KPIView.as_view(), name="kpi"),
    path("market/", MarketView.as_view(), name="market"),
    path("exports/", ExportListView.as_view(), name="export-list"),
    # Unrestricted filename pattern on purpose: the view resolves and confirms containment
    # rather than trusting a regex to be an adequate path-traversal defence.
    path("exports/<path:name>/", ExportDownloadView.as_view(), name="export-download"),
    path("", include(router.urls)),
]
