from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.exceptions.auth import InvalidToken
from app.core.security import oauth2_scheme
from app.dependencies import get_lookup_service
from app.schemas.lookup import PlayerLookupRequest, PlayerPublicResponse
from app.services.lookup_service import LookupService

# Public profile of players, used by other services (e.g. the game) to show names
router = APIRouter(prefix="/players", tags=["players"])

LookupServiceDep = Annotated[LookupService, Depends(get_lookup_service)]


@router.post("/lookup", response_model=list[PlayerPublicResponse])
# Requires an access token as a header
async def lookup_players(
    payload: PlayerLookupRequest,
    token: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    service: LookupServiceDep,
):
    """
    Endpoint to get the public profile (id, name) of several players at once.
    It only reads: POST is used so the ids travel in the body instead of a very long URL.
    Unknown ids are left out of the response.
    """
    try:
        return await service.lookup_players(token.credentials, payload.ids)
    except InvalidToken as e:
        raise HTTPException(status_code=401, detail=str(e))
