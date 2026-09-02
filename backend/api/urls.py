from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from .views import (
    ABPairViewSet,
    ArticleViewSet,
    HealthView,
    KPIView,
    ReviewViewSet,
    RunViewSet,
    VariantViewSet,
)

router = DefaultRouter()
router.register("articles", ArticleViewSet, basename="article")
router.register("runs", RunViewSet, basename="run")
router.register("variants", VariantViewSet, basename="variant")
router.register("reviews", ReviewViewSet, basename="review")
router.register("ab/pairs", ABPairViewSet, basename="ab-pair")

urlpatterns = [
    path("health/", HealthView.as_view()),
    path("auth/token/", obtain_auth_token),
    path("kpi/", KPIView.as_view()),
    path("", include(router.urls)),
]
