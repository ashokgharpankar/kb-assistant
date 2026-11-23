"""Who is calling? Verifies Amazon Cognito access tokens.

The browser signs in with Cognito's managed login page and sends the access
token on every request:  Authorization: Bearer <JWT>.

A JWT is three base64 parts: header.payload.signature. Cognito signs it with a
private key; anyone can check the signature with the matching public key, which
Cognito publishes as a JWKS (JSON Web Key Set). So the API never calls Cognito
per request: it fetches the public keys once, caches them, and checks locally.

Checks, in order (all must pass):
  1. signature, with the key named by the token's "kid" header, RS256 only
  2. issuer: our user pool, not any other Cognito pool
  3. expiry (exp) and issue time (iat), with a little clock leeway
  4. token_use == "access": an ID token proves identity to the *app*, not
     permission to call an API
  5. client_id == our app client: tokens issued to other clients of the same
     pool are refused (access tokens have no "aud" claim, so this is the check)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from kb_core.settings import Settings, get_settings

log = logging.getLogger("kb_api.auth")


@dataclass(frozen=True)
class User:
    sub: str  # Cognito's stable user ID; use this, not the username, as a key
    username: str
    groups: tuple[str, ...] = ()


LOCAL_USER = User(sub="local", username="local (auth disabled)")


class InvalidToken(Exception):
    """The token is malformed, forged, expired or meant for something else."""


class AuthUnavailable(Exception):
    """We could not fetch the signing keys, so we can't decide either way."""


class TokenVerifier(Protocol):
    def verify(self, token: str) -> User: ...


class KeySource(Protocol):
    """Finds the public key for a token. PyJWKClient in production, a fake in tests."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class CognitoVerifier:
    def __init__(
        self,
        region: str,
        user_pool_id: str,
        client_id: str,
        keys: KeySource | None = None,
        leeway_seconds: int = 30,
    ) -> None:
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.client_id = client_id
        self.leeway = leeway_seconds
        # Keys are cached in memory; an unknown "kid" (Cognito rotated its keys)
        # triggers one refetch, at most every 30 seconds.
        self._keys: KeySource = keys or jwt.PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,
            timeout=5,
        )

    def verify(self, token: str) -> User:
        try:
            key = self._keys.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthUnavailable(str(exc)) from exc
        except (jwt.PyJWKClientError, jwt.DecodeError) as exc:
            raise InvalidToken(f"unknown or unreadable key: {exc}") from exc

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],  # never accept "none" or a different algorithm
                issuer=self.issuer,
                leeway=self.leeway,
                options={
                    "require": ["exp", "iat", "iss", "sub", "token_use", "client_id"],
                    "verify_aud": False,  # access tokens carry client_id instead of aud
                },
            )
        except jwt.InvalidTokenError as exc:
            raise InvalidToken(str(exc)) from exc

        if claims["token_use"] != "access":  # noqa: S105 (a claim value, not a password)
            raise InvalidToken(f"expected an access token, got {claims['token_use']!r}")
        if claims["client_id"] != self.client_id:
            raise InvalidToken("token was issued to a different app client")

        return User(
            sub=claims["sub"],
            username=claims.get("username", claims["sub"]),
            groups=tuple(claims.get("cognito:groups", [])),
        )


def build_verifier(settings: Settings) -> TokenVerifier | None:
    """None means auth is disabled. Fails loudly if Cognito is on but not configured."""
    if settings.auth_mode == "disabled":
        return None
    if not settings.cognito_user_pool_id or not settings.cognito_client_id:
        raise RuntimeError(
            "KB_AUTH_MODE=cognito needs KB_COGNITO_USER_POOL_ID and KB_COGNITO_CLIENT_ID "
            "(run `make cognito-env`). For local tests only, set KB_AUTH_MODE=disabled."
        )
    return CognitoVerifier(
        settings.aws_region, settings.cognito_user_pool_id, settings.cognito_client_id
    )


@lru_cache
def get_verifier() -> TokenVerifier | None:
    return build_verifier(get_settings())


_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    # WWW-Authenticate tells the client which scheme to use (RFC 6750).
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


def require_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier | None, Depends(get_verifier)],
) -> User:
    """FastAPI dependency: the signed-in user, or 401."""
    if verifier is None:
        return LOCAL_USER
    if credentials is None:
        raise _unauthorized("sign in required")
    try:
        return verifier.verify(credentials.credentials)
    except InvalidToken as exc:
        # The reason goes to our logs only: telling the caller exactly which
        # check failed helps an attacker more than a legitimate user.
        log.info("rejected token: %s", exc)
        raise _unauthorized("invalid or expired token") from exc
    except AuthUnavailable as exc:
        log.error("cannot fetch Cognito signing keys: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "sign-in check unavailable"
        ) from exc


CurrentUser = Annotated[User, Depends(require_user)]
