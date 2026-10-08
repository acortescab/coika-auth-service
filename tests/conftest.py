import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine_writer
from app.main import app
from app.main import app as fastapi_app


@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture
async def async_client():
    """
    Provides an async HTTP client for FastAPI tests.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test"
    ) as client:
        yield client

@pytest.fixture
async def db_connection():
    """
    Creates a DB connection with rollback
    """
    async with engine_writer.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()

@pytest.fixture
async def db_session_writer(db_connection):
    """
    Creates the session writer
    """
    async with AsyncSession(bind=db_connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
        yield session

@pytest.fixture
async def db_session_reader(db_connection):
    """
    Creates the session reader
    """
    async with AsyncSession(bind=db_connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
        yield session

@pytest.fixture(autouse=True)
async def clean_db():
    """
    Clear db for tests
    """
    yield

    async with engine_writer.connect() as conn:
        await conn.execute(text("""
            TRUNCATE TABLE
                refresh_tokens,
                players
            RESTART IDENTITY CASCADE;
        """))
        await conn.commit()


@pytest.fixture
def get_app():
    return fastapi_app