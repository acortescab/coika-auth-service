import logging

from app.repositories.player_repository import PlayerRepository
from app.schemas.lookup import PlayerPublicResponse
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

class LookupService:
    """
    Service class for reading public data of players on behalf of an authenticated caller.
    """
    def __init__(self, repo: PlayerRepository, auth_service: AuthService):
        """
        Initializes the LookupService with a PlayerRepository and the AuthService that authenticates callers.
        """
        self.repo = repo
        self.auth_service = auth_service

    async def lookup_players(self, token: str, player_ids):
        """
        Returns the public profile (id, name) of the given players, leaving out unknown ids.
        Any authenticated player may ask: the data is what the game already shows in its rankings.
        """
        await self.auth_service.get_player_by_token(token)
        players = await self.repo.get_public_by_ids(list(dict.fromkeys(player_ids)))
        logger.info("players looked up", extra={"requested": len(player_ids), "found": len(players)})

        return [PlayerPublicResponse(id=player.id, name=player.name) for player in players]