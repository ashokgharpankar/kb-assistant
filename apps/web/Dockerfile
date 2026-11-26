# syntax=docker/dockerfile:1.7
# The web UI image: the built React app served by nginx, which also forwards /api/
# to the API (same origin, no CORS). Build from the repo root:
#   docker build -f apps/web/Dockerfile -t kb-assistant-web:local .
#
# Configured at runtime, so one image works everywhere:
#   API_UPSTREAM             where /api/ goes (default http://api:8000)
#   VITE_COGNITO_AUTHORITY   } served as /config.json; leave empty for no sign-in
#   VITE_COGNITO_CLIENT_ID   } (the API decides whether that's allowed)
#   VITE_COGNITO_DOMAIN      }

FROM node:22-alpine AS build
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

# nginx-unprivileged runs as uid 101 and listens on 8080: no root, no port below 1024.
# Pin a version tag (e.g. 1.30.7-alpine) once nginx-unprivileged publishes it: on
# 2026-11-26 the newest was 1.31.7 (2026-10-19), a week after the nginx 1.30.7 / 1.31.9
# security release. Until then: stable-alpine + the reviewed nginx entries in .trivyignore.
# (A literal tag, not an ARG: checkov's CKV_DOCKER_7 can't see the tag inside ${...}.)
FROM nginxinc/nginx-unprivileged:stable-alpine AS runtime
# Alpine fixes OS libraries (zlib, musl, expat, curl…) faster than base images are
# rebuilt; take them at build time. nginx itself comes from the tag above.
USER root
RUN apk upgrade --no-cache
COPY apps/web/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY apps/web/nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /web/dist /usr/share/nginx/html
# The nginx entrypoint substitutes these into the template at start-up. Only variables
# defined here are substituted, so nginx's own $uri, $host… are left alone.
ENV API_UPSTREAM=http://api:8000 \
    VITE_COGNITO_AUTHORITY="" \
    VITE_COGNITO_CLIENT_ID="" \
    VITE_COGNITO_DOMAIN=""
# The base image already runs as nginx (uid 101); stated here so it's explicit and checked.
USER 101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
