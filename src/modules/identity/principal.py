import hashlib
from dataclasses import dataclass

DEFAULT_TENANT_ID = "default"
ROLE_MEMBER = "member"
ROLE_ADMIN = "admin"
VALID_ROLES = frozenset({ROLE_MEMBER, ROLE_ADMIN})


@dataclass(frozen=True)
class Principal:
    """Authenticated caller: who they are, which tenant they belong to, and their roles."""

    user_id: str
    tenant_id: str
    roles: frozenset[str] = frozenset({ROLE_MEMBER})

    @property
    def is_admin(self) -> bool:
        return ROLE_ADMIN in self.roles


# Used only when VEKTOR_APP_ENV=development and no API keys are configured.
DEV_PRINCIPAL = Principal(
    user_id="dev",
    tenant_id=DEFAULT_TENANT_ID,
    roles=frozenset({ROLE_ADMIN}),
)


def hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest under which an API key is stored and looked up."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
