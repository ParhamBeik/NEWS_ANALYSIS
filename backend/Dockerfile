# One image serves gunicorn, both Celery worker pools, and beat. Five roles from one
# artifact means the code running in a worker is provably the code running in the web
# process - separate images drift, and the drift shows up as a task that works locally and
# dead-letters in production.

# `-bookworm` explicitly, not bare `-slim`. The bare tag follows Debian's stable pointer,
# so the interpreter bump would silently drag a distro bump along with it and the apt
# package names below (libjpeg62-turbo, libwebp7) are exactly the sort of thing that gets
# renamed across a Debian release. One variable at a time.
FROM python:3.13-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq for psycopg, and the imaging libraries Pillow needs to decode what Iranian news
# CDNs actually serve (jpeg, png, webp). The -dev headers are build-only and dropped from
# the final layer.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libpq5 libjpeg62-turbo libwebp7 zlib1g \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder
RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential libpq-dev libjpeg-dev libwebp-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM base AS runtime
COPY --from=builder /install /usr/local

# Non-root. The crawler parses untrusted HTML from five external sites and the inference
# layer parses untrusted JSON from a provider; neither needs to be able to write outside
# its own media directory.
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --chown=app:app . .
# Every path a named volume gets mounted on has to exist here and be owned by `app`.
# Docker seeds a fresh volume from the image directory underneath it; where that directory
# does not exist it creates the mount point as root, and the nightly export then fails with
# a permission error inside a Celery worker nobody is watching. /app/var/exports is
# deliberately NOT under /app/media - the edge file-serves that volume with no auth.
RUN mkdir -p /app/media /app/staticfiles /app/var/exports \
    && chown -R app:app /app/media /app/staticfiles /app/var
USER app

EXPOSE 8000

# Overridden per service in compose. This default is the web role, so a bare
# `docker run` of the image does something sensible rather than nothing.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
