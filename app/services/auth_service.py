import asyncio
import logging
from uuid import uuid4

from pydantic import EmailStr

from app.core.exceptions.auth import InvalidCredentials, InvalidRegistration, InvalidToken
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    generate_device_secret,
    hash_device_secret,
    verify_device_secret,
    verify_password,
)
from app.db.models.player import PlayerAccountType
from app.repositories.player_repository import PlayerRepository
from app.schemas.auth import GuestLoginResponse, LoginResponse, MeResponse, RegisterResponse
from app.services.token_service import TokenService

logger = logging.getLogger(__name__)

class AuthService:
    """
    Service class for handling authentication-related operations, such as guest login.
    This class interacts with the PlayerRepository to manage player data and uses token
    generation functions to create access and refresh tokens for authenticated players.
    """
    def __init__(self, repo: PlayerRepository, token_service: TokenService):
        """
        Initializes the AuthService with a PlayerRepository and TokenService instance.
        """
        self.repo = repo
        self.token_service = token_service

    async def guest_login(self, device_id: str, device_secret: str | None = None):
        """
        Handles guest login by checking for an existing player with the given device ID or creating a new one if none exists.
        Generates access and refresh tokens for the player and returns an AuthResponse
        containing the player's information and tokens.
        """
        player, issued_secret = await self._get_or_create_guest(device_id, device_secret)

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
        if await self.repo.get_by_email(email):
            logger.warning("registration rejected because email is already in use", extra={"email": email})
            raise InvalidRegistration("Email is already in use")

        player = await self.repo.create_user(email, name, password)

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
        player = await self.repo.get_by_email(email)

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

        await self.repo.update_last_login(player.id)
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

        duplicate = await self.repo.get_by_email(email)

        if duplicate:
            logger.warning("user tried to link account with email that is already used",
                           extra={"email": email, "player_name": name})
            raise InvalidRegistration("Invalid registration")

        player = await self.repo.upgrade_guest(player.id, email, password, name)

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

        player = await self.repo.get_by_id(sub)

        if not player:
            logger.warning("player not found for access token sub", extra={"sub": sub})
            raise InvalidToken("Invalid token")

        return player

    async def _get_or_create_guest(self, device_id: str, device_secret: str | None = None):
        """
        Authenticates a guest by device_id + device_secret, creating the guest on first login.
        Returns (player, issued_secret). issued_secret is only set when a secret was just created
        (new guest, or a legacy guest without a secret claiming one); the client must store it.
        Raises InvalidCredentials when the guest exists and the secret is missing or wrong.
        """
        player = await self.repo.get_by_device_id(device_id)

        if not player:
            secret = generate_device_secret()
            name = self._generate_guest_name()
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

            await self.repo.update_last_login(player.id)
            logger.info("legacy guest claimed a device secret", extra={"player_id": player.id})
            return player, secret

        if not device_secret or not verify_device_secret(device_secret, player.device_secret_hash):
            logger.warning("player tried create or get a guest account with an invalid device secret",
                          extra={"player_id": player.id})
            raise InvalidCredentials("Invalid device credentials")

        await self.repo.update_last_login(player.id)
        return player, None

    def _generate_guest_name(self):
        """
        Generates a random guest name using a UUID.
        """
        return f"guest-{uuid4().hex[:6]}"

    async def _commit(self):
        """
        Commits the unit of work of the current flow. The player repository and TokenService share the
        same writer session, so committing through either one commits everything.
        """
        await self.token_service.commit()
