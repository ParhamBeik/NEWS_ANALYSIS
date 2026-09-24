#!/bin/sh
# Read-only release gate on the VPS after compose up.
set -eu
cd "$(dirname "$0")"
compose() { docker compose -f docker-compose.prod.yml "$@"; }

for service in db redis backend worker-crawl worker-inference frontend; do
    id=$(compose ps -q "$service")
    [ -n "$id" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$id")" = healthy ] || {
        echo "$service is not healthy" >&2; exit 1;
    }
done
for service in beat backup; do
    id=$(compose ps -q "$service")
    [ -n "$id" ] && [ "$(docker inspect -f '{{.State.Running}}' "$id")" = true ] || {
        echo "$service is not running" >&2; exit 1;
    }
done

# The app's own API client exercises the authenticated queries without persisting a
# synthetic account or exposing a production token to CI.
compose exec -T backend python manage.py shell -c '
from django.conf import settings
from django.contrib.auth import get_user_model
from django_celery_beat.models import PeriodicTask
from rest_framework.test import APIClient
client = APIClient(HTTP_HOST=settings.ALLOWED_HOSTS[0])
client.force_authenticate(user=get_user_model()(is_staff=True, is_active=True))
for path in ("/api/articles/", "/api/ops/", "/api/kpi/", "/api/market/", "/api/exports/"):
    response = client.get(path)
    assert response.status_code == 200, f"{path}: HTTP {response.status_code}"
assert PeriodicTask.objects.filter(name__in=("crawl-all-sources", "inference-cycle", "weekly-circuit-probe"), enabled=True).count() == 3
'

# A successful process exit is not proof that a recoverable copy exists. The off-host
# marker is written only after a byte-for-byte checked copy has been promoted remotely.
compose exec -T backup sh -c '
    set -eu
    find /backups -maxdepth 1 -type f -name "*.dump" -mmin -2160 -print -quit | grep -q .
    test -f /backups/.offsite-last
    find /backups/.offsite-last -mmin -2160 -print -quit | grep -q .
    # A restart makes a new dump before the next hourly Mac pull. Accept the
    # previously copied archive while its verified marker is still fresh.
    copied=$(cat /backups/.offsite-last)
    case "$copied" in newsintel-*.dump) ;; *) exit 1 ;; esac
    test -s "/backups/$copied"
'
