# Upper bound of ids per lookup: a ranking page never needs more, and it bounds the IN (...) query
from uuid import UUID

from pydantic import BaseModel, Field

MAX_LOOKUP_IDS = 100

class PlayerLookupRequest(BaseModel):
    """
    Request for the public profile of several players. The ids go in the body, not in the URL,
    because 100 UUIDs would make a URL of about 4 KB.
    """
    ids: list[UUID] = Field(min_length=1, max_length=MAX_LOOKUP_IDS)

class PlayerPublicResponse(BaseModel):
    """
    Public profile of a player: what other services may show to anyone (never email or account data).
    """
    id: UUID
    name: str