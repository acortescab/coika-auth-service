import logging
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.core.config import get_settings
from app.core.exceptions.auth import InvalidToken
from app.repositories.refresh_token_repository import RefreshTokenRepository

logger = logging.getLogger(__name__)

class TokenService:
    """
    Service class for handling token-related operations, such as creating access and refresh tokens. 
    This class provides methods to generate tokens based on player IDs, 
    which can be used for authentication and session management in the application.
    """
    def __init__(self, repo: RefreshTokenRepository):
        """
        Initializes the TokenService with necessary configurations.
        """
        self.settings = get_settings()
        self.repo = repo
    
    def create_access_token(self, player_id: UUID | str) -> str:
        """
        Creates an access token for the given player ID. 
        """
        payload = {
            "sub": str(player_id),
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            "iat": datetime.now(timezone.utc)
        }

        return self.encode_token(payload)
    
    async def refresh_token(self, refresh_token: str):
        """
        Create a new refresh token and marks previous as revoked.
        If a token from the same family is reused after rotation, revoke the whole family.
        """
        token = self.decode_token(refresh_token, "refresh")

        if not token:
            logger.warning("refresh rejected, token payload is empty")
            raise InvalidToken("Invalid token")

        player_id = token.get("sub")
        jti = token.get("jti")

        if not player_id or not jti:
            logger.warning("refresh rejected, token without sub or jti",
                           extra={"player_id": player_id, "jti": jti})
            raise InvalidToken("Invalid token")

        # Read from the primary: a replica could still show a token as active after it was rotated.
        stored = await self.get_token_by_jti(jti, include_revoked=True, use_writer=True)

        if not stored:
            logger.warning("refresh rejected, token not found", extra={"player_id": player_id, "jti": jti})
            raise InvalidToken("Not found or invalid token")

        # If the token was already revoked, invalidate the entire family and reject the request.
        if stored.revoked:
            logger.warning("refresh token reuse detected, token already revoked",
                           extra={"player_id": player_id, "jti": jti, "family_id": stored.family_id})
            await self._invalidate_family(stored)
            raise InvalidToken("Refresh token reused; family invalidated")

        # Claim the token with a conditional UPDATE (revoked = false -> true) BEFORE issuing new ones.
        # Only one of several concurrent requests can win; the others are treated as reuse.
        revoked = await self.repo.revoke_by_jti(jti)
        if not revoked:
            # Another request already rotated this token; treat this request as reuse.
            logger.warning("refresh token reuse detected, concurrent rotation lost",
                           extra={"player_id": player_id, "jti": jti, "family_id": stored.family_id})
            await self._invalidate_family(stored)
            raise InvalidToken("Refresh token reused; family invalidated")

        family_id = stored.family_id or str(uuid.uuid4())

        access_token = self.create_access_token(player_id)
        new_refresh_token = await self.create_refresh_token(player_id, family_id)

        # Revoking the old token and storing the new one commit together: if anything above fails,
        # nothing is persisted and the client can retry with the old token.
        await self.repo.commit()
        logger.info("refresh token rotated",
                    extra={"player_id": player_id, "old_jti": jti, "family_id": family_id})

        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token
        }

    async def _invalidate_family(self, stored):
        """
        Revokes every active token of the family of a reused refresh token and rejects the request.
        """
        if stored.family_id:
            await self.repo.revoke_by_family_id(stored.family_id)
        # Commit before raising: the request fails, so the revocation would otherwise be rolled back.
        await self.repo.commit()

    async def create_refresh_token(self, player_id: UUID | str, family_id: str | None = None) -> str:
        """
        Creates a refresh token for the given player ID.
        Each refresh-token family shares the same family_id across rotations.
        """
        family_id = family_id or str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        jti = str(uuid.uuid4())

        payload = {
            "sub": str(player_id),
            "jti": jti,
            "family_id": str(family_id),
            "type": "refresh",
            "exp": expires_at,
            "iat": datetime.now(timezone.utc)
        }

        token = self.encode_token(payload)
        await self.repo.create(player_id, jti, token, expires_at, family_id)

        return token

    def encode_token(self, payload: dict) -> str:
        """
        Encodes a payload into a JWT token.
        """
        return jwt.encode(payload, self.settings.SECRET_KEY, algorithm=self.settings.ALGORITHM)

    def decode_token(self, token, token_type: str | None = None):
        """
        Decodes a token and returns the payload using the matching public key.
        When token_type is given ("access" or "refresh"), the token's type claim must match.
        Raises InvalidToken if the token is expired, malformed or of the wrong type.
        """
        try:
            payload = jwt.decode(
                token,
                self.settings.public_key_pem,
                algorithms=[self.settings.ALGORITHM],
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as e:
            logger.warning("token decode failed", extra={"reason": type(e).__name__, "token_type": token_type})
            raise InvalidToken("Invalid token")

        if token_type and payload.get("type") != token_type:
            logger.warning("token type mismatch",
                           extra={"expected": token_type, "received": payload.get("type"), "sub": payload.get("sub")})
            raise InvalidToken("Invalid token")

        return payload
    
    async def get_token_by_jti(self, jti: str, include_revoked: bool = False, use_writer: bool = False):
        """
        Get refresh token by jti.
        """
        return await self.repo.get_by_jti(jti, include_revoked=include_revoked, use_writer=use_writer)
    
    async def commit(self):
        """
        Commits the pending changes of the writer session, which is shared with PlayerService.
        create_refresh_token and the revoke_* methods do not commit on their own.
        """
        await self.repo.commit()

    async def revoke_token_by_jti(self, jti: str):
        """
        Revokes token by jti
        """
        revoked = await self.repo.revoke_by_jti(jti)

        if not revoked:
            logger.warning("revoke rejected, token already revoked or not found", extra={"jti": jti})
            raise InvalidToken("Invalid or revoked token")
        
    async def revoke_token_by_player_id(self, player_id: UUID | str):
        """
        Revokes token by player_id
        """
        await self.repo.revoke_by_player_id(player_id)

    async def revoke_token_by_family_id(self, family_id):
        """
        Revokes all tokens from a family.
        """
        await self.repo.revoke_by_family_id(family_id)

