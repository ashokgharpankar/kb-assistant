# Phase 2c: Sign-in with Amazon Cognito

**Time:** half a day. **AWS cost:** $0 (Cognito Essentials: 10,000 monthly active users free, no end date).

**You finish with:**

- A Cognito user pool, sign-in page and app client, all in Terraform.
- The web UI asking you to sign in, sending Cognito's access token with every question.
- The API refusing every request without a valid access token, and refusing to start if
  sign-in isn't configured.
- Users invited by you only (no self sign-up), with a temporary password by email.
- Endpoints that get their pipeline and user through FastAPI dependencies, swappable in tests.

The Bedrock switch is the last part of Phase 2c and waits for the quota case. Everything here
works with Ollama.

---

## Part 1: Concepts

### 1. Authentication vs authorization

- **Authentication:** who are you? Cognito checks the password and issues tokens.
- **Authorization:** what may you do? Here: any signed-in user may ask questions. Later
  phases can use Cognito groups (in the token as `cognito:groups`) for roles such as admin.

### 2. OAuth 2.0, OpenID Connect and the three tokens

OAuth 2.0 is a standard for an app to get a token that grants access to an API. OpenID
Connect (OIDC) adds identity on top. Cognito issues three tokens:

| Token | For | Lifetime here | Sent to the API? |
|---|---|---|---|
| **Access token** | Calling APIs: "this request is allowed" | 60 min | **Yes**, as `Authorization: Bearer …` |
| **ID token** | The app: who the user is (email, name) | 60 min | No |
| **Refresh token** | Getting new access and ID tokens without a password | 7 days | No, only to Cognito |

Sending the ID token to an API is a common mistake. Our API checks `token_use == "access"` and
rejects ID tokens.

### 3. What's in a JWT, and how the API checks it without calling Cognito

A JWT (JSON Web Token) is three base64url parts: `header.payload.signature`.

```json
header:  { "kid": "abc123", "alg": "RS256" }
payload: { "sub": "8f2e…", "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXX",
           "client_id": "4abc…", "token_use": "access", "scope": "openid email profile",
           "exp": 1795390000, "iat": 1795386400, "username": "8f2e…" }
```

Cognito signs it with a **private key**. It publishes the matching **public keys** at
`<issuer>/.well-known/jwks.json` (a JWKS). The API downloads them once, caches them, and checks
each token locally. That means no per-request call to Cognito and no AWS permissions needed.
`kid` says which key signed the token. When Cognito rotates keys, an unknown `kid` makes the API
refetch the set (at most every 30 seconds).

The API's five checks, in `apps/api/src/kb_api/auth.py`:

1. **Signature** with the key named by `kid`, **RS256 only**. Allowing `none` or HS256 opens
   well-known forgery attacks; there's a test for HS256.
2. **Issuer** is our user pool, not any Cognito pool in the world.
3. **Expiry** (`exp`) and issue time, with 30 seconds of clock leeway.
4. **`token_use`** is `access`.
5. **`client_id`** is our app client. Access tokens have no `aud` claim, so this is how to
   reject tokens issued to other apps in the same pool.

The payload is only base64, **not encrypted**. Anyone holding a token can read it; only Cognito
can create a valid one. Never put secrets in tokens, and never paste real tokens into websites
that "decode JWTs".

### 4. Authorization code flow with PKCE

The UI is a **public client**: its code runs in the browser, so it can't keep a secret.
PKCE (Proof Key for Code Exchange) replaces the secret:

1. The browser makes a random `code_verifier` and sends only its SHA-256 hash
   (`code_challenge`) when redirecting to Cognito's sign-in page.
2. After the password, Cognito redirects back with a short-lived **authorization code**.
3. The browser exchanges the code **plus the original verifier** for tokens. Cognito checks
   that the verifier matches the hash it saw in step 1.

A stolen authorization code is useless without the verifier, which never left the browser.
The sign-in sequence diagram is in `docs/architecture/README.md`.

### 5. Fail closed

`KB_AUTH_MODE` defaults to `cognito`. If the pool or client ID is missing, the API **refuses to
start** with a message saying what to set. `disabled` exists for tests and the demo, and you
must set it on purpose. A missing setting should never quietly open the API.

The UI is different: with no Cognito settings it simply shows no sign-in screen. That's fine,
because the UI isn't a security boundary. Anyone can call the API without the UI, so the API
must check every request.

### 6. Dependencies instead of globals (step 0)

Endpoints now declare what they need:

```python
@app.post("/ask/stream")
def ask_stream(body: AskRequest, request: Request, pipeline: PipelineDep, user: CurrentUser): ...
```

FastAPI builds `pipeline` with `get_pipeline()` and `user` with `require_user()`, which reads the
`Authorization` header and verifies the token. Tests and the demo swap them with
`app.dependency_overrides[get_pipeline] = FakePipeline`, without monkey-patching module
attributes. The token is checked **before** the stream starts, so a bad token is a clean 401,
not an error event inside a 200 response.

---

## Part 2: What changed in the repo

| Path | What |
|---|---|
| `infra/terraform/envs/dev/cognito.tf` | User pool (Essentials, admin-only sign-up, email sign-in, password policy, optional TOTP MFA), domain with managed login v2, public web client (code + PKCE, 60 min / 7 days), default branding style. |
| `infra/terraform/envs/dev/{variables,outputs}.tf` | `web_app_urls`; outputs for pool ID, client ID, domain, issuer, and ready-to-paste `env_api` / `env_web`. |
| `apps/api/src/kb_api/auth.py` | New: `CognitoVerifier` (5 checks), `require_user` dependency, 401/503 handling, fail-closed config. |
| `apps/api/src/kb_api/main.py` | `Pipeline` protocol; `get_pipeline`, `provider_label` and the user as dependencies; startup check; `/health` reports `auth`. |
| `packages/kb_core/src/kb_core/settings.py` | `auth_mode` (default `cognito`), `cognito_user_pool_id`, `cognito_client_id`. |
| `apps/api/tests/test_auth.py` | 24 tests with tokens signed by a key pair made in the test: valid, expired, other pool, ID token, other client, forged, HS256, unknown key, garbage, missing claim, clock leeway, key endpoint down, config, endpoints. |
| `apps/api/tests/conftest.py` | Every API test starts with auth disabled; auth tests switch it on. |
| `apps/web/src/lib/auth.ts`, `components/AuthGate.tsx`, `main.tsx` | Config from `VITE_COGNITO_*`, OIDC settings, sign-in screen, sign-out through Cognito's `/logout`. |
| `apps/web/src/lib/api.ts`, `hooks/useAsk.ts`, `App.tsx` | Bearer token on requests; user email and Sign out in the header; "Sign in again" on 401. |
| `apps/web/.env.example`, `.env.example` | The new settings. |
| `scripts/demo_api.py` | Uses dependency overrides; sign-in off unless `KB_AUTH_MODE=cognito` is exported. |
| `Makefile` | `tf-output`, `cognito-env`, `cognito-user EMAIL=…`. |
| `docs/adr/0021-authentication-cognito.md` | The decisions. |
| `docs/architecture/README.md` | Cognito and the token check in the current state; the sign-in sequence. |

---

## Part 3: Step by step

### Step 1: Apply and test (10 min)

```bash
cd ~/Projects/kb-assistant          # on the phase-2c branch
unzip -o ~/Downloads/kb-assistant-phase2c.zip -d .
uv sync
make web-setup
make lint test                      # 103 passed, 8 skipped
make web-lint web-test              # 41 passed
```

From now on `make api` refuses to start until Cognito is configured (Step 4). That's the
fail-closed behaviour. Until then, `KB_AUTH_MODE=disabled make api` still works.

### Step 2: Create Cognito with Terraform (10 min)

`backend.hcl` and `terraform.tfvars` are git-ignored. If either is missing (a fresh clone, or a
folder overwritten by Finder), recreate them first: `backend.hcl` points at the state bucket
(`aws s3 ls | grep tfstate`; key `envs/dev/terraform.tfstate`), `terraform.tfvars` from
`terraform.tfvars.example` with the same values as before. Then `make tf-init`. Keep a backup
of both.

```bash
aws login --profile kb-dev           # if your session has expired (direnv sets the profile)
make tf-check                        # format, validate, lint: no AWS calls
make tf-plan                         # expect: 4 to add, 0 to change, 0 to destroy
make tf-apply
```

The 4 resources: `aws_cognito_user_pool.main`, `aws_cognito_user_pool_domain.main`,
`aws_cognito_user_pool_client.web`, `aws_cognito_managed_login_branding.web`.

If the plan shows changes to the **existing** budgets or IAM role, stop and send me the plan.
It should only add Cognito. If `tf-plan` fails on the state backend, your bootstrap state needs
attention (the Phase 0 recovery note); send me the error.

### Step 3: Invite yourself (5 min)

```bash
make cognito-user EMAIL=you@example.com
```

Cognito emails a **temporary password** (valid 3 days) from `no-reply@verificationemail.com`.
Check spam (Gmail: search `from:verificationemail.com`). Sign in with the email you invited and
that temporary password, not your AWS account login: Cognito users are your app's users,
separate from AWS identities. Running the command again for an existing user prints the
command that re-sends the invite (each resend makes a new temporary password). In the AWS console: **Cognito → User pools → kb-assistant-dev-users → Users**, your
user shows **Force change password**.

### Step 4: Configure the API and the UI (5 min)

```bash
make cognito-env
```

It prints two blocks:
- the **first** goes into the repo's `.env`: replace the empty `KB_AUTH_MODE` / `KB_COGNITO_*` lines
  if `.env` already has them;
- the **second** goes into a new file `apps/web/.env.local` (git-ignored; see `apps/web/.env.example`).

None of these values are secrets.

### Step 5: Sign in (10 min)

```bash
make api        # terminal 1: logs "auth: cognito"
make web-dev    # terminal 2 (restart it: Vite reads .env.local at startup)
```

Open http://localhost:5173:

1. **Sign in** sends you to Cognito's page at `…auth.us-east-1.amazoncognito.com`. Look at the
   address bar: `code_challenge`, `code_challenge_method=S256`, `state`.
2. Enter your email and the temporary password. Cognito asks for a **new password**
   (12+ characters, upper, lower, number).
3. You land back on the app, already signed in. The `?code=…&state=…` disappears from the address bar.
4. Your email and **Sign out** are in the header. Ask a question as before.

### Step 6: Look inside the tokens (10 min)

DevTools → **Application → Session storage → http://localhost:5173** → the `oidc.user:…` entry.
It holds `access_token`, `id_token`, `refresh_token` and `expires_at`.

Decode the access token **locally** in the DevTools console (don't paste tokens into websites):

```js
const u = JSON.parse(sessionStorage.getItem(Object.keys(sessionStorage).find(k => k.startsWith('oidc.user')))
const claims = t => JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
claims(u.access_token)   // token_use: "access", client_id, scope, exp
claims(u.id_token)       // token_use: "id", aud, email
```

Compare them: the access token has `client_id` and `scope`; the ID token has `aud` and `email`.

DevTools → **Network** → the `stream` request → **Request headers**: `authorization: Bearer eyJ…`.

### Step 7: Try to break it (10 min)

In a terminal, with a token copied from the console (`copy(u.access_token)` puts it on your clipboard):

```bash
Q='{"question":"How should I design for failure?"}'

# 1. No token
curl -s -X POST localhost:8000/ask -H 'content-type: application/json' -d "$Q"
# {"detail":"sign in required"}

# 2. The ID token instead of the access token
curl -s -X POST localhost:8000/ask -H 'content-type: application/json' -H "Authorization: Bearer <id_token>" -d "$Q"
# {"detail":"invalid or expired token"}; terminal 1 logs: expected an access token, got 'id'

# 3. A tampered token: change one character in the middle of the access token
# {"detail":"invalid or expired token"}; the log says why (signature)

# 4. The real access token
curl -N -X POST localhost:8000/ask/stream -H 'content-type: application/json' -H "Authorization: Bearer <access_token>" -d "$Q"
# the SSE stream
```

The client always gets the same vague message; the reason is only in the server log. Telling
callers which check failed helps an attacker more than a user.

### Step 8: Sign out (2 min)

**Sign out** clears the tokens, ends the Cognito session and returns to the sign-in screen.
Sign in again: Cognito asks for the password, because its session was ended too.

### Step 9: Commit

```bash
git add -A
git commit -m "Phase 2c: Cognito sign-in, token verification in the API, dependencies"
git push -u origin phase-2c
gh pr create --fill && gh pr checks --watch
gh pr merge --squash
```

`apps/web/.env.local` and `.env` are git-ignored. Run `git status` before committing to be sure.

---

## Part 4: Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Identity provider | Cognito Essentials | Auth0, Clerk, Cognito Plus | AWS-native, $0 at this scale; Plus adds threat protection at a per-user cost |
| Who can sign up | Admin invites only | Self sign-up | A public sign-up page would let anyone spend the Bedrock budget |
| Flow | Code + PKCE, public client | Implicit flow; client secret | Implicit is deprecated; a browser can't keep a secret |
| Where tokens are checked | In the API (JWKS cached) | API Gateway / ALB authorizer only | Works locally, in tests and behind any proxy; an edge check can be added in Phase 6 |
| Token sent to the API | Access token | ID token | Access tokens are for APIs; ID tokens for the app |
| Token storage | sessionStorage | httpOnly cookie via a backend-for-frontend | Simpler; the trade-off is exposure to injected scripts, mitigated by safe rendering and CSP |
| Default auth mode | `cognito`, fail closed | `disabled` by default | A missing setting must not open the API |
| Error detail | Generic 401, reason in logs | Detailed 401 | Don't help attackers tune forged tokens |

---

## Part 5: Interview hooks

1. *"How do you secure an API behind a single-page app?"* Authorization code flow with PKCE
   against an OIDC provider; the SPA sends the access token; the API verifies signature,
   issuer, expiry, token type and client on every request using cached public keys.
   Fail closed if configuration is missing.
2. *"Access token vs ID token?"* Access tokens authorize API calls; ID tokens describe the user
   to the client app. APIs should reject ID tokens. Cognito marks them with `token_use`.
3. *"Why PKCE?"* A browser can't keep a client secret. PKCE binds the authorization code to a
   one-time secret that never leaves the browser, so an intercepted code can't be exchanged.
4. *"How does the API verify a JWT without calling the identity provider?"* Public keys from
   the JWKS endpoint, cached; the `kid` header picks the key; refetch on an unknown `kid` for
   key rotation, rate-limited. Only RS256 accepted, to block algorithm-confusion attacks.
5. *"Where do you store tokens in the browser?"* sessionStorage or memory with short-lived
   access tokens, plus strong XSS defences; or a backend-for-frontend with httpOnly cookies when
   the risk justifies the extra server. Name the trade-off rather than claiming one is free.
6. *"How do you keep sign-in cheap?"* Essentials free tier (10,000 MAU), admin-created users so
   nobody can mass-register, no per-request calls to the identity provider.

**Resume line:** "Added Cognito sign-in (Terraform) with authorization code + PKCE, and JWT
verification in a FastAPI dependency (signature, issuer, expiry, token type, client) with
fail-closed configuration and 24 tests covering forged, expired and mis-issued tokens."

---

## Part 6: Done checklist

- [ ] `make lint test` and `make web-lint web-test` pass
- [ ] `make tf-plan` showed only 4 Cognito resources to add; applied
- [ ] Invited yourself, changed the temporary password, signed in through the UI
- [ ] Decoded both tokens locally and compared their claims
- [ ] curl: no token, ID token and tampered token all get 401; the access token streams
- [ ] Sign out ends the Cognito session too
- [ ] Merged through a PR with CI green

**Next:** the Bedrock switch (last part of 2c) as soon as the quota case is resolved: then
`KB_LLM_PROVIDER=bedrock`, Titan embeddings in their own table, and our first cost-per-query
numbers. Phase 3 (evaluation) can start before that on Ollama.
