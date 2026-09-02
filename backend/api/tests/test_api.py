import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_is_public():
    response = APIClient().get("/api/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_articles_require_login():
    response = APIClient().get("/api/articles/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_authenticated_kpi_is_available():
    user = get_user_model().objects.create_user("reviewer", password="pass")
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/kpi/")
    assert response.status_code == 200
    assert response.json()["articles"] == 0
