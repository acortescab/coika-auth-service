import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base


def _async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)

# Set up database engines and session makers for reader and writer connections
engine_writer = create_async_engine(_async_url(os.getenv("DATABASE_URL_WRITER")), pool_pre_ping=True)
engine_reader = create_async_engine(_async_url(os.getenv("DATABASE_URL_READER")), pool_pre_ping=True)

# Create session makers for both reader and writer engines
SessionLocalWriter = async_sessionmaker(engine_writer, expire_on_commit=False)
# Session maker for reader engine
SessionLocalReader = async_sessionmaker(engine_reader, expire_on_commit=False)

# Base class for declarative models
Base = declarative_base()

async def get_write_db():
    """
    Dependency function to get a database session for writing operations. 
    This function is used in FastAPI routes to provide a database session that is properly closed after the request is processed.
    Yields: Session: A SQLAlchemy session for database operations.
    """
    async with SessionLocalWriter() as session:
        yield session


async def get_read_db():
    """
    Dependency function to get a database session for reading operations. 
    This function is used in FastAPI routes to provide a database session that is properly closed after the request is processed.
    Yields: Session: A SQLAlchemy session for database operations.
    """
    async with SessionLocalReader() as session:
        yield session