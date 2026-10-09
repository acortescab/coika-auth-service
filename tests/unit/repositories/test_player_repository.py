import uuid

from app.repositories.player_repository import PlayerRepository


async def test_player_repository_create_and_get(db_session_writer, db_session_reader):
    """
    Unit test for creating a new guest-user.
    """
    repo = PlayerRepository(db_session_writer, db_session_reader)

    created = await repo.create_guest(
        device_id="device_123",
        name="guest-abc"
    )

    player = await repo.get_by_device_id("device_123")

    assert player is not None
    assert player.id == created.id
    assert player.device_id == "device_123"

async def test_update_last_login(db_session_writer, db_session_reader):
    """
    Unit test for updating last login timestamp.
    """
    repo = PlayerRepository(db_session_writer, db_session_reader)

    player = await repo.create_guest(
        device_id="device_999",
        name="guest-test"
    )

    await repo.update_last_login(player.id)

    updated = await repo.get_by_device_id("device_999")

    assert updated.last_login is not None

async def test_register_user(db_session_writer, db_session_reader):
    """
    Unit test creating a new registered-user
    """
    # Arrange
    repo = PlayerRepository(db_session_writer, db_session_reader)

    # Act
    created = await repo.create_user(
        email="email@email.com",
        name="registered_user",
        password="basd13.z112"
    )

    player = await repo.get_by_email("email@email.com")

    # Assert
    assert player is not None
    assert player.account_type == "registered"
    assert player.id == created.id

async def test_upgrade_account(db_session_writer, db_session_reader):
    """
    Unit test for upgrading from guest to registered
    """
    # Arrange
    repo = PlayerRepository(db_session_writer, db_session_reader)
    
    # Act
    player = await repo.create_guest(
        device_id="device_999",
        name="guest-test"
    )

    await repo.upgrade_guest(
        id=player.id,
        email="email@email.com",
        password="basd13.z112",
        name="registered_user"
    )

    player = await repo.get_by_email("email@email.com")

    # Arrange
    assert player is not None
    assert player.account_type == "registered"
    assert player.id == player.id

async def test_get_public_by_ids_returns_only_id_and_name_of_known_players(db_session_writer, db_session_reader):
    """
    Unit test for the public lookup: unknown ids are absent and no private fields are exposed.
    """
    # Arrange
    repo = PlayerRepository(db_session_writer, db_session_reader)
    first = await repo.create_guest(device_id="device_a", name="guest-a")
    second = await repo.create_guest(device_id="device_b", name="guest-b")

    # Act
    rows = await repo.get_public_by_ids([first.id, second.id, uuid.uuid4()])

    # Assert
    assert {(row.id, row.name) for row in rows} == {(first.id, "guest-a"), (second.id, "guest-b")}
    assert set(rows[0]._fields) == {"id", "name"}
