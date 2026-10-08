import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from app.db.models.player import Player
from app.repositories.refresh_token_repository import RefreshTokenRepository


async def test_get_by_player_id(db_session_writer, db_session_reader):
    """
    Unit test for fetch refresh token by player_id
    """
    repo_token = RefreshTokenRepository(db_session_writer, db_session_reader)

    player = await create_player_helper(db_session_writer)

    await repo_token.create(
        player_id=player.id,
        jti = uuid.uuid4(),
        token="token_123",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )

    result = await repo_token.get_by_player_id(player.id)

    assert result is not None
    assert result.player_id == player.id

async def test_refresh_token_persistence(db_session_writer, db_session_reader):
    """
    Unit test for RefreshTokenRepository.

    Verifies:
    - token is stored in DB
    - can be retrieved later
    """

    repo_token = RefreshTokenRepository(db_session_writer, db_session_reader)

    token = "token_123"
    token_hashed = hashlib.sha256(token.encode()).hexdigest()

    player = await create_player_helper(db_session_writer)

    await repo_token.create(
        player_id=player.id,
        jti = uuid.uuid4(),
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )

    result = await repo_token.get_by_player_id(player.id)

    assert result is not None
    assert result.token_hash == token_hashed

async def test_get_by_jti_returns_valid_token(db_session_writer, db_session_reader):
    """
    Unit test for fetch a valir refresh token by jti
    """
    repo_token = RefreshTokenRepository(db_session_writer, db_session_reader)
    
    player = await create_player_helper(db_session_writer)

    token_db = await repo_token.create(
        player_id=player.id,
        jti = uuid.uuid4(),
        token="token_123",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )

    result = await repo_token.get_by_jti(token_db.jti)

    assert result is not None
    assert result.jti == token_db.jti
    assert result.revoked is False

async def test_get_by_jti_excludes_revoked(db_session_writer, db_session_reader):
    """
    Unit test to check if revoked tokens are excluded from the query
    """
    repo_token = RefreshTokenRepository(db_session_writer, db_session_reader)

    player = await create_player_helper(db_session_writer)

    token = await repo_token.create(
        player_id=player.id,
        jti = uuid.uuid4(),
        token="token_123",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )

    await repo_token.revoke_by_jti(token.jti)
    result = await repo_token.get_by_jti(token.jti)

    assert result is None

async def test_revoke_by_jti_success(db_session_writer, db_session_reader):
    """
    Unit test to check if revoke is updating db field
    """
    repo_token = RefreshTokenRepository(db_session_writer, db_session_reader)

    player = await create_player_helper(db_session_writer)

    token = await repo_token.create(
        player_id=player.id,
        jti = uuid.uuid4(),
        token="token_123",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )

    result = await repo_token.revoke_by_jti(token.jti)

    assert result is True

    result = await repo_token.get_by_jti(token.jti)

    assert result is None

async def test_revoke_by_jti_returns_false_if_not_found(db_session_writer, db_session_reader):
    """
    Unit test to check revoke by jti when this is not found
    """
    repo = RefreshTokenRepository(db_session_writer, db_session_reader)

    result = await repo.revoke_by_jti(uuid.uuid4())

    assert result is False

async def create_player_helper(db_session_writer):
    """
    Support function for tests that inserts a player into the DB
    """
    player_id = uuid.uuid4()

    player = Player(
        id=player_id,
        device_id="device_123",
        name="name_123"
    )

    db_session_writer.add(player)
    await db_session_writer.commit()

    return player