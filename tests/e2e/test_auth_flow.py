
from sqlalchemy import select

from app.db.models.player import Player
from app.db.session import get_read_db, get_write_db


async def test_guest_login_persists_in_db(async_client, get_app, db_session_writer):
    """
    E2E test with real DB validation + isolation for guest login
    """
    # Override get_write_db/get_read_db functions used by the app 'default' behaviour
    # to work with the rollback session db for this test
    get_app.dependency_overrides[get_write_db] = lambda: db_session_writer
    get_app.dependency_overrides[get_read_db] = lambda: db_session_writer

    try:
        response = await async_client.post(
            "/v0/auth/guest-login",
            json={"device_id": "device_123"}
        )

        assert response.status_code == 200

        query = select(Player).where(Player.device_id=="device_123")
        result = await db_session_writer.execute(query)
        
        player = result.scalars().first()

        assert player is not None
    finally:
        # revert functions override
        get_app.dependency_overrides.clear()


async def test_register_persists_in_db(async_client, get_app, db_session_writer):
    """
    E2E test with real DB validation + isolation for register
    """
    # Override get_write_db/get_read_db functions used by the app 'default' behaviour
    # to work with the rollback session db for this test
    get_app.dependency_overrides[get_write_db] = lambda: db_session_writer
    get_app.dependency_overrides[get_read_db] = lambda: db_session_writer

    try:
        response = await async_client.post(
            "/v0/auth/register",
            json={
                "email":"email@email.com",
                "name":"newuser",
                "password":"213daszz!d"
            }
        )

        assert response.status_code == 200

        query = select(Player).where(Player.email=="email@email.com")
        result = await db_session_writer.execute(query)
        player = result.scalars().first()

        assert player is not None
    finally:
        # revert functions override
        get_app.dependency_overrides.clear()


async def test_register_same_email(async_client, get_app, db_session_writer):
    """
    E2E test with real DB multiple times with the same email
    """
    # Override get_write_db/get_read_db functions used by the app 'default' behaviour
    # to work with the rollback session db for this test
    get_app.dependency_overrides[get_write_db] = lambda: db_session_writer
    get_app.dependency_overrides[get_read_db] = lambda: db_session_writer

    try:
        response = await async_client.post(
            "/v0/auth/register",
            json={
                "email":"email@email.com",
                "name":"newuser",
                "password":"213daszz!d"
            }
        )

        assert response.status_code == 200

        response = await async_client.post(
            "/v0/auth/register",
            json={
                "email":"email@email.com",
                "name":"newuser",
                "password":"213daszz!d"
            }
        )

        assert response.status_code == 409
    finally:
        # revert functions override
        get_app.dependency_overrides.clear()


async def test_auth_full_lifecycle(async_client, get_app, db_session_writer):
    """
    E2E test with full auth lifecycle (login-me-refresh-logout)
    """
    # Override get_write_db/get_read_db functions used by the app 'default' behaviour
    # to work with the rollback session db for this test
    get_app.dependency_overrides[get_write_db] = lambda: db_session_writer
    get_app.dependency_overrides[get_read_db] = lambda: db_session_writer

    try:
        # Login
        login_res = await async_client.post(
            "/v0/auth/guest-login",
            json={"device_id": "device_123"}
        )

        assert login_res.status_code == 200

        login_data = login_res.json()
        access_token = login_data["access_token"]
        refresh_token = login_data["refresh_token"]

        # Me
        me_res = await async_client.get(
            "/v0/auth/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        assert me_res.status_code == 200

        # Refresh token
        refresh_res = await async_client.post(
            "/v0/auth/refresh-token",
            json={"refresh_token": refresh_token}
        )

        assert refresh_res.status_code == 200

        data = refresh_res.json()
        access_token = data["access_token"]
        refresh_token = data["refresh_token"]

        # Me
        me_res_2 = await async_client.get(
            "/v0/auth/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        assert me_res_2.status_code == 200

        # Logout
        logout_res = await async_client.post(
            "/v0/auth/logout",
            headers={"Authorization": f"Bearer {refresh_token}"}
        )

        assert logout_res.status_code == 200

        # Refresh should fail post logout
        refresh_fail = await async_client.post(
            "/v0/auth/refresh-token",
            json={"refresh_token": refresh_token}
        )

        assert refresh_fail.status_code == 401

    finally:
        # revert functions override
        get_app.dependency_overrides.clear()


async def test_register_login_sequence(async_client, get_app, db_session_writer):
    """
    E2E test for register + login sequence and refresh token
    """
    # Override get_write_db/get_read_db functions used by the app 'default' behaviour
    # to work with the rollback session db for this test
    get_app.dependency_overrides[get_write_db] = lambda: db_session_writer
    get_app.dependency_overrides[get_read_db] = lambda: db_session_writer

    try:
        login_res = await async_client.post(
            "/v0/auth/login",
            json={
                "email": "email@email.com",
                "password": "1234522a134a"
            }
        )

        assert login_res.status_code == 401

        register_res = await async_client.post(
            "/v0/auth/register",
            json={
                "email": "email@email.com",
                "name": "user",
                "password": "1234522a134a"
            }
        )

        assert register_res.status_code == 200

        login_res = await async_client.post(
            "/v0/auth/login",
            json={
                "email": "email@email.com",
                "password": "1234522a134a"
            }
        )

        assert login_res.status_code == 200

        data = login_res.json()
        refresh_token = data["refresh_token"]

        reuse_res = await async_client.post(
            "/v0/auth/refresh-token",
            json={"refresh_token": refresh_token}
        )

        assert reuse_res.status_code == 200
    finally:
        # revert functions override
        get_app.dependency_overrides.clear()


async def test_refresh_token_rejected_after_logout(async_client, get_app, db_session_writer):
    """
    E2E test to avoid token reuse after logout
    """
    # Override get_write_db/get_read_db functions used by the app 'default' behaviour
    # to work with the rollback session db for this test
    get_app.dependency_overrides[get_write_db] = lambda: db_session_writer
    get_app.dependency_overrides[get_read_db] = lambda: db_session_writer

    try:
        login_res = await async_client.post(
            "/v0/auth/guest-login",
            json={"device_id": "device_456"}
        )

        assert login_res.status_code == 200

        data = login_res.json()
        refresh_token = data["refresh_token"]

        logout_res = await async_client.post(
            "/v0/auth/logout",
            headers={"Authorization": f"Bearer {refresh_token}"}
        )

        assert logout_res.status_code == 200

        reuse_res = await async_client.post(
            "/v0/auth/refresh-token",
            json={"refresh_token": refresh_token}
        )

        assert reuse_res.status_code == 401
    finally:
        # revert functions override
        get_app.dependency_overrides.clear()
    

async def test_guest_link_login(async_client, get_app, db_session_writer):
    """
    E2E test for guest-link-login final cycle
    """
    # Override get_write_db/get_read_db functions used by the app 'default' behaviour
    # to work with the rollback session db for this test
    get_app.dependency_overrides[get_write_db] = lambda: db_session_writer
    get_app.dependency_overrides[get_read_db] = lambda: db_session_writer

    try:
        login_res = await async_client.post(
            "/v0/auth/guest-login",
            json={"device_id": "device_456"}
        )

        assert login_res.status_code == 200

        data = login_res.json()
        access_token = data["access_token"]

        link_res = await async_client.post(
            "/v0/auth/link-account",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "email": "email@email.com",
                "password": "12345as22134",
                "name": "user134"
            }
        )

        assert link_res.status_code == 200

        login_res = await async_client.post(
            "/v0/auth/login",
            json={
                "email": "email@email.com",
                "password": "12345as22134"
            }
        )

        assert login_res.status_code == 200
    finally:
        # revert functions override
        get_app.dependency_overrides.clear()



async def test_guest_login_requires_device_secret(async_client, get_app, db_session_writer):
    """
    E2E test for the device secret: issued once, then required on every later guest login
    """
    get_app.dependency_overrides[get_write_db] = lambda: db_session_writer
    get_app.dependency_overrides[get_read_db] = lambda: db_session_writer

    try:
        first = await async_client.post(
            "/v0/auth/guest-login",
            json={"device_id": "device_secret_1"}
        )
        assert first.status_code == 200
        device_secret = first.json()["device_secret"]
        assert device_secret

        # same device_id without the secret is rejected
        no_secret = await async_client.post(
            "/v0/auth/guest-login",
            json={"device_id": "device_secret_1"}
        )
        assert no_secret.status_code == 401

        wrong_secret = await async_client.post(
            "/v0/auth/guest-login",
            json={"device_id": "device_secret_1", "device_secret": "x" * 43}
        )
        assert wrong_secret.status_code == 401

        # correct secret works and is not issued again
        again = await async_client.post(
            "/v0/auth/guest-login",
            json={"device_id": "device_secret_1", "device_secret": device_secret}
        )
        assert again.status_code == 200
        assert again.json()["device_secret"] is None
        assert again.json()["id"] == first.json()["id"]
    finally:
        get_app.dependency_overrides.clear()
