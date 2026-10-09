import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions.auth import InvalidToken
from app.dependencies import get_auth_service
from app.main import app
from app.schemas.auth import PlayerPublicResponse

AUTH = {"Authorization": "Bearer some-access-token"}


class FakeAuthService:
    """Stands in for AuthService so the route is tested without a database."""

    def __init__(self, players=None, error=None):
        self.players = players or []
        self.error = error
        self.calls = []

    async def lookup_players(self, token, ids):
        self.calls.append((token, ids))
        if self.error:
            raise self.error
        return self.players


@pytest.fixture
def use_service():
    def _use(service):
        app.dependency_overrides[get_auth_service] = lambda: service
        return service

    yield _use
    app.dependency_overrides.pop(get_auth_service, None)


async def get(path, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, **kwargs)


async def test_lookup_returns_the_public_profile(use_service):
    first, second = uuid.uuid4(), uuid.uuid4()
    service = use_service(FakeAuthService([
        PlayerPublicResponse(id=first, name="Ana"),
        PlayerPublicResponse(id=second, name="Luis"),
    ]))

    response = await get(f"/v0/players?ids={first}&ids={second}", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == [
        {"id": str(first), "name": "Ana"},
        {"id": str(second), "name": "Luis"},
    ]
    assert service.calls == [("some-access-token", [first, second])]


async def test_lookup_never_exposes_account_data(use_service):
    """Only id and name leave the auth service, even if the service returned more."""
    pid = uuid.uuid4()
    use_service(FakeAuthService([PlayerPublicResponse(id=pid, name="Ana")]))

    response = await get(f"/v0/players?ids={pid}", headers=AUTH)

    assert set(response.json()[0]) == {"id", "name"}


async def test_lookup_without_token_is_rejected(use_service):
    service = use_service(FakeAuthService())

    response = await get(f"/v0/players?ids={uuid.uuid4()}")

    assert response.status_code in (401, 403)
    assert service.calls == []


async def test_lookup_with_invalid_token_is_401(use_service):
    use_service(FakeAuthService(error=InvalidToken("Invalid token")))

    response = await get(f"/v0/players?ids={uuid.uuid4()}", headers=AUTH)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid token"}


@pytest.mark.parametrize(
    "query",
    ["", "?ids=not-a-uuid", "?" + "&".join(f"ids={uuid.uuid4()}" for _ in range(101))],
    ids=["no-ids", "invalid-uuid", "more-than-100-ids"],
)
async def test_lookup_validates_the_ids(use_service, query):
    service = use_service(FakeAuthService())

    response = await get(f"/v0/players{query}", headers=AUTH)

    assert response.status_code == 422
    assert service.calls == []


async def test_lookup_accepts_exactly_100_ids(use_service):
    service = use_service(FakeAuthService())
    ids = [uuid.uuid4() for _ in range(100)]

    response = await get("/v0/players?" + "&".join(f"ids={i}" for i in ids), headers=AUTH)

    assert response.status_code == 200
    assert response.json() == []
    assert len(service.calls[0][1]) == 100
