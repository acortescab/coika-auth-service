import uuid
from typing import cast
from unittest.mock import create_autospec, patch

import pytest

from app.core.exceptions.auth import InvalidToken
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.services.token_service import TokenService


def test_create_access_token_returns_token():
    """
    Tests that create_access_token returns a JWT string
    and encodes correct payload structure.

    This test mocks JWT encoding to isolate logic.
    """
    # Arrange
    repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))
    service = TokenService(repo)

    with patch("app.services.token_service.jwt.encode") as mock_encode:
        mock_encode.return_value = "access_token"

        # Act
        token = service.create_access_token(1)

        # Assert
        mock_encode.assert_called_once()

        args, kwargs = mock_encode.call_args
        payload = args[0]

        assert payload["sub"] == "1"
        assert "exp" in payload
        assert "iat" in payload

        assert token == "access_token"

async def test_create_refresh_token_saves_to_repository():
    """
    Tests that create_refresh_token:
    - generates a JWT token
    - persists it via RefreshTokenRepository
    """
    # Arrange
    repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))
    repo.create.return_value = None

    service = TokenService(repo)

    with patch("app.services.token_service.jwt.encode") as mock_encode:
        mock_encode.return_value = "refresh_token"

        # Act
        token = await service.create_refresh_token(1)

        # Assert
        mock_encode.assert_called_once()
        repo.create.assert_awaited_once()

        args = repo.create.call_args.args
        assert args[0] == 1
        assert args[2] == "refresh_token"
        assert args[4] is not None

        assert token == "refresh_token"

def test_decode_token_returns_payload():
    """
    Tests that decode_token correctly calls jwt.decode
    and returns the decoded payload.
    """
    # Arrange
    repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))
    service = TokenService(repo)

    fake_payload = {
        "sub": "1",
        "type": "access"
    }

    with patch("app.services.token_service.jwt.decode") as mock_decode:
        mock_decode.return_value = fake_payload

        # Act
        result = service.decode_token("fake_token")

        # Assert
        mock_decode.assert_called_once()
        assert result == fake_payload


async def test_refresh_token_rotates_valid_token_and_reuses_family_id():
    """A valid refresh token rotates and keeps the same family."""
    repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))
    service = TokenService(repo)
    family_id = str(uuid.uuid4())

    repo.get_by_jti.return_value = type(
        "StoredToken",
        (),
        {"family_id": family_id, "revoked": False, "jti": "old-jti"},
    )()

    with patch("app.services.token_service.jwt.decode") as mock_decode, patch(
        "app.services.token_service.jwt.encode",
        side_effect=["new_access_token", "new_refresh_token"],
    ):
        mock_decode.return_value = {"sub": "1", "jti": "old-jti", "type": "refresh"}

        result = await service.refresh_token("old_token")

    assert result == {"access_token": "new_access_token", "refresh_token": "new_refresh_token"}
    repo.get_by_jti.assert_awaited_once_with("old-jti", include_revoked=True, use_writer=True)
    repo.revoke_by_jti.assert_awaited_once_with("old-jti")
    assert repo.create.call_args.args[0] == "1"
    assert repo.create.call_args.args[4] == family_id
    repo.commit.assert_awaited_once()


async def test_refresh_token_failure_after_revoke_commits_nothing():
    """
    Revoking the old token and creating the new one are one transaction: if creating fails, nothing
    is committed, so the old token stays valid and the client can retry.
    """
    repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))
    service = TokenService(repo)

    repo.get_by_jti.return_value = type(
        "StoredToken", (), {"family_id": str(uuid.uuid4()), "revoked": False, "jti": "old-jti"}
    )()
    repo.create.side_effect = RuntimeError("db connection lost")

    with patch("app.services.token_service.jwt.decode") as mock_decode, patch(
        "app.services.token_service.jwt.encode", return_value="token"
    ):
        mock_decode.return_value = {"sub": "1", "jti": "old-jti", "type": "refresh"}

        with pytest.raises(RuntimeError):
            await service.refresh_token("old_token")

    repo.revoke_by_jti.assert_awaited_once_with("old-jti")
    repo.commit.assert_not_awaited()


async def test_refresh_token_reuse_invalidates_family():
    """A rotated refresh token cannot be reused; it invalidates the entire family."""
    repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))
    service = TokenService(repo)
    family_id = str(uuid.uuid4())

    repo.get_by_jti.return_value = type(
        "StoredToken",
        (),
        {"family_id": family_id, "revoked": True, "jti": "old-jti"},
    )()

    with patch("app.services.token_service.jwt.decode") as mock_decode:
        mock_decode.return_value = {"sub": "1", "jti": "old-jti", "type": "refresh"}

        with pytest.raises(InvalidToken, match="family"):
            await service.refresh_token("reused_token")

    repo.revoke_by_family_id.assert_awaited_once_with(family_id)
    # The family revocation must be committed even though the request fails.
    repo.commit.assert_awaited_once()

@pytest.fixture
def signing_service():
    """
    TokenService wired with a real, throwaway RSA key pair so tokens are really signed and verified.
    """
    from types import SimpleNamespace

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))
    service = TokenService(repo)
    service.settings = SimpleNamespace(
        SECRET_KEY=private_pem, ALGORITHM="RS256", public_key_pem=public_pem, KID="test-kid"
    )
    return service


def test_decode_token_expired_raises_invalid_token(signing_service):
    """
    An expired token must raise InvalidToken (401) instead of leaking a PyJWT error (500).
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    token = signing_service.encode_token(
        {"sub": "1", "type": "access", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)}
    )

    with pytest.raises(InvalidToken):
        signing_service.decode_token(token, "access")


def test_decode_token_garbage_raises_invalid_token(signing_service):
    """
    A malformed token must raise InvalidToken.
    """
    with pytest.raises(InvalidToken):
        signing_service.decode_token("not-a-jwt")


async def test_decode_token_rejects_wrong_token_type(signing_service):
    """
    A refresh token must not be accepted where an access token is required, and vice versa.
    """
    access = signing_service.create_access_token(1)
    refresh = await signing_service.create_refresh_token(1)

    assert signing_service.decode_token(access, "access")["sub"] == "1"
    assert signing_service.decode_token(refresh, "refresh")["type"] == "refresh"

    with pytest.raises(InvalidToken):
        signing_service.decode_token(refresh, "access")

    with pytest.raises(InvalidToken):
        signing_service.decode_token(access, "refresh")


def test_access_token_carries_issuer_audience_and_kid(signing_service):
    """The game service validates iss/aud and picks the public key by the kid in the header."""
    import jwt

    token = signing_service.create_access_token(1)

    assert jwt.get_unverified_header(token)["kid"] == "test-kid"
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["iss"] == "coika-auth"
    assert claims["aud"] == "coika-game"
    assert claims["type"] == "access"


async def test_refresh_token_has_no_audience_and_still_decodes(signing_service):
    """Refresh tokens are only for the auth service: no aud/iss, and they still decode."""
    refresh = await signing_service.create_refresh_token(1)

    assert "aud" not in __import__("jwt").decode(refresh, options={"verify_signature": False})
    assert signing_service.decode_token(refresh, "refresh")["sub"] == "1"


def test_decode_access_token_with_wrong_audience_raises_invalid_token(signing_service):
    """An access token issued for another service must not be accepted."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    token = signing_service.encode_token(
        {"sub": "1", "type": "access", "iat": now, "exp": now + timedelta(minutes=5),
         "iss": "coika-auth", "aud": "other-service"},
        is_access=True,
    )

    with pytest.raises(InvalidToken):
        signing_service.decode_token(token, "access")


def test_published_jwks_verifies_issued_access_tokens():
    """
    End to end for the game service: a token signed here must be verifiable using ONLY the published
    JWKS, finding the key through the kid in the token header.
    """
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.core.config import Settings

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    settings = Settings(SECRET_KEY=private_pem, ENV="test")
    service = TokenService(cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository)))
    service.settings = settings

    token = service.create_access_token(1)
    jwks = settings.jwks

    kid = jwt.get_unverified_header(token)["kid"]
    assert kid == jwks["keys"][0]["kid"]
    assert kid != "default"
    assert not {"d", "p", "q", "dp", "dq", "qi"} & jwks["keys"][0].keys()

    public_key = jwt.PyJWKSet.from_dict(jwks)[kid].key
    payload = jwt.decode(
        token, public_key, algorithms=["RS256"], audience="coika-game", issuer="coika-auth"
    )
    assert payload["sub"] == "1"


async def test_refresh_token_lost_race_invalidates_family_and_issues_nothing():
    """
    If another request already claimed the token (conditional revoke updates 0 rows), this request is
    treated as reuse: the family is revoked and no new token is created.
    """
    repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))
    service = TokenService(repo)
    family_id = str(uuid.uuid4())

    repo.get_by_jti.return_value = type(
        "StoredToken", (), {"family_id": family_id, "revoked": False, "jti": "old-jti"}
    )()
    repo.revoke_by_jti.return_value = False

    with patch("app.services.token_service.jwt.decode") as mock_decode, patch(
        "app.services.token_service.jwt.encode"
    ) as mock_encode:
        mock_decode.return_value = {"sub": "1", "jti": "old-jti", "type": "refresh"}

        with pytest.raises(InvalidToken, match="family"):
            await service.refresh_token("old_token")

    repo.revoke_by_family_id.assert_awaited_once_with(family_id)
    repo.commit.assert_awaited_once()
    repo.create.assert_not_awaited()
    mock_encode.assert_not_called()


def _service_with_repo():
    repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))
    return TokenService(repo), repo


async def test_refresh_token_with_empty_payload_is_rejected():
    """A refresh token that decodes to nothing must be rejected before touching the database."""
    service, repo = _service_with_repo()

    with patch.object(service, "decode_token", return_value=None):
        with pytest.raises(InvalidToken):
            await service.refresh_token("token")

    repo.get_by_jti.assert_not_awaited()
    repo.commit.assert_not_awaited()


@pytest.mark.parametrize("payload", [{"jti": "old-jti"}, {"sub": "1"}], ids=["no-sub", "no-jti"])
async def test_refresh_token_without_sub_or_jti_is_rejected(payload):
    """Both claims are needed to look the token up and rotate it."""
    service, repo = _service_with_repo()

    with patch.object(service, "decode_token", return_value=payload):
        with pytest.raises(InvalidToken):
            await service.refresh_token("token")

    repo.get_by_jti.assert_not_awaited()
    repo.commit.assert_not_awaited()


async def test_refresh_token_unknown_jti_is_rejected_and_changes_nothing():
    """A validly signed token that is not stored (e.g. wiped from the DB) must not be rotated."""
    service, repo = _service_with_repo()
    repo.get_by_jti.return_value = None

    with patch.object(service, "decode_token", return_value={"sub": "1", "jti": "unknown-jti"}):
        with pytest.raises(InvalidToken, match="Not found"):
            await service.refresh_token("token")

    repo.revoke_by_jti.assert_not_awaited()
    repo.create.assert_not_awaited()
    repo.commit.assert_not_awaited()


async def test_revoke_token_by_jti_rejects_tokens_already_revoked_or_missing():
    """Revoking twice (e.g. logging out twice) must report an invalid token instead of succeeding silently."""
    service, repo = _service_with_repo()
    repo.revoke_by_jti.return_value = False

    with pytest.raises(InvalidToken, match="revoked"):
        await service.revoke_token_by_jti("some-jti")

    repo.revoke_by_jti.assert_awaited_once_with("some-jti")


async def test_revoke_token_by_family_id_delegates_to_the_repository():
    service, repo = _service_with_repo()

    await service.revoke_token_by_family_id("family-1")

    repo.revoke_by_family_id.assert_awaited_once_with("family-1")
