# Incident 0012: The image scan blocked a release, and no patched base image existed

**Date:** 2026-11-26 · **Phase:** 6c · **Severity:** high findings, low real exposure
**Status:** Mitigated (OS packages patched; 6 nginx CVEs accepted until 2026-12-03)

## Summary

CI's trivy gate failed the web image: 20 findings (5 CRITICAL, 15 HIGH), all with a fixed version
available. Nothing in our code had changed. CI builds and scans a fresh image every time, and the
vulnerabilities were published after Phase 6a.

| Source | Findings | Fix available? |
|---|---|---|
| nginx 1.30.6 (HTTP/2, HTTP/3, mail proxy, resolver, TLS 1.3 body read) | 6 | nginx 1.30.7 / 1.31.9, released 2026-11-18 |
| Alpine packages: zlib, musl, expat, curl, libxml2, libxslt, brotli | 14 | Yes, in Alpine's repositories |

## Diagnosis

- Pinning `nginxinc/nginx-unprivileged:1.30.7-alpine` failed: **the tag didn't exist**.
- Docker Hub's tag list showed the newest image as `1.31.7-alpine`, from 2026-10-19. A week after
  the nginx security release, the unprivileged image hadn't been rebuilt.
- So there was no image to upgrade to. The choice was: block all deploys, switch base image, or
  accept the nginx findings after checking they can't be reached.

## Resolution

- `RUN apk upgrade --no-cache` in the runtime stage, as root, before `USER 101`. This fixed the
  14 Alpine findings at build time without waiting for the base image.
- The 6 nginx CVEs went into `.trivyignore`, with the reason written down: our config serves
  plain HTTP/1.1 on 8080, with no TLS, HTTP/2, HTTP/3, mail, stream or resolver (TLS ends at
  CloudFront/ALB). Checked with a `grep` of the nginx config, not assumed. Recheck date: 2026-12-03.
- Remove those six entries and pin a version tag as soon as nginx-unprivileged publishes 1.30.7+.

## What we learned

1. A scan gate fails on new CVEs even when your code didn't change. Expect it, and know the options.
2. "Fixed upstream" isn't "fixed in my base image". Base images can lag days or weeks.
3. Accepting a risk is fine if it's written down: which features are vulnerable, why they're off
   in this config, how that was checked, and when to look again. Ignoring the scanner isn't.
4. A floating tag like `stable-alpine` hides which version you ship. A pinned tag makes security
   updates visible changes.

## Interview version

"My image scan blocked a release with five critical findings, including remote code execution
in nginx, and our code hadn't changed. I fixed the operating-system packages at build time. For
nginx, the patched base image didn't exist yet: I checked Docker Hub, and the last build was a
month old. So I confirmed that each vulnerable feature, HTTP/2, HTTP/3, mail, the resolver, was
switched off in our config, recorded the exceptions with a reason and a recheck date, and
planned to pin the patched tag when it lands. The gate did its job; the decision is written down."

## Links

`apps/web/Dockerfile` · `.trivyignore` · ADR 0022 (supply chain) · Phase 6a guide

## Recurrence, Phase 7b (2026-11-27)

The API image (python:3.12-slim-bookworm) failed the same gate on the 7b pull request:
`CVE-2025-6020` (HIGH, libpam path traversal), fixed in Debian `1.5.2-6+deb12u3`, not yet in
the base image. Same fix as the web image: `apt-get upgrade` in the runtime stage. Both images
now take OS security fixes at build time, so the gate only fails when no fix exists at all.
