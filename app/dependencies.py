from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_read_db, get_write_db
from app.factories import create_auth_service, create_lookup_service, create_token_service

WriteDBDep = Annotated[AsyncSession, Depends(get_write_db)]
ReadDBDep = Annotated[AsyncSession, Depends(get_read_db)]

async def get_auth_service(write_db: WriteDBDep, read_db: ReadDBDep):
    """
    Returns an AuthService instance initialized with the database connection.
    """
    return create_auth_service(write_db, read_db)

async def get_token_service(write_db: WriteDBDep, read_db: ReadDBDep):
    """
    Returns a TokenService instance initialized with the database connection
    """
    return create_token_service(write_db, read_db)

async def get_lookup_service(write_db: WriteDBDep, read_db: ReadDBDep):
    """
    Returns a LookupService instance initialized with the database connection.
    """
    return create_lookup_service(write_db, read_db)