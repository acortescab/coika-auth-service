import hashlib
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.refresh_token import RefreshToken

logger = logging.getLogger("__name__")

class RefreshTokenRepository:
    """
    Repository for managing refresh tokens.
    """
    def __init__(self, write_db: Session, read_db: Session):
        """
        Initializes the RefreshTokenRepository with separate read and write database sessions.
        """
        self.write_db = write_db
        self.read_db = read_db

    def create(self, player_id, jti, token, expires_at: datetime, family_id=None):
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
        self.write_db.flush()
        return db_token

    def commit(self):
        """
        Commits the pending changes of the writer session.
        Write methods only flush, so the caller decides which operations form one transaction.
        """
        self.write_db.commit()
    
    def get_by_player_id(self, player_id: UUID | str):
        """
        Gets a token by player id
        """
        return self.read_db.query(RefreshToken).filter(
            RefreshToken.player_id == player_id
        ).first()
    
    def get_by_jti(self, jti: str, include_revoked: bool = False, use_writer: bool = False):
        """
        Gets a token by jti.
        When include_revoked is True, it also returns revoked tokens to detect reuse.
        When use_writer is True the primary is queried, so replica lag cannot hide a recent revocation.
        """
        logger.info(f"fetch token request with jti: {jti}, include_revoked={include_revoked}")

        db = self.write_db if use_writer else self.read_db
        query = db.query(RefreshToken).filter(RefreshToken.jti == jti)

        if not include_revoked:
            query = query.filter(~RefreshToken.revoked)

        return query.first()

    def revoke_by_jti(self, jti: str):
        """
        Revokes a token by jti
        """
        logger.info(f"revoke token request with jti: {jti}")

        rows = self.write_db.query(RefreshToken).filter(
            RefreshToken.jti == jti,
            ~RefreshToken.revoked
        ).update(
            {"revoked": True}
        )

        return rows > 0

    def revoke_by_family_id(self, family_id):
        """
        Revokes all active tokens in a family.
        """
        logger.info(f"revoke token family request with family id: {family_id}")

        rows = self.write_db.query(RefreshToken).filter(
            RefreshToken.family_id == family_id,
            ~RefreshToken.revoked
        ).update(
            {"revoked": True}
        )

        return rows > 0
    
    def revoke_by_player_id(self, player_id: UUID | str):
        """
        Revokes a token by player id
        """
        logger.info(f"revoke token request with player id: {player_id}")

        rows = self.write_db.query(RefreshToken).filter(
            RefreshToken.player_id == player_id,
            ~RefreshToken.revoked
        ).update(
            {"revoked": True}
        )

        return rows > 0
