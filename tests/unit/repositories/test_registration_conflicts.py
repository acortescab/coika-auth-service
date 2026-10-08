from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions.auth import InvalidRegistration
from app.repositories.player_repository import PlayerRepository


def _integrity_error():
    return IntegrityError("INSERT", {}, Exception("duplicate key"))


def _repo_with_flush_error():
    write_db = AsyncMock(spec=AsyncSession)
    write_db.flush.side_effect = _integrity_error()
    return PlayerRepository(write_db, AsyncMock(spec=AsyncSession)), write_db


async def test_create_user_duplicate_email_raises_invalid_registration():
    """A unique-constraint violation on signup must become a 409, not a 500."""
    repo, write_db = _repo_with_flush_error()

    with pytest.raises(InvalidRegistration):
        await repo.create_user("a@b.com", "Alice", "abcdefg1")

    write_db.rollback.assert_awaited_once()


async def test_upgrade_guest_duplicate_email_raises_invalid_registration():
    """The UPDATE itself runs inside upgrade_guest, so the violation surfaces there, not on commit."""
    write_db = AsyncMock(spec=AsyncSession)
    write_db.execute.side_effect = _integrity_error()
    repo = PlayerRepository(write_db, AsyncMock(spec=AsyncSession))

    with pytest.raises(InvalidRegistration):
        await repo.upgrade_guest("id", "a@b.com", "abcdefg1", "Alice")

    write_db.rollback.assert_awaited_once()


async def test_upgrade_guest_not_a_guest_returns_none():
    """The conditional UPDATE matches nothing when the account is no longer a guest."""
    write_db = AsyncMock(spec=AsyncSession)
    write_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    repo = PlayerRepository(write_db, AsyncMock(spec=AsyncSession))

    assert await repo.upgrade_guest("id", "a@b.com", "abcdefg1", "Alice") is None


async def test_update_last_login_unknown_player_is_a_noop():
    write_db = AsyncMock(spec=AsyncSession)
    write_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    repo = PlayerRepository(write_db, AsyncMock(spec=AsyncSession))

    await repo.update_last_login("missing")

    write_db.commit.assert_not_awaited()


async def test_create_guest_concurrent_duplicate_device_is_rejected():
    """Two first logins racing on the same device_id: the loser must not get a second account."""
    from app.core.exceptions.auth import InvalidCredentials

    repo, write_db = _repo_with_flush_error()

    with pytest.raises(InvalidCredentials):
        await repo.create_guest("device_12345", "guest-abc", "hash")

    write_db.rollback.assert_awaited_once()


@pytest.mark.parametrize("returned_id,expected", [("player-id", True), (None, False)])
async def test_set_device_secret_if_unset_reports_whether_it_won(returned_id, expected):
    write_db = AsyncMock(spec=AsyncSession)
    write_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=returned_id))
    repo = PlayerRepository(write_db, AsyncMock(spec=AsyncSession))

    assert await repo.set_device_secret_if_unset("player-id", "hash") is expected


async def test_repository_writes_never_commit():
    """The service layer owns the transaction; repositories only flush."""
    write_db = AsyncMock(spec=AsyncSession)
    write_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value="player-id"))
    repo = PlayerRepository(write_db, AsyncMock(spec=AsyncSession))

    await repo.create_guest("device_12345", "guest-abc", "hash")
    await repo.create_user("a@b.com", "Alice", "abcdefg1")
    await repo.upgrade_guest("id", "a@b.com", "abcdefg1", "Alice")
    await repo.update_last_login("id")
    await repo.set_device_secret_if_unset("id", "hash")

    write_db.commit.assert_not_awaited()
