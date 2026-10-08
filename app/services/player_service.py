import logging
from uuid import uuid4

from app.core.exceptions.auth import InvalidCredentials, InvalidRegistration
from app.core.security import generate_device_secret, hash_device_secret, verify_device_secret
from app.repositories.player_repository import PlayerRepository

logger = logging.getLogger(__name__)

class PlayerService:
    """
    Service class for managing player-related operations.
    """
    def __init__(self, repo: PlayerRepository):
        """
        Initializes the PlayerService with a PlayerRepository instance.
        """
        self.repo = repo
        
    async def get_or_create_guest(self, device_id: str, device_secret: str | None = None):
        """
        Authenticates a guest by device_id + device_secret, creating the guest on first login.
        Returns (player, issued_secret). issued_secret is only set when a secret was just created
        (new guest, or a legacy guest without a secret claiming one); the client must store it.
        Raises InvalidCredentials when the guest exists and the secret is missing or wrong.
        """
        player = await self.repo.get_by_device_id(device_id)

        if not player:
            secret = generate_device_secret()
            name = self.generate_guest_name()
            player = await self.repo.create_guest(
                device_id=device_id, name=name, device_secret_hash=hash_device_secret(secret)
            )
            logger.info("new guest player created", extra={"player_name": name, "player_id": player.id, "device_id": device_id})
            return player, secret

        if player.device_secret_hash is None:
            # Guest created before device secrets existed: the first login claims one. The conditional
            # update means only one concurrent claim wins.
            secret = generate_device_secret()
            logger.info("legacy guest without device secret, claiming one",
                        extra={"player_id": player.id, "device_id": device_id})

            if not await self.repo.set_device_secret_if_unset(player.id, hash_device_secret(secret)):
                logger.warning("device secret claim lost to a concurrent request",
                               extra={"player_id": player.id, "device_id": device_id})
                raise InvalidCredentials("Invalid device credentials")

            await self.update_last_login(player.id)
            logger.info("legacy guest claimed a device secret", extra={"player_id": player.id})
            return player, secret

        if not device_secret or not verify_device_secret(device_secret, player.device_secret_hash):
            logger.warning("player tried create or get a guest account with an invalid device secret",
                          extra={"player_id": player.id})
            raise InvalidCredentials("Invalid device credentials")

        await self.update_last_login(player.id)
        return player, None
    
    async def register_user(self, email:str, password:str, name: str):
        """
        Register a new player
        """
        player = await self.repo.get_by_email(email)

        if player:
            logger.warning("registration rejected because email is already in use", extra={"email": email})
            raise InvalidRegistration("Email is already in use")
        
        return await self.repo.create_user(email, name, password)
    
    async def get_player_by_id(self, player_id: str):
        """
        Gets player by player_id
        """
        return await self.repo.get_by_id(player_id)
    
    async def get_player_by_email(self, email: str):
        """
        Gets player by email
        """
        return await self.repo.get_by_email(email)

    def generate_guest_name(self):
        """
        Generates a random guest name using a UUID.
        """
        return f"guest-{uuid4().hex[:6]}"
    
    async def link_account(self, player_id: str, email:str, password:str, name: str):
        """
        Upgrade guest account to registered account
        """
        return await self.repo.upgrade_guest(player_id, email, password, name)
    
    async def update_last_login(self, player_id: str):
        """
        Updates last login by player_id
        """
        await self.repo.update_last_login(player_id)
