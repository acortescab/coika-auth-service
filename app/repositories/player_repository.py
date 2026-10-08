import logging
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions.auth import InvalidCredentials, InvalidRegistration
from app.core.security import hash_password
from app.db.models.player import Player, PlayerAccountType

logger = logging.getLogger("__name__")

class PlayerRepository:
    """
    Repository class for managing player data in the database. 
    This class provides methods for retrieving and creating player records,
    as well as updating player information such as the last login timestamp.
    Write methods only flush; the caller (service layer) decides when to commit.
    """
    
    def __init__(self, write_db: Session, read_db: Session):
        """
        Initializes the PlayerRepository with separate read and write database sessions.
        """
        self.write_db = write_db
        self.read_db = read_db

    def get_by_device_id(self, device_id: str):
        """
        Retrieves a player by their device ID.
        """
        return self.read_db.query(Player).filter(
            Player.device_id == device_id
        ).first()

    def get_by_id(self, player_id):
        """
        Retrieves a player by their ID.
        """
        return self.read_db.query(Player).filter(
            Player.id == player_id
        ).first()

    def create_guest(self, device_id: str, name: str, device_secret_hash: str | None = None):
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
            self.write_db.flush()
        except IntegrityError:
            # concurrent first login for the same device_id
            self.write_db.rollback()
            raise InvalidCredentials("Invalid device credentials")

        self.write_db.refresh(player)
        return player

    def set_device_secret_if_unset(self, player_id, device_secret_hash: str) -> bool:
        """
        Stores a device secret only if the player has none yet.
        The conditional UPDATE guarantees that exactly one concurrent claim wins.
        """
        rows = self.write_db.query(Player).filter(
            Player.id == player_id,
            Player.device_secret_hash.is_(None)
        ).update({"device_secret_hash": device_secret_hash})

        return rows > 0
    
    def create_user(self, email:str, name:str, password:str):
        """
        Creates a new user
        """
        player = Player(
            email=email,
            name=name,
            password=hash_password(password),
            account_type=PlayerAccountType.Registered
        )

        with self._registration_conflict():
            self.write_db.add(player)
            self.write_db.flush()

        self.write_db.refresh(player)
        return player

    @contextmanager
    def _registration_conflict(self):
        """
        Wraps a statement that writes a registration; a unique-constraint violation (e.g. a concurrent
        signup with the same email) becomes an InvalidRegistration (409) instead of an unhandled 500.
        """
        try:
            yield
        except IntegrityError:
            self.write_db.rollback()
            raise InvalidRegistration("Invalid registration")

    def update_last_login(self, id):
        """
        Updates the last login timestamp for a player.
        """
        self.write_db.query(Player).filter(
            Player.id == id
        ).update({"last_login": datetime.now(timezone.utc)})

    def get_by_email(self, email:str):
        """
        Retrieves a player by their email
        """
        return self.read_db.query(Player).filter(
            Player.email == email
        ).first()
    
    def upgrade_guest(self, id, email:str, password:str, name: str):
        """
        Upgrades a guest account to registered account
        """
        # The UPDATE runs right here, so the unique-email violation must be caught around it.
        with self._registration_conflict():
            rows = self.write_db.query(Player).filter(
                Player.id == id,
                Player.account_type == PlayerAccountType.Guest,
                Player.device_id.isnot(None)
            ).update({
                "device_id": None,
                "device_secret_hash": None,
                "email": email,
                "password": hash_password(password),
                "name": name,
                "account_type": PlayerAccountType.Registered,
            })

        if rows == 0:
            return None

        return self.write_db.query(Player).filter(Player.id == id).first()
            