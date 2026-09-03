# Next.js standalone output: the runtime layer carries only the traced dependencies, not
# the full node_modules tree. That is the difference between a ~180 MB image and a ~1 GB
# one, and on a VPS with four other apps the disk is a real constraint.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# `npm ci` when a lockfile exists: an install that silently resolves a different minor
# version than the one CI tested is a deploy that differs from the build that passed.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

FROM node:20-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 10001 -S app && adduser -u 10001 -S app -G app

COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
# `public` is not traced into standalone output - the self-hosted Persian font lives here,
# and without this line every Persian headline silently falls back to Tahoma.
COPY --from=build --chown=app:app /app/public ./public

USER app
EXPOSE 3000
CMD ["node", "server.js"]
