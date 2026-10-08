import hashlib
import logging
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.refresh_token import RefreshToken

logger = logging.getLogger(__name__)

class RefreshTokenRepository:
    """
    Repository for managing refresh tokens.
    """
    def __init__(self, write_db: AsyncSession, read_db: AsyncSession):
        """
        Initializes the RefreshTokenRepository with separate read and write database sessions.
        """
        self.write_db = write_db
        self.read_db = read_db

    async def create(self, player_id, jti, token, expires_at: datetime, family_id=None):
        """
        Creates a new refresh token
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        db_token = RefreshToken(
            player_id=player_id,
            family_id=family_id,
            jti=jti,
            token_hash=token_hash,
            revoked=False,
            expires_at=expires_at,
        )

        self.write_db.add(db_token)
        await self.write_db.flush()
        return db_token
    
    async def get_by_player_id(self, player_id: UUID | str):
        """
        Gets a token by player id
        """
        query = select(RefreshToken).where(RefreshToken.player_id == player_id)
        result = await self.read_db.execute(query)

        return result.scalars().first()
    
    async def get_by_jti(self, jti: str, include_revoked: bool = False, use_writer: bool = False):
        """
        Gets a token by jti.
        When include_revoked is True, it also returns revoked tokens to detect reuse.
        When use_writer is True the primary is queried, so replica lag cannot hide a recent revocation.
        """
        logger.debug("fetch refresh token by jti",
                     extra={"jti": jti, "include_revoked": include_revoked, "use_writer": use_writer})

        db = self.write_db if use_writer else self.read_db
        if include_revoked:
            query = select(RefreshToken).where(RefreshToken.jti == jti)
        else:
            query = select(RefreshToken).where(RefreshToken.jti == jti, ~RefreshToken.revoked)

        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def revoke_by_jti(self, jti: str):
        """
        Revokes a token by jti
        """
        query = update(RefreshToken).where(RefreshToken.jti == jti, ~RefreshToken.revoked).values(
            revoked=True)
        result = await self.write_db.execute(query)

        logger.debug("revoke refresh token by jti", extra={"jti": jti})

        return cast(CursorResult, result).rowcount > 0

    async def revoke_by_family_id(self, family_id):
        """
        Revokes all active tokens in a family.
        """
        query = update(RefreshToken).where(RefreshToken.family_id == family_id, ~RefreshToken.revoked).values(revoked=True)
        result = await self.write_db.execute(query)

        logger.info("revoke refresh token family", extra={"family_id": family_id})

        return cast(CursorResult, result).rowcount > 0
    
    async def revoke_by_player_id(self, player_id: UUID | str):
        """
        Revokes a token by player id
        """
        query = update(RefreshToken).where(RefreshToken.player_id == player_id, ~RefreshToken.revoked).values(revoked=True)
        result = await self.write_db.execute(query)

        logger.info("revoke refresh tokens by player", extra={"player_id": str(player_id)})

        return cast(CursorResult, result).rowcount > 0

    async def commit(self):
        """
        Commits the pending changes of the writer session.
        Write methods only flush, so the caller decides which operations form one transaction.
        """
        await self.write_db.commit()
