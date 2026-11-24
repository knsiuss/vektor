from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.security import verify_api_key
from modules.identity.oauth_repo import OAuthRepository
from modules.identity.principal import (
    DEFAULT_TENANT_ID,
    DEV_PRINCIPAL,
    ROLE_MEMBER,
    Principal,
    hash_api_key,
)
from modules.identity.repository import ApiKeyRepository, parse_roles


async def resolve_principal(
    *,
    presented_key: str | None,
    session_token: str | None = None,
    legacy_keys: tuple[str, ...],
    allow_open: bool,
    session_factory: async_sessionmaker[AsyncSession],
) -> Principal | None:
    """Map a presented API key to a Principal, or None when the caller is not authenticated.

    Order: per-user database key, then legacy shared keys from VEKTOR_API_KEYS (mapped to a
    member of the default tenant), then open development access. Fails closed otherwise.
    """
    if session_token:
        async with session_factory() as session:
            principal = await OAuthRepository(session).resolve(session_token)
        if principal is not None:
            return principal

    if presented_key:
        key_hash = hash_api_key(presented_key)
        async with session_factory() as session:
            record = await ApiKeyRepository(session).find_active(key_hash)
        if record is not None:
            return Principal(
                user_id=record.user_id,
                tenant_id=record.tenant_id,
                roles=parse_roles(record.roles),
            )
        if legacy_keys and verify_api_key(presented_key, legacy_keys):
            return Principal(
                user_id=f"legacy:{key_hash[:16]}",
                tenant_id=DEFAULT_TENANT_ID,
                roles=frozenset({ROLE_MEMBER}),
            )
    if not legacy_keys and allow_open:
        # Open development access only while nothing is configured. Once a per-user
        # key exists, an anonymous request must be rejected like anywhere else.
        async with session_factory() as session:
            if await ApiKeyRepository(session).has_any_active():
                return None
        return DEV_PRINCIPAL
    return None
