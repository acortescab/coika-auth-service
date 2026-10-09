from app.repositories.player_repository import PlayerRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.services.auth_service import AuthService
from app.services.lookup_service import LookupService
from app.services.token_service import TokenService


def create_auth_service(write_db, read_db):
    """
    Creates an AuthService instance with a PlayerRepository and TokenService.
    """
    repo = PlayerRepository(write_db, read_db)
    token_service = create_token_service(write_db, read_db)
    return AuthService(repo, token_service)

def create_lookup_service(write_db, read_db):
    """
    Creates a LookupService instance with a PlayerRepository and the AuthService that authenticates callers.
    """
    repo = PlayerRepository(write_db, read_db)
    return LookupService(repo, create_auth_service(write_db, read_db))

def create_token_service(write_db, read_db):
    """
    Creates a TokenService instance.
    """
    repo = RefreshTokenRepository(write_db, read_db)
    return TokenService(repo)
