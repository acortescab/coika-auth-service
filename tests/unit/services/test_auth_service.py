import uuid
from typing import cast
from unittest.mock import create_autospec, patch

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core.exceptions.auth import InvalidRegistration, InvalidToken
from app.db.models.player import Player
from app.repositories.player_repository import PlayerRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.schemas.auth import GuestLoginResponse, LoginResponse, RegisterResponse
from app.services.auth_service import AuthService
from app.services.player_service import PlayerService
from app.services.token_service import TokenService


async def test_guest_login_success():
    """
    Tests that guest_login returns a valid AuthResponse
    when a valid device_id is provided.

    This test verifies:
    - PlayerService is called correctly
    - TokenService generates both tokens
    - Response structure is correct
    """
    # Arrange
    player_service = cast(PlayerService, create_autospec(PlayerService))
    token_service = cast(TokenService, create_autospec(TokenService))
    mock_player = cast(Player, create_autospec(Player))

    mock_player.id = uuid.uuid4()
    mock_player.name = "guest_123"

    player_service.get_or_create_guest.return_value = (mock_player, "issued_secret")

    token_service.create_access_token.return_value = "access_token_mock"
    token_service.create_refresh_token.return_value = "refresh_token_mock"

    auth_service = AuthService(player_service, token_service)

    # Act
    result = await auth_service.guest_login("device_123")

    # Assert
    player_service.get_or_create_guest.assert_awaited_once_with("device_123", None)
    token_service.create_access_token.assert_called_once_with(mock_player.id)
    token_service.create_refresh_token.assert_awaited_once_with(mock_player.id)

    assert isinstance(result, GuestLoginResponse)
    assert result.id == mock_player.id
    assert result.name == mock_player.name
    assert result.access_token == "access_token_mock"
    assert result.refresh_token == "refresh_token_mock"
    assert result.device_secret == "issued_secret"
    token_service.commit.assert_awaited_once()

async def test_me_success():
    """
    Tests that /me returns player data when token is valid
    """
    # Arrange
    token_service = cast(TokenService, create_autospec(TokenService))
    player_service = cast(PlayerService, create_autospec(PlayerService))

    payload = {
        "sub": uuid.uuid4()
    }

    token_service.decode_token.return_value = payload

    mock_player = cast(Player, create_autospec(Player))
    mock_player.id = payload["sub"]
    mock_player.name = "test"
    mock_player.email = "email@email.com"
    mock_player.account_type = "registered"

    player_service.get_player_by_id.return_value = mock_player

    auth_service = AuthService(player_service, token_service)

    # Act
    result = await auth_service.me("valid_token")

    # Assert
    token_service.decode_token.assert_called_once_with("valid_token", "access")
    player_service.get_player_by_id.assert_awaited_once_with(payload["sub"])

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
    player_service = cast(PlayerService, create_autospec(PlayerService))

    token_service.decode_token.return_value = None

    auth_service = AuthService(player_service, token_service)

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
    player_service = cast(PlayerService, create_autospec(PlayerService))
    mock_player = cast(Player, create_autospec(Player))

    mock_player.id = uuid.uuid4()
    mock_player.name = "user-123"
    mock_player.email = "email@email.com"

    player_service.register_user.return_value = mock_player

    auth_service = AuthService(player_service, token_service)

    # Act
    result = await auth_service.register_user("email@email.com", "user-123", "1314rdas.z")

    # Assert
    assert player_service.register_user.await_count == 1

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
    player_service = cast(PlayerService, create_autospec(PlayerService))

    mock_player = cast(Player, create_autospec(Player))
    mock_player.id = uuid.uuid4()
    mock_player.name = "user_123"
    mock_player.email = "email@email.com"

    player_service.get_player_by_email.return_value = mock_player

    token_service.create_access_token.return_value = "access_token_mock"
    token_service.create_refresh_token.return_value = "refresh_token_mock"
    
    auth_service = AuthService(player_service, token_service)
    
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
    player_service = cast(PlayerService, create_autospec(PlayerService))

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

    player_service.get_player_by_id.return_value = mock_player
    player_service.get_player_by_email.return_value = None
    player_service.link_account.return_value = mock_player_new
    
    auth_service = AuthService(player_service, token_service)

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
        player_service.get_player_by_email.assert_awaited_once_with("test@example.com")
        player_service.link_account.assert_awaited_once()
        token_service.revoke_token_by_player_id.assert_awaited_once_with(mock_player_new.id)
        token_service.commit.assert_awaited_once()
    

async def test_link_account_email_already_exists():
    """
    Cannot link account if provided email already exists
    """
    # Arrange
    token_service = cast(TokenService, create_autospec(TokenService))
    player_service = cast(PlayerService, create_autospec(PlayerService))
    player_repo = cast(PlayerRepository, create_autospec(PlayerRepository))

    mock_player_new = cast(Player, create_autospec(Player))
    mock_player_new.id = uuid.uuid4()
    mock_player_new.account_type = "guest"
    mock_player_new.device_id = "device_123"

    mock_player = cast(Player, create_autospec(Player))
    mock_player.id = uuid.uuid4()
    mock_player.account_type = "registered"
    mock_player.name = "user-123"
    mock_player.email ="test@example.com" 

    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="refresh_token"
    )

    payload = {
        "sub": uuid.uuid4()
    }

    token_service.decode_token.return_value = payload

    player_repo.get_by_email.return_value = mock_player
    player_repo.get_by_id.return_value = mock_player_new
    player_service.link_account.return_value = mock_player_new

    auth_service = AuthService(player_service, token_service)

    # Act
    try:
        await auth_service.link_account(
            "test@mail.com", 
            "userfake_123", 
            "Password123", 
            credentials
        )

        # Assert
        assert False
    except InvalidRegistration:
        assert True

async def test_link_account_guest_not_found():
    """
    Cannot link if guest account for this device is not found
    """
    # Arrange
    token_service = cast(TokenService, create_autospec(TokenService))
    player_service = cast(PlayerService, create_autospec(PlayerService))
    token_repo = cast(RefreshTokenRepository, create_autospec(RefreshTokenRepository))

    auth_service = AuthService(player_service, token_service)

    token_repo.get_by_jti.return_value = None

    try:
        await auth_service.link_account(
            "test@mail.com",
            "userfake_123",
            "Password123",
            "access_token"
        )
        assert False
    except InvalidRegistration:
        assert True

async def test_login_unknown_email_still_verifies_a_hash():
    """
    Unknown emails must cost the same bcrypt verification as known ones so response time
    does not reveal which emails are registered.
    """
    from unittest.mock import AsyncMock, patch

    from app.core.exceptions.auth import InvalidCredentials
    from app.services.auth_service import AuthService

    player_service = AsyncMock(spec=PlayerService)
    player_service.get_player_by_email.return_value = None
    service = AuthService(player_service, AsyncMock(spec=TokenService))

    with patch("app.services.auth_service.verify_password") as mock_verify:
        with pytest.raises(InvalidCredentials):
            await service.login("nobody@example.com", "whatever1")

    mock_verify.assert_called_once()
