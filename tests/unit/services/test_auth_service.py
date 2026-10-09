import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, create_autospec, patch

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.exceptions.auth import InvalidCredentials, InvalidRegistration, InvalidToken
from app.core.security import hash_device_secret
from app.db.models.player import Player, PlayerAccountType
from app.repositories.player_repository import PlayerRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.schemas.auth import GuestLoginResponse, LoginResponse, RegisterResponse
from app.services.auth_service import AuthService
from app.services.token_service import TokenService


def _auth_service_for(player):
    """
    AuthService whose access-token lookup resolves to `player` (None means "no such player").
    """
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    token_service = cast(TokenService, create_autospec(TokenService))

    token_service.decode_token.return_value = {"sub": "player-id"}
    repo.get_by_id.return_value = player

    return AuthService(repo, token_service), repo, token_service


def _linkable_guest(**overrides):
    fields = {"id": uuid.uuid4(), "device_id": "device_123", "account_type": PlayerAccountType.Guest}
    return SimpleNamespace(**{**fields, **overrides})


async def test_guest_login_success():
    """
    Tests that guest_login returns a valid AuthResponse
    when a valid device_id is provided.

    This test verifies:
    - The repository creates the guest with a hashed device secret
    - TokenService generates both tokens
    - Response structure is correct
    """
    # Arrange
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    token_service = cast(TokenService, create_autospec(TokenService))
    mock_player = cast(Player, create_autospec(Player))

    mock_player.id = uuid.uuid4()
    mock_player.name = "guest_123"

    repo.get_by_device_id.return_value = None
    repo.create_guest.return_value = mock_player

    token_service.create_access_token.return_value = "access_token_mock"
    token_service.create_refresh_token.return_value = "refresh_token_mock"

    auth_service = AuthService(repo, token_service)

    # Act
    result = await auth_service.guest_login("device_123")

    # Assert
    repo.get_by_device_id.assert_awaited_once_with("device_123")
    repo.create_guest.assert_awaited_once()
    token_service.create_access_token.assert_called_once_with(mock_player.id)
    token_service.create_refresh_token.assert_awaited_once_with(mock_player.id)

    assert isinstance(result, GuestLoginResponse)
    assert result.id == mock_player.id
    assert result.name == mock_player.name
    assert result.access_token == "access_token_mock"
    assert result.refresh_token == "refresh_token_mock"
    assert result.device_secret
    assert repo.create_guest.call_args.kwargs["device_secret_hash"] == hash_device_secret(result.device_secret)
    token_service.commit.assert_awaited_once()

async def test_me_success():
    """
    Tests that /me returns player data when token is valid
    """
    # Arrange
    token_service = cast(TokenService, create_autospec(TokenService))
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))

    payload = {
        "sub": uuid.uuid4()
    }

    token_service.decode_token.return_value = payload

    mock_player = cast(Player, create_autospec(Player))
    mock_player.id = payload["sub"]
    mock_player.name = "test"
    mock_player.email = "email@email.com"
    mock_player.account_type = "registered"

    repo.get_by_id.return_value = mock_player

    auth_service = AuthService(repo, token_service)

    # Act
    result = await auth_service.me("valid_token")

    # Assert
    token_service.decode_token.assert_called_once_with("valid_token", "access")
    repo.get_by_id.assert_awaited_once_with(payload["sub"])

    assert result.id == mock_player.id
    assert result.name == mock_player.name
    assert result.email == mock_player.email
    assert result.account_type == mock_player.account_type

async def test_logout_refresh_token():
    """
    Tests that logout revokes a single refresh token
    """
    # Arrange
    token_service = cast(TokenService, create_autospec(TokenService))
    token_repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="refresh_token"
    )

    payload = {"jti": "token_123"}

    token_service.decode_token.return_value = payload
    token_repo.revoke_by_jti.return_value = True

    auth_service = AuthService(None, token_service)

    # Act
    await auth_service.logout_player(credentials)

    # Assert
    token_service.decode_token.assert_called_once_with(credentials, "refresh")
    token_service.revoke_token_by_jti.assert_awaited_once_with("token_123")
    token_service.commit.assert_awaited_once()

async def test_me_invalid_token():
    """
    Tests that /me raises error when token is invalid
    """
    # Arrange
    token_service = cast(TokenService, create_autospec(TokenService))
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))

    token_service.decode_token.return_value = None

    auth_service = AuthService(repo, token_service)

    # Act
    try:
        await auth_service.me("bad_token")
        
        # Assert
        assert False
    except InvalidToken:
        token_service.decode_token.assert_called_once()

async def test_register_success():
    """
    Test that register returns a valid RegisteredResponse
    """
    # Arrange
    token_service = cast(TokenService, create_autospec(TokenService))
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    mock_player = cast(Player, create_autospec(Player))

    mock_player.id = uuid.uuid4()
    mock_player.name = "user-123"
    mock_player.email = "email@email.com"

    repo.get_by_email.return_value = None
    repo.create_user.return_value = mock_player

    auth_service = AuthService(repo, token_service)

    # Act
    result = await auth_service.register_user("email@email.com", "user-123", "1314rdas.z")

    # Assert
    repo.create_user.assert_awaited_once_with("email@email.com", "user-123", "1314rdas.z")

    assert isinstance(result, RegisterResponse)
    assert result.id == mock_player.id
    assert result.name == mock_player.name
    assert result.email == mock_player.email

async def test_login_success():
    """
    Test that login returns a valid LoginResponse
    """
    # Arrange
    token_service = cast(TokenService, create_autospec(TokenService))
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))

    mock_player = cast(Player, create_autospec(Player))
    mock_player.id = uuid.uuid4()
    mock_player.name = "user_123"
    mock_player.email = "email@email.com"

    repo.get_by_email.return_value = mock_player

    token_service.create_access_token.return_value = "access_token_mock"
    token_service.create_refresh_token.return_value = "refresh_token_mock"
    
    auth_service = AuthService(repo, token_service)
    
    with patch("app.services.auth_service.verify_password", return_value=True):
        # Act
        result = await auth_service.login("email@email.com", "1314rdas.z")

        # Assert
        assert isinstance(result, LoginResponse)

        assert result.id == mock_player.id
        assert result.name == mock_player.name
        assert result.email == mock_player.email
        assert result.access_token == "access_token_mock"
        assert result.refresh_token == "refresh_token_mock"
    

async def test_link_account_success():
    """
    Guest account should be converted to registered account
    and return new tokens for same player.
    """
    # Arrange
    token_service = cast(TokenService, create_autospec(TokenService))
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))

    mock_player = cast(Player, create_autospec(Player))
    mock_player.id = uuid.uuid4()
    mock_player.account_type = "guest"
    mock_player.device_id ="device_123" 

    mock_player_new = cast(Player, create_autospec(Player))
    mock_player_new.id = mock_player.id
    mock_player_new.account_type = "registered"
    mock_player_new.device_id = None 
    mock_player_new.email = "test@example.com"
    mock_player_new.name = "new_user"

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="refresh_token"
    )

    payload = {
        "sub": uuid.uuid4()
    }

    token_service.decode_token.return_value = payload

    repo.get_by_id.return_value = mock_player
    repo.get_by_email.return_value = None
    repo.upgrade_guest.return_value = mock_player_new
    
    auth_service = AuthService(repo, token_service)

    with patch("app.core.security.hash_password", return_value="hashed_password"):
        
        # Act
        result = await auth_service.link_account(
            email="test@example.com",
            name="new_user",
            password="Password123",
            token=credentials
        )

        # Assert
        assert isinstance(result, RegisterResponse)
        repo.get_by_email.assert_awaited_once_with("test@example.com")
        repo.upgrade_guest.assert_awaited_once()
        token_service.revoke_token_by_player_id.assert_awaited_once_with(mock_player_new.id)
        token_service.commit.assert_awaited_once()
    

async def test_link_account_email_already_exists():
    """
    A valid guest cannot be linked to an email that already belongs to another account.
    """
    service, repo, token_service = _auth_service_for(_linkable_guest())
    repo.get_by_email.return_value = SimpleNamespace(id=uuid.uuid4(), email="test@example.com")

    with pytest.raises(InvalidRegistration, match="Invalid registration"):
        await service.link_account("test@example.com", "userfake_123", "Password123", "access_token")

    # It was rejected by the email lookup (not by a guest guard), and nothing was written
    repo.get_by_email.assert_awaited_once_with("test@example.com")
    repo.upgrade_guest.assert_not_awaited()
    token_service.revoke_token_by_player_id.assert_not_awaited()
    token_service.commit.assert_not_awaited()


async def test_link_account_guest_not_found():
    """
    A valid access token whose player no longer exists cannot link anything: it is rejected as an
    invalid token (401), before the email is even looked up.
    """
    service, repo, token_service = _auth_service_for(None)

    with pytest.raises(InvalidToken):
        await service.link_account("test@example.com", "userfake_123", "Password123", "access_token")

    repo.get_by_id.assert_awaited_once_with("player-id")
    repo.get_by_email.assert_not_awaited()
    repo.upgrade_guest.assert_not_awaited()
    token_service.commit.assert_not_awaited()

async def test_login_unknown_email_still_verifies_a_hash():
    """
    Unknown emails must cost the same bcrypt verification as known ones so response time
    does not reveal which emails are registered.
    """
    repo = AsyncMock(spec=PlayerRepository)
    repo.get_by_email.return_value = None
    service = AuthService(repo, AsyncMock(spec=TokenService))

    with patch("app.services.auth_service.verify_password") as mock_verify:
        with pytest.raises(InvalidCredentials):
            await service.login("nobody@example.com", "whatever1")

    mock_verify.assert_called_once()


async def test_logout_with_invalid_refresh_token_is_rejected():
    """An undecodable refresh token must not reach the database."""
    token_service = cast(TokenService, create_autospec(TokenService))
    token_service.decode_token.return_value = None

    with pytest.raises(InvalidToken):
        await AuthService(None, token_service).logout_player("bad_token")

    token_service.revoke_token_by_jti.assert_not_awaited()
    token_service.commit.assert_not_awaited()


async def test_logout_with_refresh_token_without_jti_is_rejected():
    """Without a jti there is nothing to revoke."""
    token_service = cast(TokenService, create_autospec(TokenService))
    token_service.decode_token.return_value = {"sub": "player-id"}

    with pytest.raises(InvalidToken):
        await AuthService(None, token_service).logout_player("token_without_jti")

    token_service.get_token_by_jti.assert_not_awaited()
    token_service.revoke_token_by_jti.assert_not_awaited()
    token_service.commit.assert_not_awaited()


async def test_login_wrong_password_is_rejected_without_issuing_tokens():
    """A known email with the wrong password must fail before any token is created or stored."""
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    token_service = cast(TokenService, create_autospec(TokenService))
    repo.get_by_email.return_value = SimpleNamespace(id=uuid.uuid4(), password="stored_hash")

    with patch("app.services.auth_service.verify_password", return_value=False):
        with pytest.raises(InvalidCredentials):
            await AuthService(repo, token_service).login("known@example.com", "wrong-password1")

    token_service.create_refresh_token.assert_not_awaited()
    repo.update_last_login.assert_not_awaited()
    token_service.commit.assert_not_awaited()


async def test_access_token_without_sub_is_rejected():
    """The player cannot be looked up without a sub claim."""
    service, repo, token_service = _auth_service_for(None)
    token_service.decode_token.return_value = {"type": "access"}

    with pytest.raises(InvalidToken):
        await service.get_player_by_token("token_without_sub")

    repo.get_by_id.assert_not_awaited()


async def test_access_token_for_unknown_player_is_rejected():
    """A valid token for a player that no longer exists must not authenticate anyone."""
    service, repo, _ = _auth_service_for(None)

    with pytest.raises(InvalidToken):
        await service.me("token_of_deleted_player")

    repo.get_by_id.assert_awaited_once_with("player-id")


@pytest.mark.parametrize(
    "player",
    [
        _linkable_guest(device_id=None),
        _linkable_guest(account_type=PlayerAccountType.Registered),
    ],
    ids=["no-device", "already-registered"],
)
async def test_link_account_rejects_players_that_are_not_linkable_guests(player):
    """Only a guest tied to a device can be upgraded; the rejection must happen before any lookup or write."""
    service, repo, token_service = _auth_service_for(player)

    with pytest.raises(InvalidRegistration):
        await service.link_account("new@example.com", "Alice", "Password123", "access_token")

    repo.get_by_email.assert_not_awaited()
    repo.upgrade_guest.assert_not_awaited()
    token_service.revoke_token_by_player_id.assert_not_awaited()
    token_service.commit.assert_not_awaited()


async def test_link_account_lost_race_is_rejected_and_commits_nothing():
    """If the guest was upgraded by a concurrent request (conditional UPDATE matched nothing), nothing is committed."""
    service, repo, token_service = _auth_service_for(_linkable_guest())
    repo.get_by_email.return_value = None
    repo.upgrade_guest.return_value = None

    with pytest.raises(InvalidRegistration):
        await service.link_account("new@example.com", "Alice", "Password123", "access_token")

    token_service.revoke_token_by_player_id.assert_not_awaited()
    token_service.commit.assert_not_awaited()


def _guest(secret_hash):
    return SimpleNamespace(id=uuid.uuid4(), name="guest-123", device_secret_hash=secret_hash)


def _guest_login_service(repo):
    token_service = cast(TokenService, create_autospec(TokenService))
    token_service.create_access_token.return_value = "access_token_mock"
    token_service.create_refresh_token.return_value = "refresh_token_mock"

    return AuthService(repo, token_service)


async def test_guest_login_new_device_creates_guest_with_hashed_secret_and_generated_name():
    """
    A new device gets a guest account named guest-xxxxxx and a freshly issued secret; only its hash is stored.
    """
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    repo.get_by_device_id.return_value = None
    repo.create_guest.return_value = _guest(None)

    result = await _guest_login_service(repo).guest_login("device_999")

    assert result.device_secret and len(result.device_secret) >= 32
    kwargs = repo.create_guest.call_args.kwargs
    assert kwargs["device_id"] == "device_999"
    assert kwargs["name"].startswith("guest-") and len(kwargs["name"]) == len("guest-") + 6
    assert kwargs["device_secret_hash"] == hash_device_secret(result.device_secret)
    assert kwargs["device_secret_hash"] != result.device_secret
    repo.update_last_login.assert_not_awaited()


async def test_guest_login_correct_secret_logs_in_without_issuing_new_one():
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    existing = _guest(hash_device_secret("the-device-secret"))
    repo.get_by_device_id.return_value = existing

    result = await _guest_login_service(repo).guest_login("device_123", "the-device-secret")

    assert result.id == existing.id
    assert result.device_secret is None
    repo.update_last_login.assert_awaited_once_with(existing.id)
    repo.create_guest.assert_not_awaited()


@pytest.mark.parametrize("provided", [None, "", "wrong-secret"])
async def test_guest_login_missing_or_wrong_secret_is_rejected(provided):
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    repo.get_by_device_id.return_value = _guest(hash_device_secret("the-device-secret"))
    service = _guest_login_service(repo)

    with pytest.raises(InvalidCredentials):
        await service.guest_login("device_123", provided)

    repo.update_last_login.assert_not_awaited()
    service.token_service.commit.assert_not_awaited()


async def test_guest_login_legacy_guest_claims_a_secret():
    """
    A guest created before secrets existed (no hash) gets one on its next login.
    """
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    legacy = _guest(None)
    repo.get_by_device_id.return_value = legacy
    repo.set_device_secret_if_unset.return_value = True

    result = await _guest_login_service(repo).guest_login("device_123")

    assert result.device_secret
    repo.set_device_secret_if_unset.assert_awaited_once_with(legacy.id, hash_device_secret(result.device_secret))
    repo.update_last_login.assert_awaited_once_with(legacy.id)


async def test_guest_login_legacy_claim_lost_race_is_rejected():
    """
    If another request claimed the secret first, this one must not get tokens.
    """
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    repo.get_by_device_id.return_value = _guest(None)
    repo.set_device_secret_if_unset.return_value = False
    service = _guest_login_service(repo)

    with pytest.raises(InvalidCredentials):
        await service.guest_login("device_123")

    service.token_service.create_access_token.assert_not_called()
    service.token_service.commit.assert_not_awaited()


async def test_register_user_with_email_already_in_use_is_rejected():
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    repo.get_by_email.return_value = SimpleNamespace(id=uuid.uuid4())
    service = AuthService(repo, cast(TokenService, create_autospec(TokenService)))

    with pytest.raises(InvalidRegistration, match="Email is already in use"):
        await service.register_user("taken@example.com", "user-123", "1314rdas.z")

    repo.create_user.assert_not_awaited()
    service.token_service.commit.assert_not_awaited()
