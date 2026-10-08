import logging

from pydantic import EmailStr

from app.core.exceptions.auth import InvalidCredentials, InvalidRegistration, InvalidToken
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.db.models.player import PlayerAccountType
from app.schemas.auth import GuestLoginResponse, LoginResponse, MeResponse, RegisterResponse
from app.services.player_service import PlayerService
from app.services.token_service import TokenService

logger = logging.getLogger(__name__)

class AuthService:
    """
    Service class for handling authentication-related operations, such as guest login. 
    This class interacts with the PlayerRepository to manage player data and uses token 
    generation functions to create access and refresh tokens for authenticated players.
    """
    def __init__(self, player_service: PlayerService, token_service: TokenService):
        """
        Initializes the AuthService with a PlayerService and TokenService instance.
        """
        self.player_service = player_service
        self.token_service = token_service

    def guest_login(self, device_id: str, device_secret: str | None = None):
        """
        Handles guest login by checking for an existing player with the given device ID or creating a new one if none exists.
        Generates access and refresh tokens for the player and returns an AuthResponse 
        containing the player's information and tokens.
        """
        player, issued_secret = self.player_service.get_or_create_guest(device_id, device_secret)

        access_token = self.token_service.create_access_token(player.id)
        refresh_token = self.token_service.create_refresh_token(player.id)

        response = GuestLoginResponse(
            id=player.id,
            name=player.name,
            access_token=access_token,
            refresh_token=refresh_token,
            device_secret=issued_secret
        )

        self._commit()
        return response

    def register_user(self, email: EmailStr, name: str, password: str):
        """
        Registers a player
        """
        player = self.player_service.register_user(email, password, name)

        response = RegisterResponse(
            id=player.id,
            email=player.email,
            name=player.name,
            created_at=player.created_at
        )

        self._commit()
        return response

    def me(self, token: str):
        """
        Returns player from token
        """
        player = self.get_player_by_token(token)

        return MeResponse(
            id=player.id,
            name=player.name,
            email=player.email,
            account_type=player.account_type
        )
    
    def logout_player(self, token: str):
        """
        Logouts a player with valid token revoking it
        """
        payload = self.token_service.decode_token(token, "refresh")

        if not payload:
            logger.info("payload decoding error for refresh token")
            raise InvalidToken("Invalid token")
        
        jti = payload.get("jti")

        if not jti:
            logger.info("payload jti error")
            raise InvalidToken("Invalid token")
        
        self.token_service.revoke_token_by_jti(jti)
        self._commit()

    def login(self, email: EmailStr, password: str):
        """
        Logins a player and returns token
        """
        player = self.player_service.get_player_by_email(email)
 
        if not player:
            logger.info("valid email not found")
            verify_password(password, DUMMY_PASSWORD_HASH)
            raise InvalidCredentials("Invalid login credentials")
        
        if not verify_password(password, player.password):
            logger.info("password hash not valid")
            raise InvalidCredentials("Invalid login credentials")
        
        access_token = self.token_service.create_access_token(player.id)
        refresh_token = self.token_service.create_refresh_token(player.id)

        self.player_service.update_last_login(player.id)

        response = LoginResponse(
            id=player.id,
            name=player.name,
            email=player.email,
            access_token=access_token,
            refresh_token=refresh_token
        )

        self._commit()
        return response

    def link_account(self, email: EmailStr, name: str, password: str, token: str):
        """
        Links a guest-type account to email+password + rename of the username
        """
        player = self.get_player_by_token(token)
        
        if not player or not player.device_id or player.account_type == PlayerAccountType.Registered:
            raise InvalidRegistration("Invalid guest account")
        
        duplicate = self.player_service.get_player_by_email(email)

        if duplicate:
            raise InvalidRegistration("Invalid registration")
        
        player = self.player_service.link_account(player.id, email, password, name)

        if not player:
            raise InvalidRegistration("Invalid registration")
        
        self.token_service.revoke_token_by_player_id(player.id)

        response = RegisterResponse(
            id=player.id,
            email=player.email,
            name=player.name,
            created_at=player.created_at
        )

        # The upgrade and the token revocation commit together.
        self._commit()
        return response

    def _commit(self):
        """
        Commits the unit of work of the current flow. PlayerService and TokenService share the same
        writer session, so committing through either one commits everything.
        """
        self.token_service.commit()

    def get_player_by_token(self, token: str):
        """
        Returns player from token
        """
        payload = self.token_service.decode_token(token, "access")

        if not payload:
            logger.info("payload decoding error for access token")
            raise InvalidToken("Invalid token")
        
        sub = payload.get("sub")

        if not sub:
            logger.info("payload sub error")
            raise InvalidToken("Invalid token")

        player = self.player_service.get_player_by_id(sub)

        logger.info(f"sub value is {sub}")

        if not player:
            logger.info(f"no player found for sub {sub}")
            raise InvalidToken("Invalid token")
        
        return player