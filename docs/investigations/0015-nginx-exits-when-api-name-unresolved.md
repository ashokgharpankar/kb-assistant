# Incident 0015: The UI went down because nginx couldn't resolve the API's name at start-up

**Date:** 2026-11-27 · **Phase:** 7a · **Severity:** medium locally (UI down); would be high in production
**Status:** Fixed (request-time resolution), verified with nginx against a reachable and an unresolvable upstream

## Summary

After rebuilding the app containers for Phase 7a, http://localhost:8080 didn't load: `curl`
returned `000`. The web container had `Exited (1)`. Its log:
`nginx: [emerg] host not found in upstream "api" in /etc/nginx/conf.d/default.conf:26`.
The API container was running and healthy.

## Root cause

`proxy_pass http://api:8000/;` makes nginx resolve `api` **once, at start-up**. If the name
can't be resolved at that moment (here: the API container had just been recreated, and the
web container started without it on its network), nginx refuses to start. The whole UI, and
the `/healthz` check that should only say "nginx is alive", went down because one upstream
name was missing for a moment.

The same coupling exists in Kubernetes (the Service's DNS name) and would appear in any
restart order problem.

## Resolution

- nginx resolves the API **per request**: `resolver ${NGINX_LOCAL_RESOLVERS} valid=10s;`, the
  upstream in a variable (`set $api_upstream ...; proxy_pass $api_upstream;`), and a `rewrite`
  to strip `/api` (nginx doesn't strip the prefix when `proxy_pass` uses a variable).
- The web image sets `NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1`, so the official entrypoint fills
  `NGINX_LOCAL_RESOLVERS` from `/etc/resolv.conf`: Docker's 127.0.0.11, the cluster DNS in
  Kubernetes, the VPC resolver in ECS.
- Kubernetes: `API_UPSTREAM` is now the full name `<release>-api.<namespace>.svc.cluster.local`,
  because nginx's resolver doesn't use the pod's search domains.
- Verified with nginx before delivery: with a reachable upstream, `/api/ask/stream?x=1` reaches
  the API as `/ask/stream?x=1`; with an unresolvable one, nginx starts, `/healthz` returns 200
  and only `/api/` returns 502.
- Recovery that day: recreate both containers together (`up -d --force-recreate api web`).

## What we learned

1. A proxy shouldn't depend on its upstream to start. Fail the request, not the process.
2. A health check should report the component's own health. Here an unrelated dependency
   took the health endpoint down with it.
3. Hardening carries assumptions: read-only filesystems (6a), Fargate volumes (6c-2) and now
   DNS timing. Each new runtime needs a first real run.

## Interview version

"After a rebuild my UI wouldn't load. The nginx container had exited with 'host not found in
upstream': nginx resolves proxy_pass hostnames once at start-up and refuses to start if one is
missing, so a brief ordering problem took the whole UI and its health check down. I changed it
to resolve per request through the container's DNS resolver, verified that an unreachable API
now gives a 502 on /api only while the UI stays up, and used the full DNS name in Kubernetes,
because nginx's resolver ignores search domains."

## Links

`apps/web/nginx/default.conf.template` · `apps/web/Dockerfile` · `infra/helm/kb-assistant/templates/web.yaml` · Phase 7a guide · incident 0012 (the same image)
