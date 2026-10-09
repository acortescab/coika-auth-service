from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials

from app.core.exceptions.auth import InvalidToken
from app.core.security import oauth2_scheme
from app.dependencies import get_auth_service
from app.schemas.auth import PlayerPublicResponse
from app.services.auth_service import AuthService

# Public profile of players, used by other services (e.g. the game) to show names
router = APIRouter(prefix="/players", tags=["players"])

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

# Upper bound per request: a ranking page never needs more, and it bounds the IN (...) query
MAX_IDS = 100


@router.get("", response_model=list[PlayerPublicResponse])
# Requires an access token as a header
async def lookup_players(
    token: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    service: AuthServiceDep,
    ids: Annotated[list[UUID], Query(min_length=1, max_length=MAX_IDS)],
):
    """
    Endpoint to get the public profile (id, name) of several players at once.
    Usage: GET /v0/players?ids=<uuid>&ids=<uuid>. Unknown ids are left out of the response.
    """
    try:
        return await service.lookup_players(token.credentials, ids)
    except InvalidToken as e:
        raise HTTPException(status_code=401, detail=str(e))
