from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.dependencies import get_principal
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/me", tags=["identity"])


class MeResponse(BaseModel):
    """The authenticated caller, as the backend sees them."""

    user_id: str
    tenant_id: str
    roles: list[str]
    is_admin: bool


@router.get("", response_model=MeResponse)
async def get_me(principal: Annotated[Principal, Depends(get_principal)]) -> MeResponse:
    """Return the identity, tenant and roles resolved from the presented API key."""
    return MeResponse(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        roles=sorted(principal.roles),
        is_admin=principal.is_admin,
    )
