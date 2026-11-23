"""Token verification, with tokens signed by a key pair made in the test.

No network and no real Cognito: a fake key source plays the JWKS endpoint.
"""

import time
from dataclasses import dataclass
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from kb_api import main
from kb_api.auth import (
    LOCAL_USER,
    AuthUnavailable,
    CognitoVerifier,
    InvalidToken,
    build_verifier,
    get_verifier,
)
from kb_core.settings import Settings

REGION, POOL, CLIENT = "us-east-1", "us-east-1_TestPool", "test-client-id"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class SigningKey:
    key: Any


class FakeKeys:
    """Stands in for PyJWKClient: knows one key, "k1"."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def get_signing_key_from_jwt(self, token: str) -> SigningKey:
        if self.error:
            raise self.error
        kid = jwt.get_unverified_header(token).get("kid")
        if kid != "k1":
            raise jwt.PyJWKClientError(f'Unable to find a signing key that matches: "{kid}"')
        return SigningKey(KEY.public_key())


def claims(**changes: Any) -> dict[str, Any]:
    now = int(time.time())
    base: dict[str, Any] = {
        "sub": "user-123",
        "username": "ashok",
        "iss": ISSUER,
        "client_id": CLIENT,
        "token_use": "access",
        "scope": "openid email",
        "iat": now,
        "exp": now + 3600,
        "cognito:groups": ["admins"],
    }
    base.update(changes)
    return {k: v for k, v in base.items() if v is not None}  # None removes a claim


def token(key: rsa.RSAPrivateKey = KEY, kid: str = "k1", **changes: Any) -> str:
    return jwt.encode(claims(**changes), key, algorithm="RS256", headers={"kid": kid})


def verifier(keys: FakeKeys | None = None) -> CognitoVerifier:
    return CognitoVerifier(REGION, POOL, CLIENT, keys=keys or FakeKeys())


# --- the verifier -------------------------------------------------------------


def test_a_valid_access_token_gives_the_user() -> None:
    user = verifier().verify(token())
    assert user.sub == "user-123"
    assert user.username == "ashok"
    assert user.groups == ("admins",)


@pytest.mark.parametrize(
    ("bad_token", "reason"),
    [
        (lambda: token(exp=int(time.time()) - 120), "expired"),
        (
            lambda: token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other"),
            "issuer",
        ),
        (lambda: token(token_use="id"), "access token"),  # noqa: S106
        (lambda: token(client_id="someone-elses-client"), "different app client"),
        (lambda: token(key=OTHER_KEY), "Signature"),
        (lambda: token(kid="unknown"), "unknown or unreadable key"),
        (lambda: token(client_id=None), "client_id"),
        (lambda: "not-a-jwt", "unknown or unreadable key"),
    ],
    ids=[
        "expired",
        "other pool",
        "id token",
        "other client",
        "forged",
        "unknown kid",
        "missing claim",
        "garbage",
    ],
)
def test_bad_tokens_are_rejected(bad_token: Any, reason: str) -> None:
    with pytest.raises(InvalidToken, match=reason):
        verifier().verify(bad_token())


def test_a_symmetric_algorithm_is_refused() -> None:
    # "Algorithm confusion": a token signed with HS256 must not be accepted
    # just because it names a known kid. Only RS256 is allowed.
    forged = jwt.encode(
        claims(),
        "a-shared-secret-that-is-at-least-32-bytes",
        algorithm="HS256",
        headers={"kid": "k1"},
    )
    with pytest.raises(InvalidToken):
        verifier().verify(forged)


def test_small_clock_differences_are_tolerated() -> None:
    assert verifier().verify(token(exp=int(time.time()) - 10)).sub == "user-123"


def test_unreachable_key_endpoint_is_not_treated_as_a_bad_token() -> None:
    down = FakeKeys(error=jwt.PyJWKClientConnectionError("timed out"))
    with pytest.raises(AuthUnavailable):
        verifier(down).verify(token())


# --- configuration ------------------------------------------------------------


def test_disabled_auth_builds_no_verifier() -> None:
    assert build_verifier(Settings(_env_file=None, auth_mode="disabled")) is None


def test_cognito_without_ids_fails_loudly() -> None:
    with pytest.raises(RuntimeError, match="KB_COGNITO_USER_POOL_ID"):
        build_verifier(Settings(_env_file=None, auth_mode="cognito"))


def test_cognito_settings_point_at_the_pool() -> None:
    settings = Settings(
        _env_file=None,
        auth_mode="cognito",
        aws_region=REGION,
        cognito_user_pool_id=POOL,
        cognito_client_id=CLIENT,
    )
    built = build_verifier(settings)
    assert isinstance(built, CognitoVerifier)
    assert built.issuer == ISSUER


def test_the_default_is_cognito() -> None:
    # A missing setting must not silently open the API.
    assert Settings(_env_file=None).auth_mode == "cognito"


# --- the endpoints ------------------------------------------------------------


class Pipeline:
    def stream(self, question: str) -> Any:
        raise AssertionError("must not run without a valid token")

    def answer(self, question: str) -> Any:
        raise AssertionError("must not run without a valid token")


@pytest.fixture
def client() -> TestClient:
    main.app.dependency_overrides[get_verifier] = lambda: verifier()
    main.app.dependency_overrides[main.get_pipeline] = lambda: Pipeline()
    return TestClient(main.app)


QUESTION = {"question": "How should I design for failure?"}


@pytest.mark.parametrize("path", ["/ask", "/ask/stream"])
def test_no_token_is_401(client: TestClient, path: str) -> None:
    response = client.post(path, json=QUESTION)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json() == {"detail": "sign in required"}


@pytest.mark.parametrize("path", ["/ask", "/ask/stream"])
def test_a_bad_token_is_401_without_saying_why(client: TestClient, path: str) -> None:
    headers = {"Authorization": f"Bearer {token(token_use='id')}"}  # noqa: S106
    response = client.post(path, json=QUESTION, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid or expired token"}  # no hint which check failed


def test_a_valid_token_reaches_the_pipeline(client: TestClient) -> None:
    from kb_core.models import Answer

    class Ok(Pipeline):
        def answer(self, question: str) -> Answer:
            return Answer(question=question, text="ok", model="m")

    main.app.dependency_overrides[main.get_pipeline] = lambda: Ok()
    response = client.post("/ask", json=QUESTION, headers={"Authorization": f"Bearer {token()}"})
    assert response.status_code == 200
    assert response.json()["answer"] == "ok"


def test_key_endpoint_down_is_503(client: TestClient) -> None:
    down = verifier(FakeKeys(error=jwt.PyJWKClientConnectionError("timed out")))
    main.app.dependency_overrides[get_verifier] = lambda: down
    response = client.post("/ask", json=QUESTION, headers={"Authorization": f"Bearer {token()}"})
    assert response.status_code == 503


def test_health_stays_open(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert "auth" in response.json()


def test_disabled_auth_uses_the_local_user() -> None:
    from kb_api.auth import require_user

    assert require_user(None, None) == LOCAL_USER
