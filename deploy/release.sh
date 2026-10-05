#!/usr/bin/env bash
# Pull and restart the release IMAGE_TAG=<sha>, on the VPS, as root.
#
# Called by /usr/local/sbin/app-release (see .github/workflows/deploy.yml) after
# it has checked out <sha> in /opt/apps/news-intel. Both images were built on
# GitHub for that commit; this host only pulls them.
set -euo pipefail
cd "$(dirname "$0")"
: "${IMAGE_TAG:?IMAGE_TAG must be the commit SHA whose images to deploy}"

compose() { docker compose -f docker-compose.prod.yml "$@"; }
base=ghcr.io/parhambeik/news_analysis

# Pin the exact images in .env rather than passing them inline, so a later manual
# `docker compose up -d` on the box brings up the SAME version instead of :latest.
touch .env
sed -i '/^BACKEND_IMAGE=/d;/^FRONTEND_IMAGE=/d' .env
echo "BACKEND_IMAGE=$base-backend:$IMAGE_TAG" >> .env
echo "FRONTEND_IMAGE=$base-frontend:$IMAGE_TAG" >> .env

# GHCR resets connections from Iran mid-layer (2026-10-02: "read: connection reset
# by peer"). Finished layers are kept, so each retry only resumes the rest.
for attempt in 1 2 3 4 5; do
  compose pull && break
  [ "$attempt" = 5 ] && exit 1
  sleep $((attempt * 15))
done

# A paused crawl worker has accumulated periodic jobs. Recreating it would
# immediately run every stale cycle. Preserve both queues under release-tagged
# keys, then let Beat enqueue fresh work for the replacement worker.
if docker inspect -f '{{.State.Paused}}' newsintel-worker-crawl-1 2>/dev/null | grep -qx true; then
  for queue in crawl default; do
    if docker exec newsintel-redis-1 redis-cli EXISTS "$queue" | grep -qx 1; then
      docker exec newsintel-redis-1 redis-cli RENAMENX "$queue" "release-backlog-$queue-$IMAGE_TAG" | grep -qx 1
    fi
  done
fi

# 'up -d' recreates only what changed. The 'migrate' service is a one-shot that
# the app services wait on via service_completed_successfully, so schema changes
# land before anything serves them.
compose up -d --remove-orphans

# Dangling images only (no -a). The previous release stays TAGGED, so it is never
# a prune candidate and is always there to roll back to.
docker image prune -f >/dev/null

# Poll rather than sleep-and-hope: gunicorn plus migrations can take 30s.
for attempt in $(seq 1 20); do
  if sh ./check-stack.sh; then
    echo "stack healthy after $attempt attempt(s)"
    exit 0
  fi
  echo "attempt $attempt: not healthy yet"
  sleep 6
done
echo "stack did not pass check-stack.sh" >&2
compose ps >&2
compose logs --tail=80 backend frontend >&2
exit 1
