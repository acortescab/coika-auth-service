import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import create_autospec

import pytest

from app.core.exceptions.auth import InvalidCredentials
from app.core.security import hash_device_secret
from app.repositories.player_repository import PlayerRepository
from app.services.player_service import PlayerService


def _guest(secret_hash):
    return SimpleNamespace(id=uuid.uuid4(), name="guest-123", device_secret_hash=secret_hash)


async def test_get_or_create_guest_creates_new_player_and_issues_secret():
    """
    A new device gets a guest account and a freshly issued secret; only its hash is stored.
    """
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    repo.get_by_device_id.return_value = None
    created = _guest(None)
    repo.create_guest.return_value = created

    player, secret = await PlayerService(repo).get_or_create_guest("device_999")

    assert player == created
    assert secret and len(secret) >= 32
    kwargs = repo.create_guest.call_args.kwargs
    assert kwargs["device_id"] == "device_999"
    assert kwargs["device_secret_hash"] == hash_device_secret(secret)
    assert kwargs["device_secret_hash"] != secret
    repo.update_last_login.assert_not_awaited()


async def test_get_or_create_guest_correct_secret_logs_in_without_issuing_new_one():
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    existing = _guest(hash_device_secret("the-device-secret"))
    repo.get_by_device_id.return_value = existing

    player, secret = await PlayerService(repo).get_or_create_guest("device_123", "the-device-secret")

    assert player == existing
    assert secret is None
    repo.update_last_login.assert_awaited_once_with(existing.id)
    repo.create_guest.assert_not_awaited()


@pytest.mark.parametrize("provided", [None, "", "wrong-secret"])
async def test_get_or_create_guest_missing_or_wrong_secret_is_rejected(provided):
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    repo.get_by_device_id.return_value = _guest(hash_device_secret("the-device-secret"))

    with pytest.raises(InvalidCredentials):
        await PlayerService(repo).get_or_create_guest("device_123", provided)

    repo.update_last_login.assert_not_awaited()


async def test_get_or_create_guest_legacy_guest_claims_a_secret():
    """
    A guest created before secrets existed (no hash) gets one on its next login.
    """
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    legacy = _guest(None)
    repo.get_by_device_id.return_value = legacy
    repo.set_device_secret_if_unset.return_value = True

    player, secret = await PlayerService(repo).get_or_create_guest("device_123")

    assert player == legacy
    assert secret
    repo.set_device_secret_if_unset.assert_awaited_once_with(legacy.id, hash_device_secret(secret))
    repo.update_last_login.assert_awaited_once_with(legacy.id)


async def test_get_or_create_guest_legacy_claim_lost_race_is_rejected():
    """
    If another request claimed the secret first, this one must not get tokens.
    """
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    repo.get_by_device_id.return_value = _guest(None)
    repo.set_device_secret_if_unset.return_value = False

    with pytest.raises(InvalidCredentials):
        await PlayerService(repo).get_or_create_guest("device_123")

async def test_generate_guest_name_format():
    """
    Tests that generate_guest_name returns a string
    with correct format: guest-xxxxxx
    """
    # Arrange
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    service = PlayerService(repo)

    # Act
    name = service.generate_guest_name()

    # Assert
    assert name.startswith("guest-")
    assert len(name) == len("guest-") + 6