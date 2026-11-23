# ADR 0021: Sign-in with Amazon Cognito; the API verifies access tokens itself

**Status:** Accepted, 2026-11-22

## Context

Until Phase 2c anyone who could reach the API could ask questions. Locally that
was harmless; on AWS every answer from Bedrock costs money, and the API will be
on the internet from Phase 6. We need to know who is calling, refuse everyone
else, and keep the cost of sign-in near zero for a handful of users.

## Decision

1. **Amazon Cognito user pool**, Essentials plan, created with Terraform
   (`infra/terraform/envs/dev/cognito.tf`). Managed login (version 2) hosts the
   sign-in page. **No self sign-up**: an admin invites users (`make cognito-user`),
   Cognito emails a temporary password, and the user sets their own.
2. **Public app client with the authorization code flow and PKCE.** No client
   secret (a browser can't keep one). Access and ID tokens last 60 minutes; the
   refresh token 7 days; token revocation and "prevent user existence errors" on.
3. **The API verifies the access token on every request** (`kb_api/auth.py`):
   RS256 signature with Cognito's public keys (JWKS, fetched once and cached),
   issuer = our pool, expiry, `token_use == "access"`, `client_id` = our client.
   The API needs no AWS permissions for this and makes no call to Cognito per request.
4. **Fail closed.** `KB_AUTH_MODE` defaults to `cognito`; the API refuses to
   start if Cognito isn't configured. `disabled` exists for tests and the demo
   and must be set explicitly. `/health` stays open.
5. **UI:** `oidc-client-ts` + `react-oidc-context`; tokens in `sessionStorage`;
   silent renewal with the refresh token; sign-out also ends the Cognito session
   (`/logout` endpoint). The UI runs without sign-in when no Cognito settings are
   present, because the API, not the UI, is the security boundary.
6. Client errors stay generic (`401 invalid or expired token`); the exact reason
   goes to the server log.

## Why (and what was rejected)

| Option | Rejected because |
|---|---|
| API Gateway / ALB JWT authorizer only | We have neither yet, and in-app checks work the same locally, in tests and behind any proxy. Phase 6 may add an ALB check in front as a second layer. |
| ID token sent to the API | ID tokens prove identity to the app; access tokens grant access to an API. Accepting ID tokens is a common mistake, and the check rejects them. |
| AWS Amplify Auth | Large dependency for one sign-in flow; ties the UI to Amplify. |
| Backend-for-frontend with httpOnly cookies | Stronger against token theft by injected scripts, but needs a server-side session store and CSRF protection. Revisit if the app handles sensitive data. Mitigations now: no model output rendered as HTML (ADR 0020), short-lived tokens, a Content-Security-Policy in Phase 6. |
| Self sign-up | Anyone could create an account and spend Bedrock budget. |
| Auth0, Clerk, other providers | Another vendor and bill; Cognito is free at this scale and AWS-native. |
| Cognito Plus plan | Threat protection (compromised-credential checks, adaptive auth) costs per user with no free tier; not needed for a private app. |

## Consequences

- Cost: $0. The Essentials plan includes 10,000 monthly active users for direct
  sign-in, without expiry. Cognito's built-in email sender is limited to 50 emails a day.
- Every environment needs `KB_COGNITO_USER_POOL_ID` and `KB_COGNITO_CLIENT_ID`
  (API) and the matching `VITE_COGNITO_*` values (UI), from `make cognito-env`.
- The CLI (`kb ask`) talks to the database directly and is not covered: it is an
  operator tool on the developer's machine, not a public entry point.
- Each request now carries a stable user ID (`sub`). Phase 7 and 8 use it for
  per-user rate limits and cost per user.
- Tokens in `sessionStorage` are readable by any script on the page; the XSS
  defences above are therefore part of the auth design, not just UI hygiene.
