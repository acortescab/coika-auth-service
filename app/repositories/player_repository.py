import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions.auth import InvalidCredentials, InvalidRegistration
from app.core.security import hash_password
from app.db.models.player import Player, PlayerAccountType

logger = logging.getLogger(__name__)

class PlayerRepository:
    """
    Repository class for managing player data in the database. 
    This class provides methods for retrieving and creating player records,
    as well as updating player information such as the last login timestamp.
    Write methods only flush; the caller (service layer) decides when to commit.
    """
    
    def __init__(self, write_db: AsyncSession, read_db: AsyncSession):
        """
        Initializes the PlayerRepository with separate read and write database sessions.
        """
        self.write_db = write_db
        self.read_db = read_db

    async def get_by_device_id(self, device_id: str):
        """
        Retrieves a player by their device ID.
        """
        query = select(Player).where(Player.device_id == device_id)
        result = await self.read_db.execute(query)

        return result.scalar_one_or_none()

    async def get_by_id(self, player_id):
        """
        Retrieves a player by their ID.
        """
        query = select(Player).where(Player.id == player_id)
        result = await self.read_db.execute(query)

        return result.scalar_one_or_none()

    async def get_public_by_ids(self, player_ids):
        """
        Retrieves only the public fields (id, name) of the given players.
        Unknown ids are simply absent from the result.
        """
        query = select(Player.id, Player.name).where(Player.id.in_(player_ids))
        result = await self.read_db.execute(query)

        return result.all()

    async def create_guest(self, device_id: str, name: str, device_secret_hash: str | None = None):
        """
        Creates a new player guest.
        """
        player = Player(
            device_id=device_id,
            device_secret_hash=device_secret_hash,
            name=name,
            account_type=PlayerAccountType.Guest
        )

        self.write_db.add(player)

        try:
            await self.write_db.flush()
        except IntegrityError:
            # concurrent first login for the same device_id
            await self.write_db.rollback()
            logger.warning("guest creation conflict, concurrent first login for the same device",
                           extra={"device_id": device_id})
            raise InvalidCredentials("Invalid device credentials")

        await self.write_db.refresh(player)
        return player

    async def set_device_secret_if_unset(self, player_id, device_secret_hash: str) -> bool:
        """
        Stores a device secret only if the player has none yet.
        The conditional UPDATE guarantees that exactly one concurrent claim wins.
        """
        query = update(Player).where(
            Player.id == player_id,
            Player.device_secret_hash.is_(None)
        ).values(device_secret_hash=device_secret_hash).returning(Player.id)

        result = await self.write_db.execute(query)
        return result.scalar_one_or_none() is not None
    
    async def create_user(self, email:str, name:str, password:str):
        """
        Creates a new user
        """
        player = Player(
            email=email,
            name=name,
            password=await asyncio.to_thread(hash_password, password),
            account_type=PlayerAccountType.Registered
        )

        async with self._registration_conflict():
            self.write_db.add(player)
            await self.write_db.flush()

        await self.write_db.refresh(player)
        return player

    @asynccontextmanager
    async def _registration_conflict(self):
        """
        Wraps a statement that writes a registration; a unique-constraint violation (e.g. a concurrent
        signup with the same email) becomes an InvalidRegistration (409) instead of an unhandled 500.
        """
        try:
            yield
        except IntegrityError:
            await self.write_db.rollback()
            logger.warning("registration conflict, unique constraint violated")
            raise InvalidRegistration("Invalid registration")

    async def update_last_login(self, id):
        """
        Updates the last login timestamp for a player.
        """
        query = update(Player).where(Player.id == id).values(last_login=datetime.now(timezone.utc)).returning(Player.id)
        result = await self.write_db.execute(query)

        return result.scalar_one_or_none() is not None
        

    async def get_by_email(self, email:str):
        """
        Retrieves a player by their email
        """
        query = select(Player).where(Player.email == email)
        result = await self.read_db.execute(query)
        
        return result.scalar_one_or_none()
    
    async def upgrade_guest(self, id, email:str, password:str, name: str):
        """
        Upgrades a guest account to registered account
        """
        async with self._registration_conflict():
            query = update(Player).where(
                Player.id == id,
                Player.account_type == PlayerAccountType.Guest,
                Player.device_id.isnot(None)).values(
                    device_id=None,
                    device_secret_hash=None,
                    email=email,
                    password=await asyncio.to_thread(hash_password, password),
                    name=name,
                    account_type=PlayerAccountType.Registered).returning(Player.id)
            result = await self.write_db.execute(query)
            
            if result.scalar_one_or_none() is None:
                logger.warning("guest upgrade matched no rows", extra={"player_id": str(id)})
                return None

        query = select(Player).where(Player.id == id)
        result = await self.write_db.execute(query)

        return result.scalar_one_or_none()
            