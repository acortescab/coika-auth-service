import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions.auth import InvalidToken
from app.dependencies import get_lookup_service
from app.main import app
from app.schemas.lookup import MAX_LOOKUP_IDS, PlayerPublicResponse

URL = "/v0/players/lookup"
AUTH = {"Authorization": "Bearer some-access-token"}


class FakeLookupService:
    """Stands in for LookupService so the route is tested without a database."""

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
        app.dependency_overrides[get_lookup_service] = lambda: service
        return service

    yield _use
    app.dependency_overrides.pop(get_lookup_service, None)


async def post(payload, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(URL, json=payload, **kwargs)


async def test_lookup_returns_the_public_profile(use_service):
    first, second = uuid.uuid4(), uuid.uuid4()
    service = use_service(FakeLookupService([
        PlayerPublicResponse(id=first, name="Ana"),
        PlayerPublicResponse(id=second, name="Luis"),
    ]))

    response = await post({"ids": [str(first), str(second)]}, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == [
        {"id": str(first), "name": "Ana"},
        {"id": str(second), "name": "Luis"},
    ]
    assert service.calls == [("some-access-token", [first, second])]


async def test_lookup_never_exposes_account_data(use_service):
    """Only id and name leave the auth service."""
    pid = uuid.uuid4()
    use_service(FakeLookupService([PlayerPublicResponse(id=pid, name="Ana")]))

    response = await post({"ids": [str(pid)]}, headers=AUTH)

    assert set(response.json()[0]) == {"id", "name"}


async def test_ids_travel_in_the_body_not_in_the_url(use_service):
    """A GET with the ids in the query string must not exist: it would be a ~4 KB URL."""
    use_service(FakeLookupService())
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"{URL}?ids={uuid.uuid4()}", headers=AUTH)

    assert response.status_code == 405


async def test_lookup_without_token_is_rejected(use_service):
    service = use_service(FakeLookupService())

    response = await post({"ids": [str(uuid.uuid4())]})

    assert response.status_code in (401, 403)
    assert service.calls == []


async def test_lookup_with_invalid_token_is_401(use_service):
    use_service(FakeLookupService(error=InvalidToken("Invalid token")))

    response = await post({"ids": [str(uuid.uuid4())]}, headers=AUTH)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid token"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"ids": []},
        {"ids": ["not-a-uuid"]},
        {"ids": [str(uuid.uuid4()) for _ in range(MAX_LOOKUP_IDS + 1)]},
    ],
    ids=["no-ids-field", "empty-list", "invalid-uuid", "more-than-the-maximum"],
)
async def test_lookup_validates_the_ids(use_service, payload):
    service = use_service(FakeLookupService())

    response = await post(payload, headers=AUTH)

    assert response.status_code == 422
    assert service.calls == []


async def test_lookup_accepts_exactly_the_maximum_number_of_ids(use_service):
    service = use_service(FakeLookupService())
    ids = [uuid.uuid4() for _ in range(MAX_LOOKUP_IDS)]

    response = await post({"ids": [str(i) for i in ids]}, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == []
    assert len(service.calls[0][1]) == MAX_LOOKUP_IDS
