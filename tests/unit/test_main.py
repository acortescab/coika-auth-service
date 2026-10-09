from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app, lifespan, validate_settings


@pytest.mark.asyncio
async def test_root():
    """
    Test the root endpoint to ensure it returns the expected status and service information.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "OAuth"
    assert "env" in data


@pytest.mark.asyncio
async def test_jwks_endpoint_returns_public_key_set():
    """The app must expose a JWKS document for other services to validate tokens."""
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/.well-known/jwks.json")

    assert response.status_code == 200
    payload = response.json()

    assert "keys" in payload
    assert isinstance(payload["keys"], list)
    assert len(payload["keys"]) > 0

    key = payload["keys"][0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert "n" in key
    assert "e" in key
    assert key["kid"] and key["kid"] != "default"
    # Only the public part may be published
    assert not {"d", "p", "q", "dp", "dq", "qi"} & key.keys()


@pytest.fixture
def database_urls(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_READER", "postgresql://reader")
    monkeypatch.setenv("DATABASE_URL_WRITER", "postgresql://writer")
    return monkeypatch


@pytest.mark.usefixtures("database_urls")
def test_validate_settings_accepts_a_complete_configuration():
    validate_settings(SimpleNamespace(SECRET_KEY="private-key"))


@pytest.mark.parametrize(
    "secret_key,missing_env,message",
    [
        (None, None, "SECRET KEY"),
        ("", None, "SECRET KEY"),
        ("private-key", "DATABASE_URL_READER", "DATABASE_URL_READER"),
        ("private-key", "DATABASE_URL_WRITER", "DATABASE_URL_WRITER"),
    ],
    ids=["no-secret-key", "empty-secret-key", "no-reader-url", "no-writer-url"],
)
def test_validate_settings_rejects_missing_values(database_urls, secret_key, missing_env, message):
    if missing_env:
        database_urls.delenv(missing_env)

    with pytest.raises(RuntimeError, match=message):
        validate_settings(SimpleNamespace(SECRET_KEY=secret_key))


async def test_lifespan_disposes_both_engines_on_shutdown():
    """
    The ASGI test transport never runs the lifespan, so it is exercised directly: the connection pools
    must stay open while serving and be closed exactly once on shutdown.
    """
    with patch("app.main.validate_settings"), \
         patch("app.main.engine_writer", dispose=AsyncMock()) as writer, \
         patch("app.main.engine_reader", dispose=AsyncMock()) as reader:
        async with lifespan(app):
            writer.dispose.assert_not_awaited()
            reader.dispose.assert_not_awaited()

    writer.dispose.assert_awaited_once()
    reader.dispose.assert_awaited_once()


async def test_lifespan_exits_with_error_when_settings_are_invalid():
    """A misconfigured service must stop at startup instead of serving requests it cannot handle."""
    with patch("app.main.validate_settings", side_effect=RuntimeError("SECRET KEY IS NULL")):
        with pytest.raises(SystemExit) as exit_info:
            async with lifespan(app):
                pass

    assert exit_info.value.code == 1