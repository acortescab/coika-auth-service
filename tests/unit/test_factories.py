from unittest.mock import create_autospec

from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_lookup_service
from app.factories import create_lookup_service
from app.services.auth_service import AuthService
from app.services.lookup_service import LookupService


def test_create_lookup_service_wires_the_repository_and_an_auth_service():
    write_db = create_autospec(AsyncSession)
    read_db = create_autospec(AsyncSession)

    service = create_lookup_service(write_db, read_db)

    assert isinstance(service, LookupService)
    assert isinstance(service.auth_service, AuthService)
    assert service.repo.write_db is write_db
    assert service.repo.read_db is read_db


async def test_get_lookup_service_dependency_builds_a_lookup_service():
    service = await get_lookup_service(create_autospec(AsyncSession), create_autospec(AsyncSession))

    assert isinstance(service, LookupService)
