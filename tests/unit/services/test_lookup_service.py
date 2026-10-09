import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import create_autospec

import pytest

from app.core.exceptions.auth import InvalidToken
from app.repositories.player_repository import PlayerRepository
from app.services.auth_service import AuthService
from app.services.lookup_service import LookupService


def _lookup_service():
    repo = cast(PlayerRepository, create_autospec(PlayerRepository))
    auth_service = cast(AuthService, create_autospec(AuthService))
    auth_service.get_player_by_token.return_value = SimpleNamespace(id=uuid.uuid4())

    return LookupService(repo, auth_service), repo, auth_service


async def test_lookup_players_returns_only_id_and_name():
    """Other services get the public profile (id, name) of the requested players, nothing else."""
    first, second = uuid.uuid4(), uuid.uuid4()
    service, repo, auth_service = _lookup_service()
    repo.get_public_by_ids.return_value = [
        SimpleNamespace(id=first, name="Ana"),
        SimpleNamespace(id=second, name="Luis"),
    ]

    result = await service.lookup_players("valid_token", [first, second])

    auth_service.get_player_by_token.assert_awaited_once_with("valid_token")
    repo.get_public_by_ids.assert_awaited_once_with([first, second])
    assert [(p.id, p.name) for p in result] == [(first, "Ana"), (second, "Luis")]
    assert set(result[0].model_dump()) == {"id", "name"}


async def test_lookup_players_deduplicates_ids_preserving_order():
    """The repository is queried once, with each id a single time and in first-seen order."""
    first, second = uuid.uuid4(), uuid.uuid4()
    service, repo, _ = _lookup_service()
    repo.get_public_by_ids.return_value = []

    await service.lookup_players("valid_token", [first, second, first])

    repo.get_public_by_ids.assert_awaited_once_with([first, second])


async def test_lookup_players_with_invalid_token_does_not_query_players():
    """Without a valid access token (or for a deleted caller) nobody can enumerate player names."""
    service, repo, auth_service = _lookup_service()
    auth_service.get_player_by_token.side_effect = InvalidToken("Invalid token")

    with pytest.raises(InvalidToken):
        await service.lookup_players("garbage", [uuid.uuid4()])

    repo.get_public_by_ids.assert_not_awaited()
