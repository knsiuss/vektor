from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogItem(BaseModel):
    """Serialized audit record of privileged access."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None
    resource_owner_id: str | None
    created_at: datetime
