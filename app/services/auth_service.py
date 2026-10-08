import asyncio
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

    async def guest_login(self, device_id: str, device_secret: str | None = None):
        """
        Handles guest login by checking for an existing player with the given device ID or creating a new one if none exists.
        Generates access and refresh tokens for the player and returns an AuthResponse 
        containing the player's information and tokens.
        """
        player, issued_secret = await self.player_service.get_or_create_guest(device_id, device_secret)

        access_token = self.token_service.create_access_token(player.id)
        refresh_token = await self.token_service.create_refresh_token(player.id)

        response = GuestLoginResponse(
            id=player.id,
            name=player.name,
            access_token=access_token,
            refresh_token=refresh_token,
            device_secret=issued_secret
        )

        await self._commit()
        logger.info("guest player logged in successfully", extra={"player_id":player.id, "device_id": device_id})

        return response

    async def register_user(self, email: EmailStr, name: str, password: str):
        """
        Registers a player
        """
        player = await self.player_service.register_user(email, password, name)

        response = RegisterResponse(
            id=player.id,
            email=player.email,
            name=player.name,
            created_at=player.created_at
        )

        await self._commit()
        logger.info("player registered in successfully", extra={"player_id":player.id})

        return response

    async def me(self, token: str):
        """
        Returns player from token
        """
        player = await self.get_player_by_token(token)
        logger.info("player fetch himself successfully", extra={"player_id":player.id})

        return MeResponse(
            id=player.id,
            name=player.name,
            email=player.email,
            account_type=player.account_type
        )
    
    async def logout_player(self, token: str):
        """
        Logouts a player with valid token revoking it
        """
        payload = self.token_service.decode_token(token, "refresh")

        if not payload:
            logger.warning("player tried to logout with an invalid refresh token")
            raise InvalidToken("Invalid token")
        
        jti = payload.get("jti")

        if not jti:
            logger.warning("player tried to logout with a refresh token without jti")
            raise InvalidToken("Invalid token")

        refresh_token = await self.token_service.get_token_by_jti(jti, include_revoked=True)
        await self.token_service.revoke_token_by_jti(jti)
        await self._commit()
        logger.info("player logout successfully", 
                    extra={"player_id":refresh_token.player_id, "jti": jti, "family_id": refresh_token.family_id})

    async def login(self, email: EmailStr, password: str):
        """
        Logins a player and returns token
        """
        player = await self.player_service.get_player_by_email(email)
 
        if not player:
            # Pay the same bcrypt cost as a known email so response time does not reveal which emails exist
            await asyncio.to_thread(verify_password, password, DUMMY_PASSWORD_HASH)
            logger.warning("user cannot login because email not found", extra={"email": email})
            raise InvalidCredentials("Invalid login credentials")
        
        if not await asyncio.to_thread(verify_password, password, player.password):
            logger.warning("user cannot login because password encrypt doesn't match", extra={"email": email})
            raise InvalidCredentials("Invalid login credentials")
        
        access_token = self.token_service.create_access_token(player.id)
        refresh_token = await self.token_service.create_refresh_token(player.id)
        logger.info("user login both tokens are created", extra={"player_id":player.id})

        await self.player_service.update_last_login(player.id)
        logger.info("user login last login update", extra={"player_id": player.id})

        response = LoginResponse(
            id=player.id,
            name=player.name,
            email=player.email,
            access_token=access_token,
            refresh_token=refresh_token
        )

        await self._commit()
        logger.info("user login successfully", extra={"player_id":player.id})

        return response

    async def link_account(self, email: EmailStr, name: str, password: str, token: str):
        """
        Links a guest-type account to email+password + rename of the username
        """
        player = await self.get_player_by_token(token)

        if not player:
            logger.warning("user tried to link account with unvalid token", extra={"email": email, "player_name": name})
            raise InvalidRegistration("Invalid guest account")
        
        if not player.device_id:
            logger.warning("user tried to link account with unvalid device", 
                           extra={"email": email, "player_name": name, "device_id":player.device_id })
            raise InvalidRegistration("Invalid guest account")

        if player.account_type == PlayerAccountType.Registered:
            logger.warning("user tried to link account which is already linked", 
                           extra={"email": email, "player_name": name, "account_type":player.account_type})
            raise InvalidRegistration("Invalid guest account")
        
        duplicate = await self.player_service.get_player_by_email(email)

        if duplicate:
            logger.warning("user tried to link account with email that is already used",
                           extra={"email": email, "player_name": name})
            raise InvalidRegistration("Invalid registration")
        
        player = await self.player_service.link_account(player.id, email, password, name)

        if not player:
            logger.warning("user tried to link account but the guest register is optimist-locked",
                           extra={"email": email, "player_name": name})
            raise InvalidRegistration("Invalid registration")
        
        await self.token_service.revoke_token_by_player_id(player.id)
        logger.info("link account previous refresh tokens are revoked",
                    extra={"player_id":player.id, "email": email, "player_name": name}
        )

        response = RegisterResponse(
            id=player.id,
            email=player.email,
            name=player.name,
            created_at=player.created_at
        )

        await self._commit()
        logger.info("link account successfully", extra={"player_id":player.id, "email": email, "player_name": name})

        return response

    async def _commit(self):
        """
        Commits the unit of work of the current flow. PlayerService and TokenService share the same
        writer session, so committing through either one commits everything.
        """
        await self.token_service.commit()

    async def get_player_by_token(self, token: str):
        """
        Returns player from token
        """
        payload = self.token_service.decode_token(token, "access")

        if not payload:
            logger.warning("access token is not valid")
            raise InvalidToken("Invalid token")
        
        sub = payload.get("sub")

        if not sub:
            logger.warning("access token has not valid player_id")
            raise InvalidToken("Invalid token")

        player = await self.player_service.get_player_by_id(sub)

        if not player:
            logger.warning("player not found for access token sub", extra={"sub": sub})
            raise InvalidToken("Invalid token")
        
        return player